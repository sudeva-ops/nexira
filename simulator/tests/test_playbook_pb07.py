"""PB-07 on the full seed: scene 3 of NBO-CIVIL-UNREST (decisions.md §7, Prompt 9).

Scenes 1-2 run through the worker handlers first, so the incident has its exposure
and mission. The run then goes through the same services and engine the API and
worker use, as the seeded demo users.
"""

import re
import uuid
from typing import Any

import pytest
from app.core.approvals import ApprovalDeniedError
from app.core.db import create_engine, tenant_session
from app.modules.intel.models import IncidentEvent
from app.modules.notifications.models import NotificationCampaign
from app.modules.partners.models import Partner, PartnerRequest
from app.modules.playbooks import engine as playbook_engine
from app.modules.playbooks import service
from app.modules.playbooks.models import Playbook, PlaybookRun, PlaybookRunStep, PlaybookStep
from app.modules.tenancy.service import Actor
from app.tests.conftest import DbUrls
from app.tests.fakes import ListPublisher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.scene_helpers import seeded_incident, user


async def steps(engine: AsyncEngine, tenant_id: uuid.UUID, run_id: uuid.UUID) -> list[Any]:
    async with tenant_session(tenant_id, engine) as session:
        rows = await session.execute(
            select(PlaybookStep.seq, PlaybookRunStep.status, PlaybookRunStep.result)
            .join(PlaybookStep, PlaybookStep.id == PlaybookRunStep.step_id)
            .where(PlaybookRunStep.run_id == run_id)
            .order_by(PlaybookStep.seq)
        )
        return list(rows)


async def approve(
    engine: AsyncEngine, tenant_id: uuid.UUID, username: str, run_id: uuid.UUID
) -> None:
    async with tenant_session(tenant_id, engine) as session:
        step7 = await session.scalar(
            select(PlaybookStep.id)
            .join(Playbook, Playbook.id == PlaybookStep.playbook_id)
            .where(Playbook.code == "PB-07", PlaybookStep.seq == 7)
        )
        assert step7 is not None
        await service.approve_step(session, await user(session, username), run_id, step7)
        await session.commit()


async def test_pb07_runs_to_step_7_waits_for_the_nairobi_hom_and_completes(
    db: DbUrls, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    publisher = ListPublisher()
    try:
        incident_id = await seeded_incident(db, engine, tenant_id)
        async with tenant_session(tenant_id, engine) as session:
            duty = await user(session, "duty.officer")
            assert await service.may_start(session, duty, incident_id)
            run = await service.start_run(
                session,
                playbook_code="PB-07",
                incident_id=incident_id,
                actor=Actor(type="USER", id=str(duty.id)),
                started_by=duty.id,
            )
            await session.commit()
            run_id = run.id

        # A worker dies during step 5 (the check-in): its effects roll back.
        real_execute = playbook_engine._execute
        crashed = False

        async def crash_in_step_5(
            session: AsyncSession, r: PlaybookRun, p: Playbook, step: PlaybookStep
        ) -> tuple[str, dict[str, Any]]:
            nonlocal crashed
            result = await real_execute(session, r, p, step)
            if step.seq == 5 and not crashed:
                crashed = True
                raise RuntimeError("worker killed")
            return result

        monkeypatch.setattr(playbook_engine, "_execute", crash_in_step_5)
        with pytest.raises(RuntimeError):
            await playbook_engine.advance(engine, tenant_id, run_id, publisher)
        assert [s.status for s in await steps(engine, tenant_id, run_id)][:5] == [
            "DONE",
            "DONE",
            "DONE",
            "DONE",
            "PENDING",
        ]
        # Restart: the run resumes where it stopped.
        assert await playbook_engine.resumable_runs(engine, tenant_id) == [run_id]
        assert await playbook_engine.advance(engine, tenant_id, run_id, publisher) == (
            "AWAITING_APPROVAL"
        )

        state = await steps(engine, tenant_id, run_id)
        assert [s.status for s in state] == ["DONE"] * 6 + ["AWAITING_APPROVAL", "PENDING"]
        recipients = {s.seq: s.result.get("recipients") for s in state if "recipients" in s.result}
        assert recipients == {2: 2, 4: 17, 5: 229}  # plan G-14
        # AS-05: step 6 asked Kestrel to stand by, tracked (plan-pilot-ast §5).
        assert state[5].result["request_reference"] == "REQ-0551"

        # PB-03: the Duty Officer and the Cairo Head of Mission are refused (D-05).
        for username in ("duty.officer", "hom.cairo"):
            with pytest.raises(ApprovalDeniedError) as denied:
                await approve(engine, tenant_id, username, run_id)
            assert denied.value.verdict.status_code == 403, username

        await approve(engine, tenant_id, "hom.nairobi", run_id)
        assert await playbook_engine.advance(engine, tenant_id, run_id, publisher) == (
            "RUN_COMPLETED"
        )

        async with tenant_session(tenant_id, engine) as session:
            run_row = await session.get_one(PlaybookRun, run_id)
            campaigns = list(
                await session.execute(
                    select(
                        NotificationCampaign.reference, NotificationCampaign.campaign_type
                    ).order_by(NotificationCampaign.reference)
                )
            )
            standby = list(
                await session.execute(
                    select(
                        PartnerRequest.reference,
                        Partner.code,
                        PartnerRequest.service,
                        PartnerRequest.incident_id,
                        PartnerRequest.created_by_type,
                        PartnerRequest.created_by,
                        PartnerRequest.status,
                    ).join(Partner, Partner.id == PartnerRequest.partner_id)
                )
            )
            briefing = await session.scalar(
                select(IncidentEvent.summary).where(
                    IncidentEvent.event_type == "PLAYBOOK_STEP",
                    IncidentEvent.summary.like("Step 8 ·%"),
                )
            )
    finally:
        await engine.dispose()

    assert run_row.status == "COMPLETED"
    # One standby request despite the crash in step 5, made by the run (D-16, AS-05).
    assert [tuple(r) for r in standby] == [
        ("REQ-0551", "KES", "MEDICAL", incident_id, "PLAYBOOK", str(run_id), "REQUESTED")
    ]
    # Four campaigns, no gaps or duplicates despite the crash (D-18 numbering).
    assert [c.campaign_type for c in campaigns] == ["ALERT", "ALERT", "CHECKIN", "ALERT"]
    assert all(re.fullmatch(r"NTF-\d{4}", c.reference) for c in campaigns)
    assert [c.reference for c in campaigns] == ["NTF-3101", "NTF-3102", "NTF-3103", "NTF-3104"]
    # Step 8 (BRIEFING) writes an incident event only: no fifth campaign.
    assert briefing is not None
    assert "Situation report" in briefing
    assert "229 people" in briefing
