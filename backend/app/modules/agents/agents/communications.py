"""Communications: when a playbook step that carries a citizen advisory is done
(PB-07 step 4, shelter-in-place), propose the advisory to registered citizens in
the zone (PLAYBOOK_STEP -> SEND_EXTERNAL_MESSAGE).

D-15: the texts are pre-written EN/AR/FR/SW templates. From PB-07 v2 the step names a
template (citizen_advisory_template), resolved for the incident's mission (D-31,
MN-04), so a Paris incident gets the Paris text. Runs of PB-07 v1 still carry the text
in the step (citizen_advisory). Until native speakers review them, AR/FR/SW keep their
REVIEW REQUIRED marker; an alternative offers English only."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event
from app.modules.agents.agents import facts
from app.modules.agents.proposals import ProposalIn
from app.modules.notifications import templates
from app.modules.playbooks.models import PlaybookStep


class Communications:
    code = "COMMUNICATIONS"
    observes = frozenset({"PLAYBOOK_STEP"})
    proposes = ("SEND_EXTERNAL_MESSAGE",)

    async def observe(self, session: AsyncSession, event: Event) -> list[ProposalIn]:
        if event.payload.get("step_status") != "DONE" or not event.payload.get("step_id"):
            return []
        try:
            step = await session.get(PlaybookStep, uuid.UUID(str(event.payload["step_id"])))
        except ValueError:
            return []
        incident = await facts.incident(session, event.payload.get("incident_id"))
        if step is None or incident is None:
            return []
        config = step.action_config
        translations: dict[str, str] = {}
        channels = ["SMS"]
        if config.get("citizen_advisory_template"):
            resolved = await templates.resolve(
                session, str(config["citizen_advisory_template"]), incident.mission_id
            )
            if resolved is not None:
                translations = dict(resolved.texts)
            channels = list(config.get("citizen_advisory_channels") or channels)
        elif isinstance(config.get("citizen_advisory"), dict):  # a PB-07 v1 run
            translations = dict(config["citizen_advisory"].get("translations") or {})
            channels = list(config["citizen_advisory"].get("channels") or channels)
        english = translations.pop("en", None)
        if not english:
            return []
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
