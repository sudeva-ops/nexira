"""Watch Officer: logs every new incident (INCIDENT_CREATED -> LOG_INFO)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event
from app.modules.agents.agents import facts
from app.modules.agents.proposals import ProposalIn


class WatchOfficer:
    code = "WATCH_OFFICER"
    observes = frozenset({"INCIDENT_CREATED"})
    proposes = ("LOG_INFO",)

    async def observe(self, session: AsyncSession, event: Event) -> list[ProposalIn]:
        incident = await facts.incident(session, event.payload.get("incident_id"))
        if incident is None:
            return []
        evidence = await facts.signal_evidence(session, incident.id)
        text = (
            f"New incident {incident.reference}: {incident.title}. Signal severity "
            f"{incident.signal_severity}, confidence {incident.confidence}%, from "
            f"{', '.join(e['source'] for e in evidence) or 'one source'}."
        )
        return [
            ProposalIn(
                agent_code=self.code,
                proposal_key=f"LOG_INFO:incident_created:{incident.id}",
                action_type="LOG_INFO",
                title=f"Log new incident {incident.reference}",
                proposed_action="Record the new incident on the timeline for the duty team.",
                action_payload={"text": text},
                incident_id=incident.id,
                evidence=evidence,
                alternatives=[],
                risk_if_no_action="The duty team may miss the first report of the incident.",
                confidence=incident.confidence,
            )
        ]
