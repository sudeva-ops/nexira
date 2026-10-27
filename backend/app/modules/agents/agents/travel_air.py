"""Travel & Air (pilot module 4; TA-01..04, TA-07, TA-08; D-34, docs/plan-pilot-ta.md).

Watches flights and incidents; proposes, never acts (level 2, D-12):
- FLIGHT_UPDATED: HOLDING, DIVERTED or CANCELLED, or 60 minutes or more late ->
  NOTIFY_TRAVELLERS; DIVERTED or CANCELLED also -> ADVISE_REBOOKING (advice only).
- EXPOSURE_COMPUTED (after every incident change, with its final severity):
  - trips impacted by the incident (JR-06) -> NOTIFY_TRAVELLERS, linked to the incident;
  - approved trips in the incident's mission country whose live risk is now HIGH or
    CRITICAL and above the approved level (JR-07): not started -> CANCEL_TRIP with
    "notify instead" as the alternative (D-14); under way -> NOTIFY_TRAVELLERS. A trip
    that is impacted gets the impacted message only.
Never about a restricted trip (D-33, TA-07). One proposal per trip or flight and cause
(proposal_key, plan §2). Messages are fixed English texts to staff (no LLM, AGT-09).
"""

import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.events import Event
from app.modules.agents.agents import facts
from app.modules.agents.proposals import ProposalIn
from app.modules.travel import trips

DELAY_PROPOSAL_MIN = 60  # D-34 default 4: 30 minutes is only flagged (AT-03)
CODE = "TRAVEL_AIR"

_FLIGHT = text(
    """
    SELECT f.id, f.flight_number, f.status, fa.city AS from_city, f.to_airport,
           ta.city AS to_city, f.diverted_to, da.city AS diverted_city, f.scheduled_arr,
           f.estimated_arr, t.id AS trip_id, t.reference, t.approval_status, t.restricted,
           (SELECT count(*) FROM trip_traveller tt JOIN person p ON p.id = tt.person_id
             WHERE tt.trip_id = t.id AND p.is_active) AS travellers,
           EXISTS (SELECT 1 FROM trip_traveller tt JOIN person p ON p.id = tt.person_id
                    WHERE tt.trip_id = t.id AND p.person_type = 'CITIZEN') AS citizens
      FROM flight f
      JOIN trip_segment s ON s.id = f.trip_segment_id
      JOIN trip t ON t.id = s.trip_id
      JOIN airport fa ON fa.tenant_id = f.tenant_id AND fa.iata = f.from_airport
      JOIN airport ta ON ta.tenant_id = f.tenant_id AND ta.iata = f.to_airport
      LEFT JOIN airport da ON da.tenant_id = f.tenant_id AND da.iata = f.diverted_to
     WHERE f.id = :flight
    """
)


# Both queries keep only trips NOTIFY_TRAVELLERS can reach (the trip audience, D-31;
# review of Prompt 35, M3): an active traveller and no citizen, or it would always fail.
_IMPACTED = text(
    """
    SELECT DISTINCT t.id, t.reference
      FROM trip t
      JOIN trip_traveller tt ON tt.trip_id = t.id
      JOIN incident_exposure e ON e.subject_type = 'PERSON' AND e.subject_id = tt.person_id
      JOIN incident i ON i.id = e.incident_id
     WHERE i.id = :incident AND i.status = 'ACTIVE'
       AND t.approval_status IN ('PENDING', 'APPROVED') AND NOT t.restricted
       AND (i.opened_at AT TIME ZONE 'UTC')::date BETWEEN t.starts_on AND t.ends_on
       AND EXISTS (SELECT 1 FROM trip_traveller tt2 JOIN person p2 ON p2.id = tt2.person_id
                    WHERE tt2.trip_id = t.id AND p2.is_active)
       AND NOT EXISTS (SELECT 1 FROM trip_traveller tt3 JOIN person p3 ON p3.id = tt3.person_id
                        WHERE tt3.trip_id = t.id AND p3.person_type = 'CITIZEN')
    """
)

_IN_COUNTRY = text(
    """
    SELECT t.id, t.reference, t.destination, t.destination_country, t.starts_on, t.ends_on,
           t.approved_risk_level
      FROM trip t
     WHERE t.approval_status = 'APPROVED' AND NOT t.restricted
       AND t.destination_country = :country AND t.ends_on >= :today
       AND EXISTS (SELECT 1 FROM trip_traveller tt2 JOIN person p2 ON p2.id = tt2.person_id
                    WHERE tt2.trip_id = t.id AND p2.is_active)
       AND NOT EXISTS (SELECT 1 FROM trip_traveller tt3 JOIN person p3 ON p3.id = tt3.person_id
                        WHERE tt3.trip_id = t.id AND p3.person_type = 'CITIZEN')
    """
)

_FLIGHT_EVENTS = text("SELECT event_type FROM flight_event WHERE flight_id = :flight ORDER BY id")

_FLIGHT_UNDER_WAY = text(
    """
    SELECT 1 FROM flight f JOIN trip_segment s ON s.id = f.trip_segment_id
     WHERE s.trip_id = :trip AND f.status NOT IN ('SCHEDULED', 'DELAYED', 'CANCELLED')
     LIMIT 1
    """
)


def _notify(trip_id: uuid.UUID, message: str) -> dict[str, Any]:
    return {"trip_id": str(trip_id), "message": message, "channels": ["APP", "SMS"]}


class TravelAir:
    code = CODE
    observes = frozenset({"FLIGHT_UPDATED", "EXPOSURE_COMPUTED"})
    proposes = ("NOTIFY_TRAVELLERS", "CANCEL_TRIP", "ADVISE_REBOOKING")

    async def observe(self, session: AsyncSession, event: Event) -> list[ProposalIn]:
        if event.type == "FLIGHT_UPDATED":
            return await self._flight(session, event)
        return await self._incident(session, event)

    # --- flights (TA-01, TA-02) -----------------------------------------------------------

    async def _flight(self, session: AsyncSession, event: Event) -> list[ProposalIn]:
        try:
            flight_id = uuid.UUID(str(event.payload.get("flight_id")))
        except ValueError:
            return []
        f = (await session.execute(_FLIGHT, {"flight": flight_id})).first()
        if f is None or f.restricted or f.approval_status not in ("PENDING", "APPROVED"):
            return []  # TA-07; restricted trips have no flights anyway (PC-19)
        if f.citizens or not f.travellers:
            return []  # the trip audience would refuse it (review of Prompt 35, M3)
        delay = max(0, round((f.estimated_arr - f.scheduled_arr).total_seconds() / 60))
        people = f"{f.travellers} traveller{'s' if f.travellers != 1 else ''}"
        if f.status == "HOLDING":
            cause, headline = "HOLDING", f"holding near {f.to_city}"
            message = (
                f"Your flight {f.flight_number} is holding near {f.to_city}. The Travel Desk "
                "is following it and will contact you with next steps."
            )
        elif f.status == "DIVERTED":
            where = f.diverted_city or f.diverted_to
            cause, headline = "DIVERTED", f"diverted to {where}"
            message = (
                f"Your flight {f.flight_number} has been diverted to {where}. The Travel Desk "
                "will arrange onward travel and somewhere to stay."
            )
        elif f.status == "CANCELLED":
            cause, headline = "CANCELLED", "cancelled"
            message = (
                f"Your flight {f.flight_number} has been cancelled. The Travel Desk will rebook "
                "you and confirm the new plan."
            )
        elif f.status not in ("LANDED",) and delay >= DELAY_PROPOSAL_MIN:
            cause, headline = "DELAY60", f"{delay} min late"
            message = (
                f"Your flight {f.flight_number} is running about {delay} minutes late. The "
                "Travel Desk will tell you if your plans need to change."
            )
        else:
            return []
        events = [e for (e,) in await session.execute(_FLIGHT_EVENTS, {"flight": f.id})]
        evidence = [
            {
                "text": f"{f.flight_number} {headline} ({f.reference}, {people})",
                "source": "flight tracker (simulated)",
            },
            {"text": "Events: " + (" → ".join(events) or "none yet"), "source": "flight events"},
        ]
        drafts = [
            ProposalIn(
                agent_code=CODE,
                proposal_key=f"NOTIFY_TRAVELLERS:flight:{f.id}:{cause}",
                action_type="NOTIFY_TRAVELLERS",
                title=f"Notify {f.flight_number} travellers · {headline}",
                proposed_action=(
                    f"Tell the {people} on {f.reference} (APP and SMS, simulated): “{message}”"
                ),
                action_payload=_notify(f.trip_id, message),
                evidence=evidence,
                risk_if_no_action=(
                    "The travellers learn of the disruption from the airline, not from us."
                ),
                confidence=95,
            )
        ]
        if cause in ("DIVERTED", "CANCELLED"):
            # Diverted: where they landed. Cancelled: never once airborne (PC-19), so they
            # are still at the departure airport (review of Prompt 35, M2).
            at = (f.diverted_city or f.diverted_to) if cause == "DIVERTED" else f.from_city
            drafts.append(
                ProposalIn(
                    agent_code=CODE,
                    proposal_key=f"ADVISE_REBOOKING:flight:{f.id}:{cause}",
                    action_type="ADVISE_REBOOKING",
                    title=f"Arrange onward travel · {f.flight_number} {headline}",
                    proposed_action=(
                        f"Book onward travel and a hotel in {at} for the {people} on {f.reference} "
                        "through the travel management company. The platform books nothing."
                    ),
                    action_payload={"trip_id": str(f.trip_id), "flight_id": str(f.id), "at": at},
                    evidence=evidence,
                    confidence=90,
                )
            )
        return drafts

    # --- incidents (TA-03, TA-04) ---------------------------------------------------------

    async def _incident(self, session: AsyncSession, event: Event) -> list[ProposalIn]:
        incident = await facts.incident(session, event.payload.get("incident_id"))
        if incident is None or incident.status != "ACTIVE":
            return []
        drafts: list[ProposalIn] = []
        impacted: set[uuid.UUID] = set()
        for trip_id, reference in await session.execute(_IMPACTED, {"incident": incident.id}):
            impacted.add(trip_id)
            message = (
                f"An incident ({incident.reference}, {incident.severity}) is close to where "
                "you are. Stay somewhere safe, avoid the area, and answer the safety check-in "
                "when it arrives."
            )
            drafts.append(
                ProposalIn(
                    agent_code=CODE,
                    proposal_key=f"NOTIFY_TRAVELLERS:impacted:{trip_id}:{incident.id}",
                    action_type="NOTIFY_TRAVELLERS",
                    title=f"Safety message to {reference} travellers · {incident.reference}",
                    proposed_action=(
                        f"Tell {reference}'s travellers (APP and SMS, simulated): “{message}”"
                    ),
                    action_payload=_notify(trip_id, message),
                    incident_id=incident.id,
                    evidence=[
                        {
                            "text": f"{reference} is in the exposure of {incident.reference} "
                            f"({incident.severity})",
                            "source": "exposure (JR-06)",
                        }
                    ],
                    risk_if_no_action="Travellers in the zone do not hear from us.",
                    confidence=incident.confidence,
                )
            )
        country = await session.scalar(
            text("SELECT country_code FROM mission WHERE id = :m"), {"m": incident.mission_id}
        )
        if country is None:
            return drafts  # plan G-1 (Journey): an incident counts for its mission's country
        live = (await trips.destination_risks(session, {country}))[country]
        if trips.rank(live.level) < trips.rank("HIGH"):
            return drafts
        today = datetime.now(ZoneInfo(get_settings().home_tz)).date()
        in_country = list(await session.execute(_IN_COUNTRY, {"country": country, "today": today}))
        # Impacted by ANY active incident, not just this one: those travellers get the
        # impacted message only (plan §2; review of Prompt 35, M1).
        impacted |= set(await trips.impacted_by(session, [t.id for t in in_country]))
        base = live.base
        breakdown = (
            f"security {base.security}, unrest {base.unrest}, health {base.health}, "
            f"transport {base.transport} (base {base.level})"
            if base
            else "no simulated base level (MODERATE)"
        )
        for t in in_country:
            if t.id in impacted:
                continue
            if trips.rank(live.level) <= trips.rank(t.approved_risk_level):
                continue
            evidence = [
                {
                    "text": f"{country} risk now {live.level} "
                    f"(approved at {t.approved_risk_level}); "
                    f"raised by {', '.join(live.incidents) or incident.reference}",
                    "source": "destination risk (simulated)",
                },
                {"text": f"{country}: {breakdown}", "source": "country risk (simulated)"},
            ]
            notify = _notify(
                t.id,
                f"The security situation in {t.destination} has worsened (risk now "
                f"{live.level}). Follow the mission's guidance and keep the Travel Desk informed.",
            )
            under_way = await session.scalar(_FLIGHT_UNDER_WAY, {"trip": t.id})
            if t.starts_on > today and not under_way:  # a red-eye in the air: notify (L2)
                drafts.append(
                    ProposalIn(
                        agent_code=CODE,
                        proposal_key=f"CANCEL_TRIP:risk:{t.id}:{live.level}",
                        action_type="CANCEL_TRIP",
                        title=f"Cancel {t.reference} {t.destination} · risk now {live.level}",
                        proposed_action=(
                            f"Cancel {t.reference} to {t.destination} "
                            f"(starts {t.starts_on:%d %b}): approved at "
                            f"{t.approved_risk_level}, the destination is now {live.level}."
                        ),
                        action_payload={"trip_id": str(t.id)},
                        evidence=evidence,
                        alternatives=[
                            {
                                "label": "Notify the travellers instead",
                                "action_type": "NOTIFY_TRAVELLERS",
                                "action_payload": notify,
                                "rationale": "The trip may still go ahead with precautions.",
                            }
                        ],
                        risk_if_no_action=f"The trip goes ahead into a {live.level} destination.",
                        confidence=incident.confidence,
                    )
                )
            else:
                drafts.append(
                    ProposalIn(
                        agent_code=CODE,
                        proposal_key=f"NOTIFY_TRAVELLERS:risk:{t.id}:{live.level}",
                        action_type="NOTIFY_TRAVELLERS",
                        title=f"Notify {t.reference} travellers · risk now {live.level}",
                        proposed_action=(
                            f"Tell {t.reference}'s travellers (APP and SMS, simulated): "
                            f"“{notify['message']}”"
                        ),
                        action_payload=notify,
                        evidence=evidence,
                        risk_if_no_action="Travellers already there are not warned.",
                        confidence=incident.confidence,
                    )
                )
        return drafts
