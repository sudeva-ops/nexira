"""Document Expiry (pilot module 7; DX-01..07, DX-09; D-37, docs/plan-pilot-dx.md).

- The register: every active staff member's and dependant's documents, with days left
  (UTC date), urgency (§3), whether the holder is travel-ready and whether the document
  could block an evacuation. Read by DUTY_OFFICER, SECURITY_OFFICER, CONSULAR_OFFICER,
  HQ_CRISIS_DIRECTOR, TRAVEL_DESK and ADMIN, and by HEAD_OF_MISSION, each within the
  mission scope of their role (D-05, §2). Everyone else gets the summary only (DX-09).
- Renewal steps and reminders: CONSULAR_OFFICER, DUTY_OFFICER or HEAD_OF_MISSION for the
  holder's mission, checked through app/core/approvals.py; or the Compliance agent's
  START_DOCUMENT_RENEWAL once a person approved it (§4). The database enforces the
  forward-only renewal and writes the times (migration 0007); this module gives clear
  messages first.
- Reminders are one ADVISORY campaign (APP and EMAIL, simulated) to the documents'
  holders through the notification service (§5): staff only, never citizens.

Every change is audited (DOCUMENT.*) and announced after commit as DOCUMENT_UPDATED.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.approvals import parse_role_codes, roles_of, user_has_role
from app.core.events import Event
from app.core.security import CurrentUser
from app.modules.documents.models import TravelDocument
from app.modules.notifications.models import NotificationCampaign
from app.modules.notifications.service import (
    AudienceError,
    CampaignIn,
    campaign_queued_event,
    create_campaign,
)
from app.modules.people.models import Mission, Person
from app.modules.tenancy.service import SYSTEM, Actor

READERS = (
    "DUTY_OFFICER|SECURITY_OFFICER|CONSULAR_OFFICER|HQ_CRISIS_DIRECTOR|TRAVEL_DESK|ADMIN|"
    "HEAD_OF_MISSION"
)
RENEWERS = "CONSULAR_OFFICER|DUTY_OFFICER|HEAD_OF_MISSION"  # §38 Q2, scoped to the mission
HOLDER_TYPES = ("DIPLOMAT", "LOCAL_STAFF", "DEPENDANT", "CONTRACTOR")
PASSPORTS = ("PASSPORT", "DIPLOMATIC_PASSPORT")
READY_DAYS = 180  # the six-month rule (§38 Q3)
AT_RISK = ("HIGH", "CRITICAL")
URGENCIES = ("EXPIRED", "CRITICAL", "HIGH", "MODERATE", "OK")  # most urgent first
STEPS = ("REQUESTED", "IN_PROGRESS", "RENEWED")
IN_RENEWAL = ("REQUESTED", "IN_PROGRESS")
_FROM = {"REQUESTED": ("NONE",), "IN_PROGRESS": ("NONE", "REQUESTED"), "RENEWED": ("IN_PROGRESS",)}
_WHO = {
    "REQUESTED": "renewal_requested_by",
    "IN_PROGRESS": "renewal_started_by",
    "RENEWED": "renewed_by",
}
ACTIONS = {  # audit action per step (plan §7)
    "REQUESTED": "DOCUMENT.RENEWAL_REQUESTED",
    "IN_PROGRESS": "DOCUMENT.RENEWAL_STARTED",
    "RENEWED": "DOCUMENT.RENEWED",
}
LATEST = date(2200, 12, 31)  # as the table's CHECK
REMINDER = "Your travel document expires soon. Please start the renewal with the consular section."
REMINDER_CHANNELS = ["APP", "EMAIL"]  # simulated (§5)
REMINDERS_MAX = 500
LIST_MAX = 1000


class DocumentError(Exception):
    """The request cannot be done: status_code 403, 404, 409 or 422."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def today_utc() -> date:
    return datetime.now(UTC).date()


def urgency(doc_type: str, days_left: int) -> str:
    """DX-02: 29 -> CRITICAL, 30 -> HIGH; 89 -> HIGH, 90 -> MODERATE (a passport) or OK;
    179 -> MODERATE, 180 -> OK."""
    if days_left < 0:
        return "EXPIRED"
    if days_left < 30:
        return "CRITICAL"
    if days_left < 90:
        return "HIGH"
    if doc_type in PASSPORTS and days_left < READY_DAYS:
        return "MODERATE"
    return "OK"


def ready_by(doc_type: str, valid_until: date, on: date) -> bool:
    """A passport-type document with at least 180 days left on `on` (DX-03)."""
    return doc_type in PASSPORTS and (valid_until - on).days >= READY_DAYS


# --- who sees what (DX-09, §2) -----------------------------------------------------------------


@dataclass(frozen=True)
class Scope:
    """The missions a role applies to: None for all (an unscoped grant, D-05)."""

    missions: frozenset[uuid.UUID] | None

    def covers(self, mission_id: uuid.UUID | None) -> bool:
        # As approvals.user_has_role: a person without a mission is for unscoped holders.
        if self.missions is None:
            return True
        return mission_id is not None and mission_id in self.missions


async def _scope(session: AsyncSession, user: CurrentUser, role_codes: str) -> Scope | None:
    """The union of the user's grants of these roles (plan G-7); None if they hold none."""
    codes = parse_role_codes(role_codes)
    grants = [g for g in await roles_of(session, user.id) if g.code in codes]
    if not grants:
        return None
    if any(g.mission_id is None for g in grants):
        return Scope(None)
    return Scope(frozenset(g.mission_id for g in grants if g.mission_id is not None))


async def read_scope(session: AsyncSession, user: CurrentUser) -> Scope | None:
    return await _scope(session, user, READERS)


async def act_scope(session: AsyncSession, user: CurrentUser) -> Scope | None:
    return await _scope(session, user, RENEWERS)


# --- the register (DX-01..03) ------------------------------------------------------------------

_MISSION_RISK = text(
    """
    WITH worst AS (
      SELECT DISTINCT ON (mission_id) mission_id, severity
        FROM incident
       WHERE status = 'ACTIVE' AND mission_id IS NOT NULL
       ORDER BY mission_id, severity_rank(severity) DESC
    )
    SELECT m.id, m.code,
           CASE WHEN severity_rank(w.severity) > severity_rank(m.risk_level)
                THEN w.severity ELSE m.risk_level END AS display_risk,
           w.mission_id IS NOT NULL AS active_incident
      FROM mission m LEFT JOIN worst w ON w.mission_id = m.id
    """
)


@dataclass(frozen=True)
class MissionRisk:
    code: str
    display_risk: str  # as the missions list (D-08)
    active_incident: bool

    @property
    def at_risk(self) -> bool:
        return self.display_risk in AT_RISK or self.active_incident


async def mission_risks(session: AsyncSession) -> dict[uuid.UUID, MissionRisk]:
    return {
        r.id: MissionRisk(r.code, r.display_risk, r.active_incident)
        for r in await session.execute(_MISSION_RISK)
    }


@dataclass(frozen=True)
class Row:
    document: TravelDocument
    holder_name: str
    holder_type: str
    mission_id: uuid.UUID | None
    mission_code: str | None
    days_left: int
    urgency: str
    holder_ready: bool  # the holder is travel-ready (DX-03)
    could_block: bool  # "Could block evacuation" (DX-03, G-4)


def _sort_key(row: Row) -> tuple[int, int, str, str]:
    return (URGENCIES.index(row.urgency), row.days_left, row.holder_name, row.document.doc_type)


async def register(
    session: AsyncSession, today: date, mission_id: uuid.UUID | None = None
) -> list[Row]:
    """The documents of active holders, most urgent first; one mission's if given."""
    query = (
        select(TravelDocument, Person.full_name, Person.person_type, Person.mission_id)
        .join(Person, Person.id == TravelDocument.person_id)
        .where(Person.is_active)
    )
    if mission_id is not None:
        query = query.where(Person.mission_id == mission_id)
    found = (await session.execute(query)).all()
    ready = {doc.person_id for doc, *_ in found if ready_by(doc.doc_type, doc.valid_until, today)}
    risks = await mission_risks(session)
    rows = []
    for doc, name, person_type, holder_mission in found:
        days = (doc.valid_until - today).days
        risk = risks.get(holder_mission) if holder_mission else None
        holder_ready = doc.person_id in ready
        rows.append(
            Row(
                document=doc,
                holder_name=name,
                holder_type=person_type,
                mission_id=holder_mission,
                mission_code=risk.code if risk else None,
                days_left=days,
                urgency=urgency(doc.doc_type, days),
                holder_ready=holder_ready,
                # A renewal in progress does not count: only a renewed date does (§3).
                could_block=doc.doc_type in PASSPORTS
                and not holder_ready
                and risk is not None
                and risk.at_risk,
            )
        )
    return sorted(rows, key=_sort_key)


@dataclass(frozen=True)
class Filters:
    mission_id: uuid.UUID | None = None
    doc_type: str | None = None
    urgency: str | None = None
    limit: int = 200


@dataclass(frozen=True)
class Listing:
    rows: list[Row]
    act: Scope | None  # where the caller may renew and remind


async def list_documents(
    session: AsyncSession, user: CurrentUser, filters: Filters, today: date | None = None
) -> Listing:
    scope = await read_scope(session, user)
    if scope is None:
        raise DocumentError(403, "The document list needs a role that reads documents (DX-09)")
    rows = [
        r
        for r in await register(session, today or today_utc(), filters.mission_id)
        if scope.covers(r.mission_id)
        and (filters.doc_type is None or r.document.doc_type == filters.doc_type)
        and (filters.urgency is None or r.urgency == filters.urgency)
    ]
    return Listing(rows[: filters.limit], await act_scope(session, user))


@dataclass(frozen=True)
class MissionReadiness:
    mission_id: uuid.UUID
    code: str
    people: int
    ready: int


@dataclass(frozen=True)
class Summary:
    tracked: int
    expiring_30: int
    expiring_90: int
    in_renewal_90: int  # of those expiring within 90 days
    could_block: int
    people: int
    ready: int
    missions: list[MissionReadiness] = field(default_factory=list)


async def summary(session: AsyncSession, user: CurrentUser, today: date | None = None) -> Summary:
    """DX-08 KPIs, no names. A reader's within their scope (a Head of Mission's covers
    their mission); everyone else's covers every mission (DX-09)."""
    scope = await read_scope(session, user) or Scope(None)
    on = today or today_utc()
    rows = [r for r in await register(session, on) if scope.covers(r.mission_id)]
    people = (
        await session.execute(
            select(Person.id, Person.mission_id).where(
                Person.is_active, Person.person_type.in_(HOLDER_TYPES)
            )
        )
    ).all()
    ready = {r.document.person_id for r in rows if r.holder_ready}
    codes = {m.id: m.code for m in await session.scalars(select(Mission))}
    by_mission: dict[uuid.UUID, list[uuid.UUID]] = {}
    for person_id, mission_id in people:
        if mission_id is not None and scope.covers(mission_id):
            by_mission.setdefault(mission_id, []).append(person_id)
    counted = [p for p, m in people if scope.covers(m)]
    soon = [r for r in rows if r.days_left < 90]
    return Summary(
        tracked=len(rows),
        expiring_30=sum(1 for r in rows if r.days_left < 30),
        expiring_90=len(soon),
        in_renewal_90=sum(1 for r in soon if r.document.renewal_status in IN_RENEWAL),
        could_block=sum(1 for r in rows if r.could_block),
        people=len(counted),
        ready=sum(1 for p in counted if p in ready),
        missions=sorted(
            (
                MissionReadiness(m, codes[m], len(ids), sum(1 for p in ids if p in ready))
                for m, ids in by_mission.items()
            ),
            key=lambda m: m.code,
        ),
    )


async def at_risk(session: AsyncSession, mission_id: uuid.UUID, today: date) -> list[Row]:
    """The mission's documents that could block an evacuation (the Compliance agent)."""
    return [r for r in await register(session, today, mission_id) if r.could_block]


# --- renewal steps (DX-04) ---------------------------------------------------------------------


def document_event(document: TravelDocument, mission_id: uuid.UUID | None) -> Event:
    return Event(
        type="DOCUMENT_UPDATED",
        tenant_id=document.tenant_id,
        payload={
            "document_id": str(document.id),
            "mission_id": str(mission_id) if mission_id else None,
            "renewal_status": document.renewal_status,
        },
        source="documents",
    )


@dataclass
class Outcome:
    document: TravelDocument
    mission_id: uuid.UUID | None  # the holder's
    events: list[Event]


def _refusal(status: str, step: str) -> str:
    if status == "RENEWED":
        return "This document is already renewed"
    if step == "RENEWED":
        return "Start the renewal before marking the document renewed"
    if status == step:
        return f"This document's renewal is already {status.lower().replace('_', ' ')}"
    return "This document's renewal is already in progress"


async def _step(
    session: AsyncSession,
    document: TravelDocument,
    step: str,
    who: str,
    actor: Actor,
    valid_until: date | None = None,
    **details: Any,
) -> None:
    """One renewal step, with the same checks as the guard trigger (migration 0007)."""
    if document.renewal_status not in _FROM[step]:
        raise DocumentError(409, _refusal(document.renewal_status, step))
    old_date = document.valid_until
    if step == "RENEWED":
        if valid_until is None:
            raise DocumentError(422, "A renewed document needs its new valid-until date")
        if valid_until <= old_date:
            raise DocumentError(422, f"The new date must be later than {old_date.isoformat()}")
        if valid_until > LATEST:
            raise DocumentError(422, f"The new date must be on or before {LATEST.isoformat()}")
    elif valid_until is not None:
        raise DocumentError(422, "A new valid-until date is given only when renewed")
    before = document.renewal_status
    document.renewal_status = step
    setattr(document, _WHO[step], who)
    if valid_until is not None:
        document.valid_until = valid_until
    await session.flush()
    await session.refresh(document)  # the trigger writes the step's time
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action=ACTIONS[step],
        entity_type="travel_document",
        entity_id=str(document.id),
        details={
            "from": before,
            "to": step,
            "doc_type": document.doc_type,
            "person_id": str(document.person_id),
            **(
                {"valid_until": {"from": old_date.isoformat(), "to": valid_until.isoformat()}}
                if valid_until is not None
                else {}
            ),
            **details,
        },
    )


async def _locked(session: AsyncSession, document_id: uuid.UUID) -> TravelDocument:
    document = await session.scalar(
        select(TravelDocument).where(TravelDocument.id == document_id).with_for_update()
    )
    if document is None:
        raise DocumentError(404, "No such document")
    return document


async def _holder_mission(session: AsyncSession, document: TravelDocument) -> uuid.UUID | None:
    mission_id: uuid.UUID | None = await session.scalar(
        select(Person.mission_id).where(Person.id == document.person_id)
    )
    return mission_id


async def renew(
    session: AsyncSession,
    user: CurrentUser,
    document_id: uuid.UUID,
    step: str,
    valid_until: date | None = None,
) -> Outcome:
    """DX-04: a person moves a document's renewal one step on."""
    if step not in STEPS:
        raise DocumentError(422, f"step is one of {', '.join(STEPS)}")
    document = await _locked(session, document_id)
    mission_id = await _holder_mission(session, document)
    if not await user_has_role(session, user, RENEWERS, mission_id):
        raise DocumentError(
            403,
            "Renewing a document needs Consular Officer, Duty Officer, or Head of Mission "
            "for the holder's mission",
        )
    await _step(
        session, document, step, str(user.id), Actor(type="USER", id=str(user.id)), valid_until
    )
    return Outcome(document, mission_id, [document_event(document, mission_id)])


# --- reminders (DX-05, §5) ---------------------------------------------------------------------


@dataclass
class Reminders:
    campaign: NotificationCampaign
    recipients: int
    documents: int
    events: list[Event]


async def _remind(
    session: AsyncSession,
    document_ids: list[uuid.UUID],
    *,
    incident_id: uuid.UUID | None,
    created_by_type: str,
    created_by: str,
    actor: Actor,
) -> Reminders:
    ids = sorted(set(document_ids))
    try:
        # The same service as every campaign; the "document holders" audience refuses
        # citizens and delegates (§5).
        campaign, recipients = await create_campaign(
            session,
            incident_id=incident_id,
            campaign=CampaignIn(
                campaign_type="ADVISORY",
                message=REMINDER,
                channels=REMINDER_CHANNELS,
                audience={"document_ids": [str(i) for i in ids]},
            ),
            created_by_type=created_by_type,
            created_by=created_by,
            actor=actor,
        )
    except AudienceError as e:
        raise DocumentError(409, str(e)) from None
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="DOCUMENT.REMINDERS",
        entity_type="notification_campaign",
        entity_id=campaign.reference,
        details={
            "documents": len(ids),
            "recipients": recipients,
            "incident_id": str(incident_id) if incident_id else None,
        },
    )
    return Reminders(campaign, recipients, len(ids), [campaign_queued_event(campaign)])


async def send_reminders(
    session: AsyncSession, user: CurrentUser, document_ids: list[uuid.UUID]
) -> Reminders:
    """DX-05: one staff campaign to the holders. Staff only, so the author sends it
    without a second person (MN-05, §38 Q2)."""
    ids = set(document_ids)
    if not ids:
        raise DocumentError(422, "Name at least one document")
    if len(ids) > REMINDERS_MAX:
        raise DocumentError(422, f"At most {REMINDERS_MAX} documents at a time")
    found = dict(
        (
            await session.execute(
                select(TravelDocument.id, Person.mission_id)
                .join(Person, Person.id == TravelDocument.person_id)
                .where(TravelDocument.id.in_(ids))
            )
        ).all()
    )
    if set(found) != ids:
        raise DocumentError(404, "No such document")
    for mission_id in set(found.values()):
        if not await user_has_role(session, user, RENEWERS, mission_id):
            raise DocumentError(
                403,
                "Sending reminders needs Consular Officer, Duty Officer, or Head of Mission "
                "for every holder's mission",
            )
    return await _remind(
        session,
        list(ids),
        incident_id=None,
        created_by_type="USER",
        created_by=str(user.id),
        actor=Actor(type="USER", id=str(user.id)),
    )


# --- the Compliance agent's action (DX-07, §4) -------------------------------------------------


@dataclass
class AgentRenewal:
    requested: list[uuid.UUID]
    skipped: list[uuid.UUID]  # already in renewal (or renewed)
    reminders: Reminders
    events: list[Event]


async def renew_by_agent(
    session: AsyncSession,
    document_ids: list[uuid.UUID],
    *,
    incident_id: uuid.UUID,
    mission_id: uuid.UUID | None,
    actor: Actor,
    approved_by: uuid.UUID | None,
    proposal_id: uuid.UUID,
) -> AgentRenewal:
    """START_DOCUMENT_RENEWAL, once a person approved it: the step REQUESTED for each
    document still at NONE (the same step, row update and audit as a person's, with the
    approver recorded as who requested it), then one reminders campaign."""
    ids = sorted(set(document_ids))
    found = (
        await session.execute(
            select(TravelDocument, Person.mission_id)
            .join(Person, Person.id == TravelDocument.person_id)
            .where(TravelDocument.id.in_(ids))
            .order_by(TravelDocument.id)
            .with_for_update(of=TravelDocument)
        )
    ).all()
    if len(found) != len(ids):
        raise DocumentError(404, "A document in the proposal no longer exists")
    # The approver decided for the incident's mission (D-05): nothing elsewhere runs.
    if mission_id is None or any(m != mission_id for _, m in found):
        raise DocumentError(409, "Every document must be at the incident's mission")
    who = str(approved_by) if approved_by else f"agent:{actor.id}"
    requested, skipped, events = [], [], []
    for document, _ in found:
        if document.renewal_status != "NONE":
            skipped.append(document.id)
            continue
        await _step(
            session,
            document,
            "REQUESTED",
            who,
            actor,
            approved_by=str(approved_by) if approved_by else None,
            proposal_id=str(proposal_id),
        )
        requested.append(document.id)
        events.append(document_event(document, mission_id))
    reminders = await _remind(
        session,
        ids,
        incident_id=incident_id,
        created_by_type="AGENT",
        created_by=str(proposal_id),
        actor=actor,
    )
    return AgentRenewal(requested, skipped, reminders, events + reminders.events)


# --- trips (DX-06) -----------------------------------------------------------------------------


@dataclass(frozen=True)
class TripWarning:
    person_id: uuid.UUID
    full_name: str
    valid_until: date | None  # the latest passport-type date; None if they hold none


async def trip_warnings(
    session: AsyncSession, person_ids: list[uuid.UUID], ends_on: date
) -> list[TripWarning]:
    """Travellers with documents on record but no passport valid for 180 days after the
    trip ends. A warning only: it never blocks approval (§38 Q6)."""
    if not person_ids:
        return []
    rows = await session.execute(
        select(Person.id, Person.full_name, TravelDocument.doc_type, TravelDocument.valid_until)
        .join(TravelDocument, TravelDocument.person_id == Person.id)
        .where(Person.id.in_(person_ids))
    )
    names: dict[uuid.UUID, str] = {}
    best: dict[uuid.UUID, date | None] = {}
    for person_id, name, doc_type, valid_until in rows:
        names[person_id] = name
        current = best.get(person_id)
        if doc_type in PASSPORTS and (current is None or valid_until > current):
            best[person_id] = valid_until
        else:
            best.setdefault(person_id, None)
    needed = ends_on + timedelta(days=READY_DAYS)
    return sorted(
        (TripWarning(p, names[p], d) for p, d in best.items() if d is None or d < needed),
        key=lambda w: w.full_name,
    )


# --- the seed (§8) -----------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentIn:
    id: uuid.UUID
    person_id: uuid.UUID
    doc_type: str
    issuing_country: str
    valid_until: date


async def ensure_documents(
    session: AsyncSession, documents: list[DocumentIn], actor: Actor = SYSTEM, batch: int = 1000
) -> list[uuid.UUID]:
    """Insert documents whose id is new (plan G-8); return their ids. Audited once per load
    with the count, as the people (plan G-20)."""
    tenant_id = session.info["tenant_id"]
    created: list[uuid.UUID] = []
    for start in range(0, len(documents), batch):
        result = await session.scalars(
            insert(TravelDocument)
            .values(
                [
                    {
                        "id": d.id,
                        "tenant_id": tenant_id,
                        "person_id": d.person_id,
                        "doc_type": d.doc_type,
                        "issuing_country": d.issuing_country,
                        "valid_until": d.valid_until,
                    }
                    for d in documents[start : start + batch]
                ]
            )
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(TravelDocument.id)
        )
        created.extend(result.all())
    if created:
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="TRAVEL_DOCUMENT.BULK_LOAD",
            entity_type="travel_document",
            details={"count": len(created)},
        )
    return created


async def start_renewals(
    session: AsyncSession, document_ids: list[uuid.UUID], actor: Actor = SYSTEM
) -> int:
    """The seed's renewals already under way (§8): IN_PROGRESS, by the system actor."""
    for document_id in sorted(document_ids):
        await _step(
            session, await _locked(session, document_id), "IN_PROGRESS", f"system:{actor.id}", actor
        )
    return len(document_ids)
