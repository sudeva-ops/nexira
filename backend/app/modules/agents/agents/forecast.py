"""Forecast (pilot module 16; PRD-06; D-46, docs/plan-pilot-prd.md §8, G-1 option B).

Watches the events calendar; advises, never acts (level 4: ADVISE_READINESS_CHECK has no
action_policy row, so the database makes it advice only, D-12, and it is never executed):
- MISSION_EVENT_ADDED: when calendar events take the mission's forecast to the threshold (70)
  or above within 14 days -> ADVISE_READINESS_CHECK for the mission, with the forecast, the
  events and the drivers as evidence.
It names no VIP visit, segment, venue or time, so a restricted visit stays hidden from every
role that reads the Decision Queue (D-42, VIP-06); a programme change stays with the Security
Officer on VIP Protection. One proposal per mission and peak day (proposal_key
PRD:<mission>:<day>). It does not watch incidents, so no other scenario gains a proposal.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event
from app.modules.agents.proposals import ProposalIn
from app.modules.predictive import service as predictive

CODE = "FORECAST"
ACTION = "ADVISE_READINESS_CHECK"
SOURCE = "Predictive Risk · illustrative model (simulated)"


class Forecast:
    code = CODE
    observes = frozenset({"MISSION_EVENT_ADDED"})
    proposes = (ACTION,)

    async def observe(self, session: AsyncSession, event: Event) -> list[ProposalIn]:
        try:
            mission_id = uuid.UUID(str(event.payload.get("mission_id")))
        except ValueError:
            return []
        found = await predictive.outlook(session, mission_id)
        if found is None or found.peak.value < predictive.THRESHOLD or not found.events_at_peak:
            return []
        c, peak = found.components, found.peak
        top = max(found.events_at_peak, key=lambda e: (e.weight, e.title))
        when = peak.day.strftime("%d %b")
        drivers = [
            (key, points)
            for key, points in c.points(peak.day).items()
            if points and key != "baseline"
        ]
        return [
            ProposalIn(
                agent_code=CODE,
                proposal_key=f"PRD:{mission_id}:{peak.day.isoformat()}",
                action_type=ACTION,
                title=f"{c.city} risk forecast {found.now} → {peak.value} by {when}",
                proposed_action=(
                    f"Review movements and venues in {c.city} in the next 14 days: "
                    f"{top.title} on {top.starts_on.strftime('%d %b')}."
                ),
                action_payload={"mission_id": str(mission_id)},
                evidence=[
                    {
                        "text": f"{c.code} risk index {found.now} today, {peak.value} on {when} "
                        f"(elevated threshold {predictive.THRESHOLD}; "
                        f"band {peak.low} to {peak.high})",
                        "source": SOURCE,
                    },
                    *(
                        {
                            "text": f"{e.title} · {e.starts_on.strftime('%d %b')}"
                            + (f" · about {e.attendance:,} people" if e.attendance else "")
                            + f" · weight {e.weight}",
                            "source": e.source,
                        }
                        for e in found.events_at_peak
                    ),
                    {
                        "text": "Drivers on that day: "
                        + ", ".join(f"{key} +{points}" for key, points in drivers),
                        "source": SOURCE,
                    },
                ],
                risk_if_no_action=(
                    "Movements and events near the calendar's peak could be disrupted."
                ),
                is_proactive=True,
            )
        ]
