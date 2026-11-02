"""VIP & Delegation Protection (VIP-01..06, D-42; docs/plan-pilot-vip.md).

- Restricted (VIP-06, §7): only SECURITY_OFFICER, HQ_CRISIS_DIRECTOR, DUTY_OFFICER and the host
  mission's HEAD_OF_MISSION see a visit. For everyone else it does not exist: 404 for every
  visit, segment, change and checklist URL, an empty list and no permissions. VIP events are
  not forwarded to realtime (G-3): the screen polls.
- Segment risk is worked out on every read from ACTIVE incidents, the mission's weather and
  attendees, with its reasons (§3). A virtual segment has no venue risk.
- The detail is read at read time from Fleet, Health and Partners (§4).
- Start, progress and the checklist: a Security Officer or the mission's Head of Mission;
  cancel: the HQ Crisis Director (§5, G-9). The departure completed completes the visit.
- Programme changes: a Security Officer proposes; the mission's Head of Mission or the HQ
  Crisis Director, another person, decides through approvals.decide() (§6, D-05, D-16).
- Every check goes through app/core/approvals.py (D-29). No position anywhere (VIP-04). Audit
  gives references, sequence numbers, statuses and counts, never venues, times, reasons or
  the principal's role (VIP-06).
"""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core import approvals, audit
from app.core.security import CurrentUser
from app.modules.documents.service import Scope
from app.modules.fleet import service as fleet
from app.modules.intel.fusion import CATEGORY_LABELS
from app.modules.people.models import Mission
from app.modules.tenancy.models import AppUser
from app.modules.tenancy.service import Actor
from app.modules.vip import schemas
from app.modules.vip.models import VipChecklistItem, VipSegment, VipSegmentChange, VipVisit

READERS = "SECURITY_OFFICER|HQ_CRISIS_DIRECTOR|DUTY_OFFICER|HEAD_OF_MISSION"  # §63 Q2
ACTORS = "SECURITY_OFFICER|HEAD_OF_MISSION"  # start, progress, checklist (G-9)
PROPOSER = "SECURITY_OFFICER"  # VIP-05
DECIDERS = "HEAD_OF_MISSION|HQ_CRISIS_DIRECTOR"  # VIP-05, G-1
CANCELLER = "HQ_CRISIS_DIRECTOR"  # VIP-04
PROGRESS = Actor(type="SYSTEM", id="visit progress (simulated)")

HIGH_M = 2_000  # from the venue to the edge of an ACTIVE incident's zone (VIP-02)
MODERATE_M = 5_000
CROWD = 500
SEVERE_WEATHER = ("STORM",)
LEVELS = ("LOW", "MODERATE", "HIGH", "CRITICAL")  # CRITICAL only from the country risk
RECOMMENDATION = "Move it out of the window, or replace it with a virtual alternative"
FINAL = ("COMPLETED", "CANCELLED")
NEXT = {"PLANNED": "IN_PROGRESS", "IN_PROGRESS": "COMPLETED"}
SURVEY = "venue survey"  # a checklist label ending so is a venue survey (G-2)
NOT_FOUND = "Visit not found"


class VipError(Exception):
    """The request cannot be done: status_code 403, 404, 409 or 422."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def _user(user: CurrentUser) -> Actor:
    return Actor(type="USER", id=str(user.id))


async def _audit(
    session: AsyncSession, actor: Actor, action: str, visit: VipVisit, details: dict[str, Any]
) -> None:
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action=f"VIP.{action}",
        entity_type="vip_visit",
        entity_id=visit.reference,
        details=details,
    )


# --- who sees a visit (VIP-06, §7) --------------------------------------------------------------


async def reader_scope(session: AsyncSession, user: CurrentUser) -> Scope | None:
    """The missions whose visits the caller sees: the union of their READERS grants (as
    evacuations.name_scope()); None if they hold none."""
    codes = approvals.parse_role_codes(READERS)
    grants = [g for g in await approvals.roles_of(session, user.id) if g.code in codes]
    if not grants:
        return None
    if any(g.mission_id is None for g in grants):
        return Scope(None)
    return Scope(frozenset(g.mission_id for g in grants if g.mission_id is not None))


def _sees(scope: Scope | None, mission_id: uuid.UUID) -> bool:
    return scope is not None and (scope.missions is None or mission_id in scope.missions)


async def visible(session: AsyncSession, user: CurrentUser) -> bool:
    """GET /api/vip/access, for the screen and its nav entry: the HQ protection roles always;
    a Head of Mission only while one of their missions has a visit (so the Cairo Head of
    Mission sees no entry, §62)."""
    scope = await reader_scope(session, user)
    if scope is None or scope.missions is None:
        return scope is not None
    found = await session.scalar(
        select(VipVisit.id).where(VipVisit.mission_id.in_(scope.missions)).limit(1)
    )
    return found is not None


async def _visible(session: AsyncSession, user: CurrentUser, visit_id: uuid.UUID) -> VipVisit:
    """The visit, or 404 alike for a missing visit and one the caller may not see."""
    visit = await session.get(VipVisit, visit_id)
    if visit is None or not _sees(await reader_scope(session, user), visit.mission_id):
        raise VipError(404, NOT_FOUND)
    return visit


async def _visit_of_segment(
    session: AsyncSession, user: CurrentUser, segment_id: uuid.UUID
) -> VipVisit:
    visit_id = await session.scalar(select(VipSegment.visit_id).where(VipSegment.id == segment_id))
    if visit_id is None:
        raise VipError(404, NOT_FOUND)
    return await _visible(session, user, visit_id)


async def _require(
    session: AsyncSession, user: CurrentUser, roles: str, visit: VipVisit, what: str
) -> None:
    if not await approvals.user_has_role(session, user, roles, visit.mission_id):
        raise VipError(403, f"{what} needs {roles.replace('|', ' or ')} for this mission")


async def _lock(session: AsyncSession, visit_id: uuid.UUID) -> VipVisit:
    """Every write locks the visit first, then its segment, then a change: one order, so two
    writers never wait on each other in a circle."""
    visit = await session.scalar(
        select(VipVisit)
        .where(VipVisit.id == visit_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if visit is None:
        raise VipError(404, NOT_FOUND)
    return visit


async def _lock_segment(session: AsyncSession, segment_id: uuid.UUID) -> VipSegment:
    segment = await session.scalar(
        select(VipSegment)
        .where(VipSegment.id == segment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if segment is None:
        raise VipError(404, NOT_FOUND)
    return segment


# --- segment risk (VIP-02, §3) ------------------------------------------------------------------

# One row per segment, with every ACTIVE incident whose zone edge is within MODERATE_M of the
# venue: its distance to the centre (for the reason) and to the edge (for the level).
_SEGMENTS = text(
    """
    SELECT s.id, s.seq, s.kind, s.title, s.venue_name, s.starts_at, s.ends_at, s.attendees,
           s.virtual, s.status,
           coalesce((
             SELECT jsonb_agg(jsonb_build_object(
                      'id', i.id, 'reference', i.reference, 'category', i.category,
                      'centre_m', round(ST_Distance(s.venue_location, i.location)),
                      'edge_m', round(greatest(0, ST_Distance(s.venue_location, i.location)
                                                  - i.impact_radius_m)))
                    ORDER BY ST_Distance(s.venue_location, i.location) - i.impact_radius_m,
                             i.reference)
               FROM incident i
              WHERE i.status = 'ACTIVE' AND i.location IS NOT NULL
                AND ST_DWithin(s.venue_location, i.location, i.impact_radius_m + :moderate_m)
           ), '[]'::jsonb) AS incidents
      FROM vip_segment s
     WHERE s.visit_id = :visit_id
     ORDER BY s.seq
    """
)


def _max(levels: list[str]) -> str:
    return max(levels, key=LEVELS.index, default="LOW")


def segment_risk(row: Any, severe_weather: bool) -> tuple[str, list[schemas.ReasonOut]]:
    """The segment's risk and every reason for it, highest first (§3)."""
    if row.virtual:
        return "LOW", []  # no venue, no venue risk (G-5)
    reasons: list[schemas.ReasonOut] = []
    for i in row.incidents:
        label = CATEGORY_LABELS.get(i["category"], i["category"].replace("_", " ")).lower()
        reasons.append(
            schemas.ReasonOut(
                level="HIGH" if i["edge_m"] <= HIGH_M else "MODERATE",
                text=f"{label} {i['centre_m'] / 1000:.1f} km away · {i['reference']}",
                incident_id=uuid.UUID(i["id"]),
                incident_reference=i["reference"],
            )
        )
    if severe_weather:
        reasons.append(schemas.ReasonOut(level="MODERATE", text="severe weather"))
    if row.attendees is not None and row.attendees >= CROWD:
        reasons.append(schemas.ReasonOut(level="MODERATE", text=f"{row.attendees} attendees"))
    if row.kind == "MOTORCADE":
        reasons.append(schemas.ReasonOut(level="MODERATE", text="exposed movement"))
    reasons.sort(key=lambda r: -LEVELS.index(r.level))  # stable: incidents first within a level
    return _max([r.level for r in reasons]), reasons


# --- reading a visit ----------------------------------------------------------------------------


async def _changes(session: AsyncSession, visit: VipVisit) -> list[schemas.ChangeOut]:
    proposer, decider = aliased(AppUser), aliased(AppUser)
    rows = await session.execute(
        select(VipSegmentChange, proposer.display_name, decider.display_name)
        .join(VipSegment, VipSegment.id == VipSegmentChange.segment_id)
        .join(proposer, proposer.id == VipSegmentChange.proposed_by)
        .outerjoin(decider, decider.id == VipSegmentChange.decided_by)
        .where(VipSegment.visit_id == visit.id)
        .order_by(VipSegmentChange.proposed_at.desc(), VipSegmentChange.id)
    )
    closed = visit.status in FINAL
    return [
        schemas.ChangeOut(
            id=c.id,
            segment_id=c.segment_id,
            new_starts_at=c.new_starts_at,
            new_ends_at=c.new_ends_at,
            make_virtual=c.make_virtual,
            reason=c.reason,
            proposed_by_name=proposed_by,
            proposed_at=c.proposed_at,
            status="CLOSED" if closed and c.status == "PENDING" else c.status,  # L4
            decided_by_name=decided_by,
            decided_at=c.decided_at,
            decision_note=c.decision_note,
        )
        for c, proposed_by, decided_by in rows.all()
    ]


async def _segments(
    session: AsyncSession, visit: VipVisit, changes: list[schemas.ChangeOut]
) -> list[schemas.SegmentOut]:
    condition = await session.scalar(
        text("SELECT condition FROM weather_current WHERE mission_id = :m"),
        {"m": visit.mission_id},
    )
    severe = condition in SEVERE_WEATHER
    pending = {c.segment_id: c for c in changes if c.status == "PENDING"}
    out = []
    for row in await session.execute(_SEGMENTS, {"visit_id": visit.id, "moderate_m": MODERATE_M}):
        risk, reasons = segment_risk(row, severe)
        out.append(
            schemas.SegmentOut(
                id=row.id,
                seq=row.seq,
                kind=row.kind,
                title=row.title,
                venue_name=row.venue_name,
                starts_at=row.starts_at,
                ends_at=row.ends_at,
                attendees=row.attendees,
                virtual=row.virtual,
                status=row.status,
                risk=risk,
                reasons=reasons,
                recommendation=(
                    RECOMMENDATION if risk == "HIGH" and row.status == "PLANNED" else None
                ),
                pending_change=pending.get(row.id),
            )
        )
    return out


def _visit_risk(segments: list[schemas.SegmentOut], country: str | None) -> str:
    """The highest open segment's, or the country's if higher (§3)."""
    levels = [s.risk for s in segments if s.status != "COMPLETED"]
    return _max(levels + ([country] if country else []))


_FACILITY = text(
    """
    SELECT f.name, ST_Distance(f.location, m.location)::int AS distance_m
      FROM medical_facility f JOIN mission m ON m.id = f.mission_id
     WHERE f.mission_id = :mission_id
       AND NOT EXISTS (SELECT 1 FROM incident i
                        WHERE i.status = 'ACTIVE' AND i.location IS NOT NULL
                          AND ST_DWithin(f.location, i.location, i.impact_radius_m))
     ORDER BY distance_m, f.name
     LIMIT 1
    """
)  # the nearest not marked Avoid, as health_intel's facility list (HL-04)

_PARTNER = text(
    "SELECT name FROM partner WHERE is_active AND 'MEDICAL' = ANY(services) "
    "AND :country = ANY(coverage) ORDER BY sla_minutes, name LIMIT 1"
)


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


async def _detail(
    session: AsyncSession, user: CurrentUser, visit: VipVisit, mission: Mission
) -> schemas.DetailOut:
    detail = visit.detail
    codes = [c for c in detail.get("vehicles", []) if isinstance(c, str)]
    assets = {a.code: a for a in await fleet.list_assets(session, user, visit.mission_id)}
    vehicles = [
        schemas.VehicleOut(
            code=code,
            type_label=assets[code].type_label,
            armoured=assets[code].armoured,
            state=assets[code].state.code,
            available=assets[code].available,
        )
        if code in assets
        else schemas.VehicleOut(
            code=code, type_label=None, armoured=False, state="UNKNOWN", available=False
        )
        for code in codes
    ]
    facility = (await session.execute(_FACILITY, {"mission_id": visit.mission_id})).first()
    partner = await session.scalar(_PARTNER, {"country": mission.country_code})
    havens = [h for h in detail.get("safe_havens", []) if isinstance(h, str)]
    if facility is not None:
        havens.append(facility.name)  # the hospital, filled in at read time (§4)
    size = detail.get("team_size")
    return schemas.DetailOut(
        team_lead=_text(detail.get("team_lead")),
        advance_team=_text(detail.get("advance_team")),
        team_size=size if isinstance(size, int) else None,
        medic=detail.get("medic") is True,
        vehicles=vehicles,
        medical=schemas.MedicalOut(
            facility_name=facility.name if facility else None,
            facility_distance_m=facility.distance_m if facility else None,
            partner_name=partner,
        ),
        safe_havens=havens,
    )


async def _checklist(
    session: AsyncSession, visit: VipVisit, today: date
) -> list[schemas.ChecklistItemOut]:
    rows = await session.execute(
        select(VipChecklistItem, AppUser.display_name)
        .outerjoin(AppUser, AppUser.id == VipChecklistItem.done_by)
        .where(VipChecklistItem.visit_id == visit.id)
        .order_by(VipChecklistItem.due_on, VipChecklistItem.created_at, VipChecklistItem.label)
    )
    return [
        schemas.ChecklistItemOut(
            id=item.id,
            label=item.label,
            due_on=item.due_on,
            done=item.done_by is not None,
            done_at=item.done_at,
            done_by_name=name,
            overdue=item.done_by is None and item.due_on < today,
        )
        for item, name in rows.all()
    ]


def _kpis(
    segments: list[schemas.SegmentOut],
    detail: schemas.DetailOut,
    checklist: list[schemas.ChecklistItemOut],
) -> schemas.KpisOut:
    """G-2: the venues of segments that are not virtual, and how many have no open "<venue>
    venue survey" item (the design's 4 / 5)."""
    venues = {s.venue_name for s in segments if not s.virtual}
    open_surveys = [
        c.label.lower() for c in checklist if not c.done and c.label.lower().endswith(SURVEY)
    ]
    unsurveyed = {v for v in venues if any(label.startswith(v.lower()) for label in open_surveys)}
    return schemas.KpisOut(
        segments=len(segments),
        high=sum(1 for s in segments if s.risk == "HIGH"),
        team_size=detail.team_size,
        vehicles=len(detail.vehicles),
        medics=1 if detail.medic else 0,
        venues=len(venues),
        venues_surveyed=len(venues) - len(unsurveyed),
    )


async def _country_risk(session: AsyncSession, country: str) -> str | None:
    level: str | None = await session.scalar(
        text("SELECT level FROM country_risk WHERE country_code = :c"), {"c": country}
    )
    return level


async def _summary_risk(session: AsyncSession, visit: VipVisit, mission: Mission) -> str:
    segments = await _segments(session, visit, [])
    return _visit_risk(segments, await _country_risk(session, mission.country_code))


async def list_visits(session: AsyncSession, user: CurrentUser) -> list[schemas.VisitSummaryOut]:
    scope = await reader_scope(session, user)
    if scope is None:
        return []
    rows = await session.execute(
        select(VipVisit, Mission)
        .join(Mission, Mission.id == VipVisit.mission_id)
        .order_by(VipVisit.starts_on, VipVisit.reference)
    )
    return [
        schemas.VisitSummaryOut(
            id=visit.id,
            reference=visit.reference,
            title=visit.title,
            mission_id=visit.mission_id,
            mission_code=mission.code,
            starts_on=visit.starts_on,
            ends_on=visit.ends_on,
            status=visit.status,
            risk=await _summary_risk(session, visit, mission),
        )
        for visit, mission in rows.all()
        if _sees(scope, visit.mission_id)
    ]


async def visit_out(
    session: AsyncSession, user: CurrentUser, visit_id: uuid.UUID, today: date
) -> schemas.VisitOut:
    visit = await _visible(session, user, visit_id)
    await session.refresh(visit)  # the database writes the times
    mission = await session.get_one(Mission, visit.mission_id)
    trip_reference = (
        await session.scalar(text("SELECT reference FROM trip WHERE id = :t"), {"t": visit.trip_id})
        if visit.trip_id
        else None
    )
    changes = await _changes(session, visit)
    segments = await _segments(session, visit, changes)
    country = await _country_risk(session, mission.country_code)
    detail = await _detail(session, user, visit, mission)
    checklist = await _checklist(session, visit, today)
    return schemas.VisitOut(
        id=visit.id,
        reference=visit.reference,
        title=visit.title,
        mission_id=visit.mission_id,
        mission_code=mission.code,
        starts_on=visit.starts_on,
        ends_on=visit.ends_on,
        status=visit.status,
        risk=_visit_risk(segments, country),
        principal_role=visit.principal_role,
        trip_id=visit.trip_id,
        trip_reference=trip_reference,
        country_risk=country,
        started_at=visit.started_at,
        cancelled_at=visit.cancelled_at,
        cancel_reason=visit.cancel_reason,
        segments=segments,
        changes=changes,
        detail=detail,
        checklist=checklist,
        kpis=_kpis(segments, detail, checklist),
        source=visit.source,
    )


# --- during the visit (VIP-04, §5) --------------------------------------------------------------


async def start(session: AsyncSession, user: CurrentUser, visit_id: uuid.UUID) -> VipVisit:
    found = await _visible(session, user, visit_id)
    await _require(session, user, ACTORS, found, "Starting a visit")  # before the lock
    visit = await _lock(session, visit_id)
    if visit.status != "PLANNED":
        raise VipError(409, f"{visit.reference} is {visit.status.lower()}, not planned")
    visit.status = "LIVE"
    visit.started_by = user.id
    await session.flush()
    await _audit(session, _user(user), "START", visit, {"from": "PLANNED", "to": "LIVE"})
    return visit


async def cancel(
    session: AsyncSession, user: CurrentUser, visit_id: uuid.UUID, reason: str
) -> VipVisit:
    found = await _visible(session, user, visit_id)
    await _require(session, user, CANCELLER, found, "Cancelling a visit")
    visit = await _lock(session, visit_id)
    if visit.status in FINAL:
        raise VipError(409, f"{visit.reference} is already {visit.status.lower()}")
    before = visit.status
    visit.status = "CANCELLED"
    visit.cancelled_by = user.id
    visit.cancel_reason = reason
    await session.flush()
    pending = await _pending_count(session, visit)
    await _audit(
        session,
        _user(user),
        "CANCEL",
        visit,
        {"from": before, "to": "CANCELLED", "pending_changes_closed": pending},
    )
    return visit


async def _pending_count(session: AsyncSession, visit: VipVisit) -> int:
    count = await session.scalar(
        text(
            "SELECT count(*) FROM vip_segment_change c JOIN vip_segment s ON s.id = c.segment_id "
            "WHERE s.visit_id = :v AND c.status = 'PENDING'"
        ),
        {"v": visit.id},
    )
    return int(count or 0)


async def _advance(
    session: AsyncSession, actor: Actor, visit: VipVisit, segment: VipSegment, to: str
) -> None:
    """One step forward while the visit is LIVE; the departure completed completes the visit
    (plan §5; review of Prompt 78, L6)."""
    if visit.status != "LIVE":
        raise VipError(409, f"{visit.reference} is {visit.status.lower()}, not live")
    if NEXT.get(segment.status) != to:
        raise VipError(409, f"Segment {segment.seq} is {segment.status.lower().replace('_', ' ')}")
    before = segment.status
    segment.status = to
    await session.flush()
    await _audit(session, actor, "SEGMENT", visit, {"seq": segment.seq, "from": before, "to": to})
    if segment.kind == "DEPARTURE" and to == "COMPLETED":
        visit.status = "COMPLETED"
        await session.flush()
        pending = await _pending_count(session, visit)
        await _audit(
            session,
            actor,
            "COMPLETE",
            visit,
            {"from": "LIVE", "to": "COMPLETED", "pending_changes_closed": pending},
        )


async def progress(session: AsyncSession, user: CurrentUser, segment_id: uuid.UUID) -> VipVisit:
    found = await _visit_of_segment(session, user, segment_id)
    await _require(session, user, ACTORS, found, "Moving the programme")
    visit = await _lock(session, found.id)
    segment = await _lock_segment(session, segment_id)
    if segment.status not in NEXT:
        raise VipError(409, f"Segment {segment.seq} is already completed")
    await _advance(session, _user(user), visit, segment, NEXT[segment.status])
    return visit


async def simulated_progress(
    session: AsyncSession, reference: str, seq: int, status: str
) -> VipVisit | None:
    """The worker's VIP_PROGRESS event (plan §5, §9): the same step as a person's, as the
    SYSTEM actor. None if there is no such visit or segment, or the step does not apply."""
    visit_id = await session.scalar(select(VipVisit.id).where(VipVisit.reference == reference))
    if visit_id is None:
        return None
    visit = await _lock(session, visit_id)
    segment_id = await session.scalar(
        select(VipSegment.id).where(VipSegment.visit_id == visit.id, VipSegment.seq == seq)
    )
    if segment_id is None:
        return None
    segment = await _lock_segment(session, segment_id)
    if visit.status != "LIVE" or NEXT.get(segment.status) != status:
        return None
    await _advance(session, PROGRESS, visit, segment, status)
    return visit


# --- the checklist (VIP-03, §4) -----------------------------------------------------------------


async def tick(session: AsyncSession, user: CurrentUser, item_id: uuid.UUID) -> VipVisit:
    visit_id = await session.scalar(
        select(VipChecklistItem.visit_id).where(VipChecklistItem.id == item_id)
    )
    if visit_id is None:
        raise VipError(404, NOT_FOUND)
    found = await _visible(session, user, visit_id)
    await _require(session, user, ACTORS, found, "Ticking the checklist")
    visit = await _lock(session, visit_id)
    item = await session.scalar(
        select(VipChecklistItem)
        .where(VipChecklistItem.id == item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if item is None:
        raise VipError(404, NOT_FOUND)
    if visit.status in FINAL:
        raise VipError(409, f"{visit.reference} is {visit.status.lower()}")
    if item.done_by is not None:
        raise VipError(409, "The item is already done")
    item.done_by = user.id  # by the caller, never on someone's behalf
    await session.flush()
    await _audit(session, _user(user), "CHECKLIST_DONE", visit, {"item": str(item.id)})
    return visit


# --- programme changes with two people (VIP-05, §6) ---------------------------------------------


async def propose(
    session: AsyncSession, user: CurrentUser, segment_id: uuid.UUID, body: schemas.ChangeIn
) -> VipVisit:
    found = await _visit_of_segment(session, user, segment_id)
    await _require(session, user, PROPOSER, found, "Proposing a programme change")
    if body.make_virtual == (body.new_starts_at is not None):
        raise VipError(422, "A change is either a new start time or a virtual alternative")
    if body.make_virtual and body.new_ends_at is not None:
        raise VipError(422, "A virtual alternative keeps the time")
    for at in (body.new_starts_at, body.new_ends_at):
        if at is not None and at.tzinfo is None:
            raise VipError(422, "Times need a time zone")
    visit = await _lock(session, found.id)
    segment = await _lock_segment(session, segment_id)
    if visit.status in FINAL:
        raise VipError(409, f"{visit.reference} is {visit.status.lower()}")
    if segment.status != "PLANNED":
        raise VipError(409, f"Segment {segment.seq} is under way; only a planned segment changes")
    if body.make_virtual and segment.virtual:
        raise VipError(409, f"Segment {segment.seq} is already virtual")
    pending = await session.scalar(
        select(VipSegmentChange.id).where(
            VipSegmentChange.segment_id == segment.id, VipSegmentChange.status == "PENDING"
        )
    )
    if pending is not None:
        raise VipError(409, f"Segment {segment.seq} already has a change waiting for a decision")
    new_ends_at = body.new_ends_at
    if body.new_starts_at is not None and new_ends_at is None and segment.ends_at is not None:
        # Keep the duration (review of Prompt 78, L5).
        new_ends_at = body.new_starts_at + (segment.ends_at - segment.starts_at)
    if body.new_starts_at is not None:
        if new_ends_at is not None and new_ends_at <= body.new_starts_at:
            raise VipError(422, "The end is after the start")
        if (body.new_starts_at, new_ends_at) == (segment.starts_at, segment.ends_at):
            raise VipError(409, f"Segment {segment.seq} is already at that time")
    change = VipSegmentChange(
        tenant_id=visit.tenant_id,
        segment_id=segment.id,
        new_starts_at=body.new_starts_at,
        new_ends_at=new_ends_at if body.new_starts_at is not None else None,
        make_virtual=body.make_virtual,
        reason=body.reason,
        proposed_by=user.id,
    )
    session.add(change)
    await session.flush()
    await _audit(
        session,
        _user(user),
        "CHANGE_PROPOSE",
        visit,
        {
            "seq": segment.seq,
            "change": str(change.id),
            "kind": "virtual" if body.make_virtual else "time",
        },
    )
    return visit


@dataclass(frozen=True)
class _Change:
    visit: VipVisit
    segment: VipSegment
    change: VipSegmentChange


async def _gate(session: AsyncSession, visit: VipVisit, change: VipSegmentChange) -> approvals.Gate:
    seq = await session.scalar(select(VipSegment.seq).where(VipSegment.id == change.segment_id))
    return approvals.Gate(
        subject=f"The change to {visit.reference} segment {seq}",
        required_role=DECIDERS,
        mission_id=visit.mission_id,
        decided=change.status != "PENDING",
        open=visit.status not in FINAL,  # a pending change of a final visit is closed (L4)
        deciders_of_other_steps=frozenset({change.proposed_by}),
    )


async def _locked_change(session: AsyncSession, user: CurrentUser, change_id: uuid.UUID) -> _Change:
    segment_id = await session.scalar(
        select(VipSegmentChange.segment_id).where(VipSegmentChange.id == change_id)
    )
    if segment_id is None:
        raise VipError(404, NOT_FOUND)
    found = await _visit_of_segment(session, user, segment_id)
    visit = await _lock(session, found.id)
    segment = await _lock_segment(session, segment_id)
    change = await session.scalar(
        select(VipSegmentChange)
        .where(VipSegmentChange.id == change_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if change is None:
        raise VipError(404, NOT_FOUND)
    return _Change(visit, segment, change)


async def decide(
    session: AsyncSession,
    user: CurrentUser,
    change_id: uuid.UUID,
    approve: bool,
    note: str | None,
) -> VipVisit:
    """Approve or reject, through approvals.decide() with the rows locked (D-05, D-16). On
    approval the segment changes in the same transaction, as the PC-36 guard requires."""
    locked = await _locked_change(session, user, change_id)
    visit, segment, change = locked.visit, locked.segment, locked.change
    try:
        await approvals.decide(session, user, await _gate(session, visit, change))
    except approvals.ApprovalDeniedError as e:
        raise VipError(e.verdict.status_code, e.verdict.reason) from None
    if approve and segment.status != "PLANNED":
        raise VipError(409, f"Segment {segment.seq} is under way; the change can only be rejected")
    change.status = "APPROVED" if approve else "REJECTED"
    change.decided_by = user.id
    change.decision_note = note
    await session.flush()
    if approve:
        if change.make_virtual:
            segment.virtual = True
        elif change.new_starts_at is not None:  # the PC-38 check: a time or virtual
            segment.starts_at = change.new_starts_at
            segment.ends_at = change.new_ends_at
        await session.flush()
    await _audit(
        session,
        _user(user),
        "CHANGE_APPROVE" if approve else "CHANGE_REJECT",
        visit,
        {"seq": segment.seq, "change": str(change.id)},
    )
    return visit


# --- the buttons (GET /api/me/permissions?entity_type=vip_visit) --------------------------------


@dataclass(frozen=True)
class Permissions:
    start: bool = False
    progress: bool = False
    cancel: bool = False
    tick: bool = False
    propose: tuple[uuid.UUID, ...] = ()  # segments the caller may propose a change for
    decide: tuple[uuid.UUID, ...] = ()  # changes the caller may decide now


async def permissions(session: AsyncSession, user: CurrentUser, visit_id: uuid.UUID) -> Permissions:
    """The endpoints' own checks. Nothing at all for a caller who may not see the visit."""
    try:
        visit = await _visible(session, user, visit_id)
    except VipError:
        return Permissions()
    if visit.status in FINAL:
        return Permissions()
    acts = await approvals.user_has_role(session, user, ACTORS, visit.mission_id)
    proposes = await approvals.user_has_role(session, user, PROPOSER, visit.mission_id)
    segments = list(
        await session.scalars(select(VipSegment).where(VipSegment.visit_id == visit.id))
    )
    changes = list(
        await session.scalars(
            select(VipSegmentChange).where(
                VipSegmentChange.segment_id.in_([s.id for s in segments]),
                VipSegmentChange.status == "PENDING",
            )
        )
    )
    waiting = {c.segment_id for c in changes}
    decidable = []
    for change in changes:
        verdict = await approvals.can_decide(session, user, await _gate(session, visit, change))
        if verdict.allowed:
            decidable.append(change.id)
    return Permissions(
        start=acts and visit.status == "PLANNED",
        progress=acts and visit.status == "LIVE",
        cancel=await approvals.user_has_role(session, user, CANCELLER, visit.mission_id),
        tick=acts,
        propose=tuple(
            s.id
            for s in sorted(segments, key=lambda s: s.seq)
            if proposes and s.status == "PLANNED" and s.id not in waiting
        ),
        decide=tuple(decidable),
    )
