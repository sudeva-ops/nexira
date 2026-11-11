"""A normal day at the embassy (TWN-13; D-53; docs/plan-pilot-twa.md §2). Outside a scenario, the
worker moves one occupant about once a minute: visitors arrive at the gate, wait in the lobby,
are seen in the consular hall and leave; staff go between their offices and the conference room;
a guard walks a round. Every move goes through twin.service.presence() as the simulated access
control feed, so it is stored, audited as SITE.PRESENCE and published like any other (AGENTS.md).

It never runs from the presence consumer, which takes SITE_PRESENCE from the scenario player only
(review of Prompt 84, L5; plan G-1). It only moves the occupants who are there or were seeded
("Visitor 1".."Visitor 11"), so the site keeps its shape (G-4). It pauses while the site shelters,
an evacuation is ACTIVE at its mission, or an NBO-SITE run is mid-scenario (G-3); and while the
"Normal day" switch is off (G-2: a flag per tenant, then a default, then TWIN_NORMAL_DAY)."""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import redis.asyncio as redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.db import tenant_session
from app.core.events import Publisher
from app.modules.people.models import Mission, Site
from app.modules.twin import service
from app.modules.twin.models import SitePresence, SiteZone

log = logging.getLogger(__name__)

EVERY_S = 60  # about one move a minute (§120 Q1)
VISITORS = 11  # the seeded visitors, "Visitor 1".."Visitor 11"
MIN_VISITORS = 6  # the band the day keeps (G-4)
MOVES = ("admit", "consult", "leave", "arrive", "staff", "guard")
FLAG = "nexira:twin:normal-day:"  # + tenant id, or "default" (G-2)


# --- the switch (G-2) --------------------------------------------------------------------------


class Flags(Protocol):
    async def get(self, name: str) -> str | None: ...

    async def set(self, name: str, value: str) -> object: ...


class RedisFlags:
    """Flags in Redis, as strings (the app's client decodes responses)."""

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    async def get(self, name: str) -> str | None:
        value = await self._client.get(name)
        return value if isinstance(value, str) else None

    async def set(self, name: str, value: str) -> object:
        return await self._client.set(name, value)


async def is_on(flags: Flags, tenant_id: uuid.UUID, default: bool) -> bool:
    """The tenant's switch, else the deployment's default (reset-demo sets it off), else the
    TWIN_NORMAL_DAY setting."""
    for name in (f"{FLAG}{tenant_id}", f"{FLAG}default"):
        value = await flags.get(name)
        if value in ("on", "off"):
            return value == "on"
    return default


async def switch(flags: Flags, tenant_id: uuid.UUID, on: bool) -> None:
    await flags.set(f"{FLAG}{tenant_id}", "on" if on else "off")


def wait_s(step: int) -> int:
    """60 s, give or take 15, the same sequence every time (testable)."""
    return EVERY_S - 15 + (step * 37) % 31


# --- choosing a move (pure) ----------------------------------------------------------------------


@dataclass(frozen=True)
class Occupant:
    key: str  # a person id (staff) or a label, as presence() takes it
    kind: str  # STAFF, GUARD, VISITOR
    zone: str  # the zone's code
    since: datetime


@dataclass(frozen=True)
class Plan:
    """The zone codes by kind; the first gate by code is where visitors come and go."""

    gate: str | None
    lobby: str | None
    consular: str | None
    office: str | None
    conference: str | None
    muster: str | None


def plan_of(zones: list[tuple[str, str]]) -> Plan:
    """From (code, kind) pairs."""

    def first(kind: str) -> str | None:
        return min((c for c, k in zones if k == kind), default=None)

    return Plan(
        gate=first("GATE"),
        lobby=first("LOBBY"),
        consular=first("CONSULAR"),
        office=first("OFFICE"),
        conference=first("CONFERENCE"),
        muster=first("MUSTER"),
    )


def _oldest(people: list[Occupant]) -> Occupant | None:
    return min(people, key=lambda o: (o.since, o.key), default=None)


def next_move(plan: Plan, present: list[Occupant], step: int) -> tuple[str, str | None] | None:
    """The move for this step, as (occupant, zone or None to leave), or None if there is none.
    The kinds of move take turns; one with nothing to do hands over to the next."""
    visitors = [o for o in present if o.kind == "VISITOR"]
    staff = sorted((o for o in present if o.kind == "STAFF"), key=lambda o: o.key)

    def admit() -> tuple[str, str | None] | None:
        at_gate = _oldest([o for o in visitors if o.zone == plan.gate])
        return (at_gate.key, plan.lobby) if at_gate and plan.lobby else None

    def consult() -> tuple[str, str | None] | None:
        waiting = _oldest([o for o in visitors if o.zone == plan.lobby])
        return (waiting.key, plan.consular) if waiting and plan.consular else None

    def leave() -> tuple[str, str | None] | None:
        if len(visitors) <= MIN_VISITORS:
            return None
        seen = _oldest([o for o in visitors if o.zone == plan.consular])
        return (seen.key, None) if seen else None

    def arrive() -> tuple[str, str | None] | None:
        if len(visitors) >= VISITORS or plan.gate is None:
            return None
        here = {o.key for o in visitors}
        absent = [f"Visitor {n}" for n in range(1, VISITORS + 1) if f"Visitor {n}" not in here]
        return (absent[0], plan.gate) if absent else None

    def meeting() -> tuple[str, str | None] | None:
        if not staff or plan.office is None or plan.conference is None:
            return None
        person = staff[(step // len(MOVES)) % len(staff)]
        if person.zone == plan.office:
            return (person.key, plan.conference)
        if person.zone == plan.conference:
            return (person.key, plan.office)
        return None  # the IT team and the consular staff stay where they work

    def round_() -> tuple[str, str | None] | None:
        if plan.lobby is None or plan.muster is None:
            return None
        walking = [o for o in present if o.kind == "GUARD" and o.zone in (plan.lobby, plan.muster)]
        guard = _oldest(walking)
        if guard is None:
            return None
        return (guard.key, plan.muster if guard.zone == plan.lobby else plan.lobby)

    choose = {
        "admit": admit,
        "consult": consult,
        "leave": leave,
        "arrive": arrive,
        "staff": meeting,
        "guard": round_,
    }
    for turn in range(len(MOVES)):
        move = choose[MOVES[(step + turn) % len(MOVES)]]()
        if move is not None:
            return move
    return None


# --- the tick ------------------------------------------------------------------------------------

_SITES = text(
    """
    SELECT DISTINCT s.id FROM site s JOIN site_zone z ON z.site_id = s.id ORDER BY s.id
    """
)
_EVACUATING = text(
    "SELECT 1 FROM evacuation WHERE mission_id = :mission AND status = 'ACTIVE' LIMIT 1"
)
# An NBO-SITE run that is playing, or paused before its last scene (the scene numbers come from
# the scenario's own events).
_SCENARIO = text(
    """
    SELECT 1 FROM scenario_run r JOIN scenario c ON c.id = r.scenario_id
     WHERE c.code = 'NBO-SITE'
       AND (r.status = 'PLAYING'
            OR (r.status = 'PAUSED' AND r.current_scene BETWEEN 1 AND
                (SELECT max(e.scene_no) - 1 FROM scenario_event e WHERE e.scenario_id = c.id)))
     LIMIT 1
    """
)


async def paused(session: AsyncSession, site: Site) -> str | None:
    """Why the day waits at this site now, or None (G-3)."""
    if await service.sheltering(session, site.mission_id):
        return "sheltering"
    if await session.scalar(_EVACUATING, {"mission": site.mission_id}):
        return "evacuating"
    if await session.scalar(_SCENARIO):
        return "NBO-SITE"
    return None


async def _site_tick(session: AsyncSession, site: Site, step: int) -> service.Outcome | None:
    if (why := await paused(session, site)) is not None:
        log.debug("normal day paused at %s: %s", site.id, why)
        return None
    zones = list(await session.scalars(select(SiteZone).where(SiteZone.site_id == site.id)))
    code = {z.id: z.code for z in zones}
    present = [
        Occupant(
            key=str(p.person_id) if p.person_id else (p.label or ""),
            kind=p.kind,
            zone=code[p.zone_id],
            since=p.since,
        )
        for p in await session.scalars(select(SitePresence).where(SitePresence.site_id == site.id))
    ]
    move = next_move(plan_of([(z.code, z.kind) for z in zones]), present, step)
    if move is None:
        return None
    mission = await session.get_one(Mission, site.mission_id)
    return await service.presence(session, f"{mission.code}:{site.site_type}", *move)


async def tick(
    engine: AsyncEngine,
    tenant_id: uuid.UUID,
    publisher: Publisher,
    flags: Flags,
    step: int,
    default_on: bool,
) -> int:
    """One step of the day at every site with a plan; the number of moves made."""
    if not await is_on(flags, tenant_id, default_on):
        return 0
    moved = 0
    async with tenant_session(tenant_id, engine) as session:
        site_ids = list(await session.scalars(_SITES))
    for site_id in site_ids:
        async with tenant_session(tenant_id, engine) as session:
            site = await session.get_one(Site, site_id)
            outcome = await _site_tick(session, site, step)
            await session.commit()
        if outcome is None:
            continue
        moved += 1
        for event in outcome.events:
            try:
                await publisher.publish(event)
            except Exception:
                log.exception("publishing %s failed after commit", event.type)
    return moved
