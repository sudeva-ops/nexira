"""Health Intelligence (HL-01..06, HL-09; D-39; docs/plan-pilot-hl.md).

Advisories are a country-level list, not incidents: the simulated feed creates and
updates them (ingest), and an advisory affects every mission in its countries. Facilities
are listed by distance with an Avoid flag computed from ACTIVE incidents. Readiness is
counts only, never a person (D-39). A health advisory is sent as a Mass Notification
campaign under D-31.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import approvals, audit
from app.core.events import Event
from app.core.security import CurrentUser
from app.modules.health_intel.models import (
    CountryHealthRequirement,
    HealthAdvisory,
    MedicalFacility,
    MissionHealthReadiness,
)
from app.modules.health_intel.schemas import (
    AdvisoryOut,
    AffectedMissionOut,
    CampaignOut,
    FacilityOut,
    LevelCount,
    MissionHealthOut,
    ReadinessOut,
    RequirementOut,
    SummaryOut,
    VaccineOut,
)
from app.modules.notifications import compose, templates
from app.modules.people.models import Mission
from app.modules.tenancy.service import SYSTEM, Actor

log = logging.getLogger(__name__)

LEVELS = ("LOW", "MODERATE", "HIGH", "CRITICAL")
RANK = {level: n for n, level in enumerate(LEVELS)}
PROPOSE_FROM = "HIGH"  # HL-07: HIGH or CRITICAL
CLOSED_SHOWN = timedelta(days=7)  # plan-pilot-hl §8
# HL-06: the mission's staff, their dependants and registered citizens; simulated channels.
AUDIENCE = ["CITIZEN", "DEPENDANT", "DIPLOMAT", "LOCAL_STAFF"]
CHANNELS = ["SMS", "APP"]
GENERAL_TEMPLATE = "HEALTH_GENERAL"  # plan-pilot-hl G-1: a topic with no template of its own


def template_code(topic_code: str) -> str:
    return f"HEALTH_{topic_code}"


class HealthError(Exception):
    """The request cannot be done: status_code 403, 404 or 409."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class AdvisoryIn(BaseModel):
    """One bulletin from the simulated feed (a HEALTH_ADVISORY scenario event, §2)."""

    external_id: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=100)
    topic_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,39}$")
    countries: list[str] = Field(min_length=1, max_length=60)
    region_label: str = Field(min_length=1, max_length=200)
    level: Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]
    guidance: str = Field(min_length=1, max_length=500)
    source: str = Field(min_length=1, max_length=200)
    status: Literal["OPEN", "CLOSED"] = "OPEN"
    published_at: AwareDatetime | None = None  # the feed's time; now if not given


@dataclass(frozen=True)
class Ingested:
    advisory: HealthAdvisory
    previous_level: str | None  # None: new
    previous_status: str | None


def advisory_event(result: Ingested) -> Event:
    a = result.advisory
    return Event(
        type="HEALTH_ADVISORY_UPDATED",
        tenant_id=a.tenant_id,
        payload={
            "advisory_id": str(a.id),
            "reference": a.reference,
            "level": a.level,
            "previous_level": result.previous_level,
            "status": a.status,
            # Each change is its own revision, so a fall and a new rise can propose again
            # (review of Prompt 61, M3); a redelivered event keeps it.
            "revision": int(a.updated_at.timestamp() * 1_000_000),
        },
        source="health.feed",
    )


async def _write_audit(
    session: AsyncSession, actor: Actor, action: str, advisory: HealthAdvisory, details: Any
) -> None:
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action=f"HEALTH_ADVISORY.{action}",
        entity_type="health_advisory",
        entity_id=advisory.reference,
        details=details,
    )


async def ingest(
    session: AsyncSession, bulletin: AdvisoryIn, actor: Actor = SYSTEM
) -> Ingested | None:
    """Create or update the advisory with this feed id (§2). Only the level, guidance and
    status move; what it is about stays as first published (PC-26). None when nothing
    changed, or the bulletin is for a closed or unknown-and-closed advisory.

    Two first bulletins for one feed id at once: the lock below finds no row for either,
    so the second insert fails on UNIQUE (tenant_id, external_id) and the stream consumer
    retries it, which then updates (review of Prompt 61, L6)."""
    advisory = await session.scalar(
        select(HealthAdvisory)
        .where(HealthAdvisory.external_id == bulletin.external_id)
        .with_for_update()
    )
    if advisory is None:
        if bulletin.status == "CLOSED":
            log.info("health bulletin %s closes an unknown advisory", bulletin.external_id)
            return None
        reference = await session.scalar(text("SELECT next_reference('HA', false)"))
        advisory = HealthAdvisory(
            tenant_id=session.info["tenant_id"],
            reference=reference,
            external_id=bulletin.external_id,
            topic=bulletin.topic,
            topic_code=bulletin.topic_code,
            countries=sorted(set(bulletin.countries)),
            region_label=bulletin.region_label,
            level=bulletin.level,
            guidance=bulletin.guidance,
            source=bulletin.source,
            published_at=bulletin.published_at or datetime.now(UTC),
        )
        session.add(advisory)
        await session.flush()
        await session.refresh(advisory)
        await _write_audit(
            session,
            actor,
            "CREATE",
            advisory,
            {"topic": advisory.topic, "level": advisory.level, "countries": advisory.countries},
        )
        return Ingested(advisory, None, None)
    if advisory.status == "CLOSED":
        log.info(
            "health bulletin %s for closed %s ignored", bulletin.external_id, advisory.reference
        )
        return None
    fixed = (bulletin.topic, bulletin.topic_code, sorted(set(bulletin.countries)))
    if fixed != (advisory.topic, advisory.topic_code, sorted(advisory.countries)):
        log.warning("health bulletin %s: what it is about is fixed; ignored", bulletin.external_id)
    previous_level, previous_status = advisory.level, advisory.status
    if (bulletin.level, bulletin.guidance, bulletin.status) == (
        advisory.level,
        advisory.guidance,
        advisory.status,
    ):
        return None
    advisory.level = bulletin.level
    advisory.guidance = bulletin.guidance
    advisory.status = bulletin.status
    await session.flush()
    await session.refresh(advisory, ["updated_at"])
    await _write_audit(
        session,
        actor,
        "CLOSE" if bulletin.status == "CLOSED" else "UPDATE",
        advisory,
        {"level": [previous_level, advisory.level], "status": advisory.status},
    )
    return Ingested(advisory, previous_level, previous_status)


# --- reading ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class MissionRow:
    id: uuid.UUID
    code: str
    city: str
    country_code: str


async def mission_rows(session: AsyncSession) -> list[MissionRow]:
    rows = await session.execute(
        select(Mission.id, Mission.code, Mission.city, Mission.country_code).order_by(Mission.code)
    )
    return [MissionRow(*r) for r in rows]


def affected(advisory: HealthAdvisory, missions: list[MissionRow]) -> list[MissionRow]:
    """HL-02: the missions in the advisory's countries (only while it is OPEN)."""
    if advisory.status != "OPEN":
        return []
    countries = set(advisory.countries)
    return [m for m in missions if m.country_code in countries]


async def _open(session: AsyncSession) -> list[HealthAdvisory]:
    return list(
        await session.scalars(select(HealthAdvisory).where(HealthAdvisory.status == "OPEN"))
    )


def _levels(advisories: list[HealthAdvisory], missions: list[MissionRow]) -> dict[uuid.UUID, str]:
    """Each mission's highest OPEN advisory level."""
    found: dict[uuid.UUID, str] = {}
    for a in advisories:
        for m in affected(a, missions):
            if m.id not in found or RANK[a.level] > RANK[found[m.id]]:
                found[m.id] = a.level
    return found


def _out(a: HealthAdvisory, missions: list[MissionRow]) -> AdvisoryOut:
    return AdvisoryOut(
        id=a.id,
        reference=a.reference,
        topic=a.topic,
        topic_code=a.topic_code,
        countries=list(a.countries),
        region_label=a.region_label,
        level=a.level,
        guidance=a.guidance,
        source=a.source,
        status=a.status,
        published_at=a.published_at,
        updated_at=a.updated_at,
        missions=[
            AffectedMissionOut(mission_id=m.id, code=m.code, city=m.city)
            for m in affected(a, missions)
        ],
    )


async def list_advisories(session: AsyncSession) -> list[AdvisoryOut]:
    """OPEN advisories, and those closed in the last 7 days; the highest level first."""
    since = datetime.now(UTC) - CLOSED_SHOWN
    rows = await session.scalars(
        select(HealthAdvisory).where(
            (HealthAdvisory.status == "OPEN") | (HealthAdvisory.updated_at >= since)
        )
    )
    missions = await mission_rows(session)
    shown = sorted(
        rows,
        key=lambda a: (a.status != "OPEN", -RANK[a.level], -a.updated_at.timestamp(), a.reference),
    )
    return [_out(a, missions) for a in shown]


async def summary(session: AsyncSession) -> SummaryOut:
    missions = await mission_rows(session)
    advisories = await _open(session)
    levels = _levels(advisories, missions)
    country_of = {m.id: m.country_code for m in missions}
    open_topics = {(c, a.topic_code) for a in advisories for c in a.countries}
    not_offered = 0
    for r in await session.scalars(select(MissionHealthReadiness)):
        for topic, offered in r.vaccines_offered.items():
            if (country_of.get(r.mission_id), topic) in open_topics:
                not_offered += max(0, r.staff - int(offered))
    vetted = await session.scalar(
        text("SELECT count(*) FROM medical_facility WHERE vetted_by IS NOT NULL")
    )
    return SummaryOut(
        open_advisories=len(advisories),
        affecting_missions=sum(1 for a in advisories if affected(a, missions)),
        missions_with_advisory=len(levels),
        by_level=[
            LevelCount(level=level, missions=n)
            for level in reversed(LEVELS)
            if (n := sum(1 for v in levels.values() if v == level))
        ],
        staff_not_offered=not_offered,
        vetted_facilities=int(vetted or 0),
    )


def _requirement_out(r: CountryHealthRequirement) -> RequirementOut:
    return RequirementOut(
        country_code=r.country_code,
        mandatory=r.mandatory,
        recommended=r.recommended,
        source=r.source,
    )


async def list_requirements(session: AsyncSession) -> list[RequirementOut]:
    rows = await session.scalars(
        select(CountryHealthRequirement).order_by(CountryHealthRequirement.country_code)
    )
    return [_requirement_out(r) for r in rows]


async def requirement_for(session: AsyncSession, country: str | None) -> RequirementOut | None:
    """HL-03 on the trip: the destination's requirements, if any."""
    if not country:
        return None
    row = await session.get(CountryHealthRequirement, (session.info["tenant_id"], country.upper()))
    return _requirement_out(row) if row else None


_FACILITIES = text(
    """
    SELECT f.id, f.name, f.capabilities, f.trauma_level, f.open_24_7, f.source, p.name AS partner,
           ST_Distance(f.location, m.location)::int AS distance_m,
           (SELECT i.reference FROM incident i
             WHERE i.status = 'ACTIVE' AND ST_DWithin(f.location, i.location, i.impact_radius_m)
             ORDER BY i.opened_at, i.reference LIMIT 1) AS avoid_incident
      FROM medical_facility f
      JOIN mission m ON m.id = f.mission_id
      LEFT JOIN partner p ON p.id = f.vetted_by
     WHERE f.mission_id = :mission_id
     ORDER BY distance_m, f.name
    """
)


async def mission_health(session: AsyncSession, mission_id: uuid.UUID) -> MissionHealthOut:
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise HealthError(404, "Mission not found")
    missions = await mission_rows(session)
    advisories = await _open(session)
    level = _levels(advisories, missions).get(mission.id)
    facilities = [
        FacilityOut(
            id=r.id,
            name=r.name,
            capabilities=list(r.capabilities),
            trauma_level=r.trauma_level,
            open_24_7=r.open_24_7,
            vetted_by=r.partner,
            distance_m=r.distance_m,
            avoid=r.avoid_incident is not None,
            avoid_incident=r.avoid_incident,
            source=r.source,
        )
        for r in await session.execute(_FACILITIES, {"mission_id": mission.id})
    ]
    row = await session.get(MissionHealthReadiness, (session.info["tenant_id"], mission.id))
    open_topics = {a.topic_code for a in advisories if mission.country_code in a.countries}
    readiness = (
        ReadinessOut(
            staff=row.staff,
            blood_type_on_file=row.blood_type_on_file,
            insurance_active=row.insurance_active,
            trauma_kits=row.trauma_kits,
            vaccines=[
                VaccineOut(topic_code=t, offered=int(n), open_advisory=t in open_topics)
                for t, n in sorted(row.vaccines_offered.items())
            ],
            as_of=row.as_of,
            source=row.source,
        )
        if row
        else None
    )
    return MissionHealthOut(
        mission_id=mission.id,
        code=mission.code,
        city=mission.city,
        country_code=mission.country_code,
        level=level,
        facilities=facilities,
        readiness=readiness,
        requirement=await requirement_for(session, mission.country_code),
    )


# --- sending (HL-06) -------------------------------------------------------------------------


@dataclass(frozen=True)
class Message:
    code: str  # the template used
    template_id: uuid.UUID
    english: str
    translations: dict[str, str]  # ar, fr, sw; REVIEW REQUIRED until reviewed (D-15)


async def message_for(
    session: AsyncSession, advisory: HealthAdvisory, mission_id: uuid.UUID
) -> Message | None:
    """The topic's template for the mission, else the generic health template (G-1)."""
    for code in (template_code(advisory.topic_code), GENERAL_TEMPLATE):
        resolved = await templates.resolve(session, code, mission_id)
        if resolved is not None:
            texts = dict(resolved.texts)
            english = texts.pop("en")
            return Message(code, resolved.template_id, english, texts)
    return None


async def advisory_for_mission(
    session: AsyncSession, advisory_id: uuid.UUID, mission_id: uuid.UUID
) -> tuple[HealthAdvisory, Mission]:
    """An OPEN advisory and a mission it affects, or a HealthError."""
    advisory = await session.get(HealthAdvisory, advisory_id)
    if advisory is None:
        raise HealthError(404, "Advisory not found")
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise HealthError(404, "Mission not found")
    if advisory.status != "OPEN":
        raise HealthError(409, f"{advisory.reference} is closed")
    if mission.country_code not in advisory.countries:
        raise HealthError(409, f"{advisory.reference} does not affect {mission.city}")
    return advisory, mission


async def may_send(session: AsyncSession, user: CurrentUser, mission_id: uuid.UUID) -> bool:
    """HL-06, §48 Q6: the Mass Notification composers, within the mission's scope."""
    return await approvals.user_has_role(session, user, compose.COMPOSERS, mission_id)


async def send_permission(session: AsyncSession, user: CurrentUser, mission_id: uuid.UUID) -> bool:
    """For the screen: a composer for the mission, and an OPEN advisory affects it."""
    mission = await session.get(Mission, mission_id)
    if mission is None or not await may_send(session, user, mission_id):
        return False
    return any(mission.country_code in a.countries for a in await _open(session))


async def create_campaign(
    session: AsyncSession, user: CurrentUser, advisory_id: uuid.UUID, mission_id: uuid.UUID
) -> CampaignOut:
    """A DRAFT campaign from the topic's template (HL-06). The author then submits it on
    Mass Notification; with citizens in the audience a second person approves (D-31)."""
    advisory, mission = await advisory_for_mission(session, advisory_id, mission_id)
    if not await may_send(session, user, mission.id):
        raise HealthError(
            403,
            "Sending a health advisory needs DUTY_OFFICER, SECURITY_OFFICER, CONSULAR_OFFICER "
            "or ADMIN for this mission",
        )
    message = await message_for(session, advisory, mission.id)
    if message is None:
        raise HealthError(409, "No health advisory template")
    try:
        campaign = await compose.create_draft(
            session,
            user,
            compose.Content(
                kind="ADVISORY",
                message=message.english,
                channels=list(CHANNELS),
                missions=[mission.id],
                person_types=list(AUDIENCE),
                translations=message.translations,
                template_id=message.template_id,
            ),
        )
    except compose.CampaignError as e:
        raise HealthError(e.status_code, str(e)) from None
    await _write_audit(
        session,
        Actor(type="USER", id=str(user.id)),
        "CAMPAIGN",
        advisory,
        {"campaign": campaign.reference, "mission": mission.code, "template": message.code},
    )
    return CampaignOut(
        campaign_id=campaign.id,
        reference=campaign.reference,
        status=campaign.status,
        template=message.code,
    )


async def prepare_by_agent(
    session: AsyncSession,
    *,
    advisory_id: uuid.UUID,
    mission_id: uuid.UUID,
    message: str,
    translations: dict[str, str],
    channels: list[str],
    proposal_id: uuid.UUID,
    approved_by: uuid.UUID | None,
    actor: Actor,
) -> compose.Outcome:
    """PREPARE_HEALTH_ADVISORY (HL-07, plan-pilot-hl G-2): the campaign the approvers read,
    to the same audience as a person's (HL-06), waiting for a second person: the
    proposal's approver is its submitter, and no one who decided the proposal may approve
    it (D-31). The words must be the mission's template, as proposed, and the channels the
    health channels (review of Prompt 61, M5). The advisory must still be OPEN and affect
    the mission; its level may have fallen since, and the second person sees that."""
    if approved_by is None:
        raise HealthError(409, "A health advisory needs a person's approval first")
    advisory, mission = await advisory_for_mission(session, advisory_id, mission_id)
    template = await message_for(session, advisory, mission.id)
    if template is None or message != template.english:
        raise HealthError(409, "The advisory text is not the mission's template")
    if any(template.translations.get(lang) != t for lang, t in translations.items()):
        raise HealthError(409, "A translation is not the template's (D-15)")
    if not set(channels) <= set(CHANNELS):
        raise HealthError(409, f"Health advisories go by {' · '.join(CHANNELS)} only")
    try:
        outcome = await compose.prepare_for_approval(
            session,
            compose.Content(
                kind="ADVISORY",
                message=message,
                channels=channels,
                missions=[mission.id],
                person_types=list(AUDIENCE),
                translations=translations,
                template_id=template.template_id,
            ),
            proposal_id=proposal_id,
            submitted_by=approved_by,
            actor=actor,
        )
    except compose.CampaignError as e:
        raise HealthError(e.status_code, str(e)) from None
    await _write_audit(
        session,
        actor,
        "CAMPAIGN",
        advisory,
        {
            "campaign": outcome.campaign.reference,
            "mission": mission.code,
            "proposal": str(proposal_id),
        },
    )
    return outcome


# --- seeding (Prompt 62), through the service layer as nexira_api ----------------------------


async def ensure_advisories(
    session: AsyncSession, bulletins: list[AdvisoryIn], actor: Actor = SYSTEM
) -> int:
    """The seeded advisories: new feed ids only, no events (so no agent reacts, §2).
    Audited once with the count."""
    existing = set(await session.scalars(select(HealthAdvisory.external_id)))
    made = 0
    for b in bulletins:
        if b.external_id in existing or b.status != "OPEN":
            continue
        reference = await session.scalar(text("SELECT next_reference('HA', false)"))
        session.add(
            HealthAdvisory(
                tenant_id=session.info["tenant_id"],
                reference=reference,
                external_id=b.external_id,
                topic=b.topic,
                topic_code=b.topic_code,
                countries=sorted(set(b.countries)),
                region_label=b.region_label,
                level=b.level,
                guidance=b.guidance,
                source=b.source,
                published_at=b.published_at or datetime.now(UTC),
            )
        )
        made += 1
    await session.flush()
    if made:
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="HEALTH_ADVISORY.SEED",
            entity_type="health_advisory",
            details={"advisories": made},
        )
    return made


@dataclass(frozen=True)
class FacilityIn:
    mission_id: uuid.UUID
    name: str
    lat: float
    lon: float
    capabilities: list[str]
    open_24_7: bool
    trauma_level: int | None = None
    vetted_by: uuid.UUID | None = None


@dataclass(frozen=True)
class ReadinessIn:
    mission_id: uuid.UUID
    staff: int
    blood_type_on_file: int
    insurance_active: int
    trauma_kits: int
    vaccines_offered: dict[str, int]
    as_of: date


async def ensure_reference_data(
    session: AsyncSession,
    *,
    facilities: list[FacilityIn],
    requirements: list[tuple[str, str, str]],  # (country, mandatory, recommended)
    readiness: list[ReadinessIn],
    actor: Actor = SYSTEM,
) -> dict[str, int]:
    """Seed facilities (for missions with none yet), requirements and readiness (for those
    with none yet). Existing rows are never changed (PC-27..29). Audited once."""
    tenant_id: uuid.UUID = session.info["tenant_id"]
    has_facilities = set(await session.scalars(select(MedicalFacility.mission_id)))
    new_facilities = [f for f in facilities if f.mission_id not in has_facilities]
    for f in new_facilities:
        await session.execute(
            text(
                "INSERT INTO medical_facility (tenant_id, mission_id, name, location, "
                "capabilities, trauma_level, open_24_7, vetted_by) VALUES (current_tenant_id(), "
                ":mission_id, :name, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, "
                ":capabilities, :trauma_level, :open_24_7, :vetted_by)"
            ),
            {
                "mission_id": f.mission_id,
                "name": f.name,
                "lat": f.lat,
                "lon": f.lon,
                "capabilities": f.capabilities,
                "trauma_level": f.trauma_level,
                "open_24_7": f.open_24_7,
                "vetted_by": f.vetted_by,
            },
        )
    known = set(await session.scalars(select(CountryHealthRequirement.country_code)))
    new_requirements = [r for r in requirements if r[0] not in known]
    session.add_all(
        CountryHealthRequirement(tenant_id=tenant_id, country_code=c, mandatory=m, recommended=rec)
        for c, m, rec in new_requirements
    )
    ready = set(await session.scalars(select(MissionHealthReadiness.mission_id)))
    new_readiness = [r for r in readiness if r.mission_id not in ready]
    session.add_all(
        MissionHealthReadiness(
            tenant_id=tenant_id,
            mission_id=r.mission_id,
            staff=r.staff,
            blood_type_on_file=r.blood_type_on_file,
            insurance_active=r.insurance_active,
            trauma_kits=r.trauma_kits,
            vaccines_offered=r.vaccines_offered,
            as_of=r.as_of,
        )
        for r in new_readiness
    )
    await session.flush()
    counts = {
        "facilities": len(new_facilities),
        "requirements": len(new_requirements),
        "readiness": len(new_readiness),
    }
    if any(counts.values()):
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="HEALTH_REFERENCE.SEED",
            entity_type="health",
            details=counts,
        )
    return counts
