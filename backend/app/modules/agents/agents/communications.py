"""Communications: when a playbook step that carries a citizen advisory is done
(PB-07 step 4, shelter-in-place), propose the advisory to registered citizens in
the zone (PLAYBOOK_STEP -> SEND_EXTERNAL_MESSAGE).

D-15: the texts are the pre-written EN/AR/FR/SW templates from the step's
configuration. Until native speakers review them, AR/FR/SW keep their REVIEW
REQUIRED marker; an alternative offers English only."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event
from app.modules.agents.agents import facts
from app.modules.agents.proposals import ProposalIn
from app.modules.playbooks.models import PlaybookStep


class Communications:
    code = "COMMUNICATIONS"
    observes = frozenset({"PLAYBOOK_STEP"})

    async def observe(self, session: AsyncSession, event: Event) -> list[ProposalIn]:
        if event.payload.get("step_status") != "DONE" or not event.payload.get("step_id"):
            return []
        try:
            step = await session.get(PlaybookStep, uuid.UUID(str(event.payload["step_id"])))
        except ValueError:
            return []
        advisory = (step.action_config.get("citizen_advisory") if step else None) or None
        incident = await facts.incident(session, event.payload.get("incident_id"))
        if step is None or not isinstance(advisory, dict) or incident is None:
            return []
        translations = dict(advisory.get("translations") or {})
        english = translations.pop("en", None)
        if not english:
            return []
        channels = list(advisory.get("channels") or ["SMS"])
        audience = {"exposed": True, "person_types": ["CITIZEN"]}
        payload = {
            "campaign_type": "ADVISORY",
            "message": english,
            "translations": translations,
            "channels": channels,
            "audience": audience,
        }
        reviewed = not any("REVIEW REQUIRED" in text for text in translations.values())
        return [
            ProposalIn(
                agent_code=self.code,
                proposal_key=f"SEND_EXTERNAL_MESSAGE:advisory:{event.payload['run_id']}:{step.id}",
                action_type="SEND_EXTERNAL_MESSAGE",
                title=f"Advise registered citizens · {incident.reference}",
                proposed_action=(
                    "Send the shelter-in-place advisory to registered citizens in the zone in "
                    f"English, {', '.join(sorted(translations)).upper() or 'no other language'} "
                    f"({' · '.join(channels)}, simulated)."
                ),
                action_payload=payload,
                incident_id=incident.id,
                evidence=[
                    {"text": f"Step {step.seq} · {step.name} completed", "source": "playbook run"},
                    {
                        "text": "Templates: "
                        + ("reviewed" if reviewed else "AR/FR/SW awaiting native-speaker review"),
                        "source": "D-15",
                    },
                ],
                alternatives=[
                    {
                        "label": "English only",
                        "action_type": "SEND_EXTERNAL_MESSAGE",
                        "action_payload": {**payload, "translations": {}},
                        "rationale": "Until the AR/FR/SW templates are reviewed (D-15).",
                    }
                ],
                risk_if_no_action="Citizens in the zone are not told to shelter in place.",
                confidence=85,
            )
        ]
