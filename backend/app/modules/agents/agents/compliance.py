"""Compliance (pilot module 7; DX-07; D-37, docs/plan-pilot-dx.md §4).

Watches incidents; proposes, never acts (level 2, D-12):
- EXPOSURE_COMPUTED (after every incident change, with its final severity) and
  INCIDENT_UPDATED: when an ACTIVE incident's mission has passport-type documents whose
  holders are not travel-ready ("could block evacuation", DX-03) -> START_DOCUMENT_RENEWAL
  for those documents, with "issue emergency travel documents only if needed" as the
  alternative (advice only, level 4).
One open proposal per mission and incident (proposal_key DX:<mission>:<incident>). The
reminder is a fixed English text to staff (no LLM, AGT-09).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event
from app.modules.agents.agents import facts
from app.modules.agents.proposals import ProposalIn
from app.modules.documents import service as documents
from app.modules.people.models import Mission

CODE = "COMPLIANCE"
DOC_LABEL = {
    "PASSPORT": "passport",
    "DIPLOMATIC_PASSPORT": "diplomatic passport",
}


def _short(name: str) -> str:
    """'Hana Takeda' -> 'H. Takeda', as the design's card."""
    first, _, rest = name.partition(" ")
    return f"{first[:1]}. {rest}" if rest else name


def _days(days: int) -> str:
    if days < 0:
        return f"expired {-days} day{'s' if days != -1 else ''} ago"
    return f"{days} day{'s' if days != 1 else ''} left"


class Compliance:
    code = CODE
    observes = frozenset({"EXPOSURE_COMPUTED", "INCIDENT_UPDATED"})
    proposes = ("START_DOCUMENT_RENEWAL", "ADVISE_EMERGENCY_DOCUMENTS")

    async def observe(self, session: AsyncSession, event: Event) -> list[ProposalIn]:
        incident = await facts.incident(session, event.payload.get("incident_id"))
        if incident is None or incident.status != "ACTIVE" or incident.mission_id is None:
            return []
        flagged = await documents.at_risk(session, incident.mission_id, documents.today_utc())
        if not flagged:
            return []
        mission = await session.get_one(Mission, incident.mission_id)
        risk = (await documents.mission_risks(session))[mission.id]
        ids = sorted(str(r.document.id) for r in flagged)
        n = len(flagged)
        people = len({r.document.person_id for r in flagged})
        which = ", ".join(
            f"{_short(r.holder_name)}'s {DOC_LABEL[r.document.doc_type]} ({_days(r.days_left)})"
            for r in flagged
        )
        return [
            ProposalIn(
                agent_code=CODE,
                proposal_key=f"DX:{mission.id}:{incident.id}",
                action_type="START_DOCUMENT_RENEWAL",
                title=(
                    f"{n} {mission.city} travel document{'s' if n != 1 else ''} "
                    "could block an evacuation"
                ),
                proposed_action=(
                    f"Start urgent renewal of {which}; send their holders a reminder (APP and "
                    f"EMAIL, simulated): “{documents.REMINDER}”"
                ),
                action_payload={"document_ids": ids},
                incident_id=incident.id,
                evidence=[
                    *(
                        {
                            "text": f"{r.holder_name} · {DOC_LABEL[r.document.doc_type]} · "
                            f"{_days(r.days_left)}"
                            + (
                                f" (renewal {r.document.renewal_status.lower().replace('_', ' ')})"
                                if r.document.renewal_status != "NONE"
                                else ""
                            ),
                            "source": "document register (simulated)",
                        }
                        for r in flagged
                    ),
                    {
                        "text": "A passport needs at least 180 days left to count as "
                        "travel-ready (the six-month rule)",
                        "source": "Document Expiry (DX-03)",
                    },
                    {
                        "text": f"{mission.code} risk {risk.display_risk}; "
                        f"{incident.reference} active ({incident.severity})",
                        "source": "mission risk",
                    },
                ],
                alternatives=[
                    {
                        "label": "Issue emergency travel documents only if needed",
                        "action_type": "ADVISE_EMERGENCY_DOCUMENTS",
                        "action_payload": {"mission_id": str(mission.id), "document_ids": ids},
                        "rationale": "If an evacuation is ordered first, the consular section "
                        "issues emergency travel documents instead (advice only).",
                    }
                ],
                risk_if_no_action=(
                    f"{people} {'people' if people != 1 else 'person'} could be unable to "
                    "board an evacuation flight."
                ),
                confidence=97,
                is_proactive=True,
            )
        ]
