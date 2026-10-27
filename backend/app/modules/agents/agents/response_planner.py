"""Response Planner: proposes a playbook when an incident matches its trigger rules
(EXPOSURE_COMPUTED -> START_PLAYBOOK, plan G-15).

PB-07's rules ({"category", "min_severity", "max_distance_m"}) depend on the
escalated severity and on exposure, so the planner reacts to EXPOSURE_COMPUTED.
max_distance_m is met when a mission site (any type except HOTEL) is exposed at or
within that distance. The key START_PLAYBOOK:{incident}:{playbook} makes it one
proposal per incident and playbook (plan G-15)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event
from app.modules.agents.agents import facts
from app.modules.agents.proposals import ProposalIn
from app.modules.intel.models import Incident, IncidentExposure
from app.modules.intel.normalise import severity_rank
from app.modules.people.models import Site
from app.modules.playbooks.models import Playbook, PlaybookRun


async def _nearest_mission_site_m(session: AsyncSession, incident: Incident) -> int | None:
    return await session.scalar(
        select(IncidentExposure.distance_m)
        .join(Site, Site.id == IncidentExposure.subject_id)
        .where(
            IncidentExposure.incident_id == incident.id,
            IncidentExposure.subject_type == "SITE",
            Site.site_type != "HOTEL",
        )
        .order_by(IncidentExposure.distance_m)
        .limit(1)
    )


def matches(rules: dict[str, Any], incident: Incident, nearest_site_m: int | None) -> bool:
    if rules.get("category") and rules["category"] != incident.category:
        return False
    if rules.get("min_severity") and severity_rank(incident.severity) < severity_rank(
        str(rules["min_severity"])
    ):
        return False
    limit = rules.get("max_distance_m")
    return limit is None or (nearest_site_m is not None and nearest_site_m <= int(limit))


class ResponsePlanner:
    code = "RESPONSE_PLANNER"
    observes = frozenset({"EXPOSURE_COMPUTED"})
    proposes = ("START_PLAYBOOK",)

    async def observe(self, session: AsyncSession, event: Event) -> list[ProposalIn]:
        incident = await facts.incident(session, event.payload.get("incident_id"))
        if incident is None or incident.status != "ACTIVE":
            return []
        nearest = await _nearest_mission_site_m(session, incident)
        drafts = []
        for playbook in await session.scalars(
            select(Playbook).where(Playbook.is_active).order_by(Playbook.code)
        ):
            if not matches(playbook.trigger_rules, incident, nearest):
                continue
            already = await session.scalar(
                select(PlaybookRun.id)
                .where(
                    PlaybookRun.playbook_id == playbook.id, PlaybookRun.incident_id == incident.id
                )
                .limit(1)
            )
            if already is not None:
                continue  # started by a person already
            evidence = await facts.signal_evidence(session, incident.id)
            evidence.append(
                {
                    "text": f"Mission property exposed at {nearest} m; "
                    f"severity {incident.severity}",
                    "source": "NEXIRA exposure engine",
                }
            )
            drafts.append(
                ProposalIn(
                    agent_code=self.code,
                    proposal_key=f"START_PLAYBOOK:{incident.id}:{playbook.code}",
                    action_type="START_PLAYBOOK",
                    title=f"Run {playbook.code} · {playbook.name}",
                    proposed_action=(
                        f"Start {playbook.code} for {incident.reference}: notify the mission and "
                        "HQ, shelter in place, safety check-in, partner standby."
                    ),
                    action_payload={"playbook_code": playbook.code},
                    incident_id=incident.id,
                    evidence=evidence,
                    alternatives=[
                        {
                            "label": "Monitor only: log for the duty team",
                            "action_type": "POST_INTERNAL_NOTE",
                            "action_payload": {
                                "text": f"{incident.reference}: monitoring; "
                                f"{playbook.code} not started."
                            },
                            "rationale": "If the situation is already contained locally.",
                        }
                    ],
                    risk_if_no_action=(
                        "Staff and citizens in the zone are not warned or accounted for."
                    ),
                    confidence=incident.confidence,
                )
            )
        return drafts
