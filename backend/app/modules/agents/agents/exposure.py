"""Exposure: posts the exposure summary (EXPOSURE_COMPUTED -> POST_INTERNAL_NOTE).

The proposal key includes the figures, so recomputing the same exposure (each
fused signal triggers one) is one note; a real change is a new note."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event
from app.modules.agents.agents import facts
from app.modules.agents.proposals import ProposalIn
from app.modules.intel.exposure import exposure_counts


class ExposureAgent:
    code = "EXPOSURE"
    observes = frozenset({"EXPOSURE_COMPUTED"})

    async def observe(self, session: AsyncSession, event: Event) -> list[ProposalIn]:
        incident = await facts.incident(session, event.payload.get("incident_id"))
        if incident is None or incident.status != "ACTIVE":
            return []
        c = await exposure_counts(session, incident.id)
        if c.people == 0 and c.sites == 0:
            return []
        text = (
            f"Exposure for {incident.reference} ({incident.severity}): {c.summary()}. "
            f"Mission property in the zone: {c.mission_sites}."
        )
        return [
            ProposalIn(
                agent_code=self.code,
                proposal_key=(
                    f"POST_INTERNAL_NOTE:exposure:{incident.id}:{c.people}:{c.staff}:"
                    f"{c.delegates}:{c.citizens}:{c.sites}:{c.trips}:{incident.severity}"
                ),
                action_type="POST_INTERNAL_NOTE",
                title=f"Exposure summary for {incident.reference}",
                proposed_action="Post the exposure summary as an internal note.",
                action_payload={"text": text},
                incident_id=incident.id,
                evidence=[
                    {"text": c.summary(), "source": "NEXIRA exposure engine"},
                    {
                        "text": f"Impact radius {incident.impact_radius_m // 1000} km",
                        "source": "incident",
                    },
                ],
                alternatives=[],
                risk_if_no_action="Responders may not know who is in the impact zone.",
                confidence=90,
            )
        ]
