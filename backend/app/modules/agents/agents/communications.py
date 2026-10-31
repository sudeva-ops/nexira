"""Communications: when a playbook step that carries a citizen advisory is done
(PB-07 step 4, shelter-in-place), propose the advisory to registered citizens in
the zone (PLAYBOOK_STEP -> SEND_EXTERNAL_MESSAGE).

D-15: the texts are pre-written EN/AR/FR/SW templates. From PB-07 v2 the step names a
template (citizen_advisory_template), resolved for the incident's mission (D-31,
MN-04), so a Paris incident gets the Paris text. Runs of PB-07 v1 still carry the text
in the step (citizen_advisory). Until native speakers review them, AR/FR/SW keep their
REVIEW REQUIRED marker; an alternative offers English only.

Health (D-39, HL-07; plan-pilot-hl §7): when an advisory rises to HIGH or CRITICAL, for
each mission in its countries, propose PREPARE_HEALTH_ADVISORY from the topic's template.
Approving creates the campaign; a second person approves it before it is sent (G-2)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event
from app.modules.agents.agents import facts
from app.modules.agents.models import AgentProposal
from app.modules.agents.proposals import ProposalIn
from app.modules.health_intel import service as health
from app.modules.health_intel.models import HealthAdvisory, MissionHealthReadiness
from app.modules.notifications import templates
from app.modules.playbooks.models import PlaybookStep


class Communications:
    code = "COMMUNICATIONS"
    observes = frozenset({"PLAYBOOK_STEP", "HEALTH_ADVISORY_UPDATED"})
    proposes = ("SEND_EXTERNAL_MESSAGE", "PREPARE_HEALTH_ADVISORY")

    async def observe(self, session: AsyncSession, event: Event) -> list[ProposalIn]:
        if event.type == "HEALTH_ADVISORY_UPDATED":
            return await self._health(session, event)
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

    async def _health(self, session: AsyncSession, event: Event) -> list[ProposalIn]:
        level, previous = event.payload.get("level"), event.payload.get("previous_level")
        if event.payload.get("status") != "OPEN" or level not in health.RANK:
            return []
        rising = previous not in health.RANK or health.RANK[str(previous)] < health.RANK[str(level)]
        if health.RANK[str(level)] < health.RANK[health.PROPOSE_FROM] or not rising:
            return []
        try:
            advisory = await session.get(
                HealthAdvisory, uuid.UUID(str(event.payload["advisory_id"]))
            )
        except (KeyError, ValueError):
            return []
        if advisory is None or advisory.status != "OPEN":
            return []
        pending = {
            str(p["mission_id"])
            for p in await session.scalars(
                select(AgentProposal.action_payload).where(
                    AgentProposal.action_type == "PREPARE_HEALTH_ADVISORY",
                    AgentProposal.status == "PENDING",
                    AgentProposal.action_payload["advisory_id"].astext == str(advisory.id),
                )
            )
        }
        out: list[ProposalIn] = []
        for mission in health.affected(advisory, await health.mission_rows(session)):
            if str(mission.id) in pending:
                continue  # one open proposal per advisory and mission (G-6)
            message = await health.message_for(session, advisory, mission.id)
            if message is None:
                continue
            out.append(await self._health_proposal(session, advisory, mission, message))
        return out

    async def _health_proposal(
        self,
        session: AsyncSession,
        advisory: HealthAdvisory,
        mission: health.MissionRow,
        message: health.Message,
    ) -> ProposalIn:
        payload = {
            "advisory_id": str(advisory.id),
            "mission_id": str(mission.id),
            "message": message.english,
            "translations": message.translations,
            "channels": list(health.CHANNELS),
        }
        evidence = [
            {
                "text": f"{advisory.topic} · {advisory.region_label} · {advisory.level}",
                "source": f"{advisory.source} · {advisory.reference}",
            }
        ]
        readiness = await session.get(MissionHealthReadiness, (advisory.tenant_id, mission.id))
        if readiness is not None and advisory.topic_code in readiness.vaccines_offered:
            offered = int(readiness.vaccines_offered[advisory.topic_code])
            evidence.append(
                {
                    "text": f"{offered} of {readiness.staff} staff offered the "
                    f"{advisory.topic.lower()} vaccine",
                    "source": "Health readiness (counts only)",
                }
            )
        reviewed = not any("REVIEW REQUIRED" in t for t in message.translations.values())
        evidence.append(
            {
                "text": "Templates: "
                + ("reviewed" if reviewed else "AR/FR/SW awaiting native-speaker review"),
                "source": "D-15",
            }
        )
        languages = ", ".join(sorted(message.translations)).upper() or "no other language"
        return ProposalIn(
            agent_code=self.code,
            proposal_key=f"PREPARE_HEALTH_ADVISORY:{advisory.id}:{mission.id}:{advisory.level}",
            action_type="PREPARE_HEALTH_ADVISORY",
            title=f"Health advisory recommended for {mission.city} staff and citizens",
            proposed_action=(
                f"Prepare the {advisory.topic.lower()} advisory for {mission.city} staff, "
                f"dependants and registered citizens in English, {languages} "
                f"({' · '.join(health.CHANNELS)}, simulated). A second person approves it "
                "before it is sent."
            ),
            action_payload=payload,
            evidence=evidence,
            alternatives=[
                {
                    "label": "English only",
                    "action_type": "PREPARE_HEALTH_ADVISORY",
                    "action_payload": {**payload, "translations": {}},
                    "rationale": "Until the AR/FR/SW templates are reviewed (D-15).",
                }
            ],
            risk_if_no_action="Avoidable illness among staff and citizens.",
            confidence=88,
            is_proactive=True,
        )
