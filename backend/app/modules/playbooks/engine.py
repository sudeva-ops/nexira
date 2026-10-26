"""Playbook run engine (PB-02, PB-03, PB-04).

A run executes its steps in seq order:
- A step with requires_approval_role and no approval yet pauses the run
  (AWAITING_APPROVAL). service.approve_step() records the approval through
  app/core/approvals.py, and the run continues.
- Every other step is executed: NOTIFY and CHECKIN create a notification
  campaign (sending is Prompt 10); TASK, PARTNER_REQUEST, BRIEFING and
  APPROVAL_GATE write an incident_event only.

Exactly once: each step's effect, its DONE status, its timeline entry and its
audit row are written in one transaction, with the run row locked FOR UPDATE.
A crash before the commit leaves nothing behind and the step runs again on
resume; after the commit the step is DONE and is never run again. Two workers
advancing the same run queue on the lock and the second finds the step done.
Events are published after each commit.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core import audit
from app.core.db import tenant_session
from app.core.events import Event, Publisher
from app.modules.intel import exposure
from app.modules.intel.models import Incident, IncidentEvent
from app.modules.notifications import templates
from app.modules.notifications.service import AudienceError, CampaignIn, create_campaign
from app.modules.playbooks.models import Playbook, PlaybookRun, PlaybookRunStep, PlaybookStep
from app.modules.tenancy.service import Actor

ENGINE = Actor(type="SYSTEM", id="playbook.engine")
FINISHED = ("DONE", "SKIPPED")


class StepError(Exception):
    """A step's configuration cannot be executed; the run is marked FAILED."""


# Errors that mean the step's configuration is wrong. Retrying cannot help, so the
# run is marked FAILED instead of being resumed forever. Anything else (a lost
# connection, a killed worker) rolls back and the step runs again on resume.
CONFIG_ERRORS = (StepError, AudienceError, ValueError, KeyError, TypeError)


@dataclass
class Outcome:
    kind: str  # STEP_DONE, AWAITING_APPROVAL, RUN_COMPLETED, RUN_FAILED
    events: list[Event] = field(default_factory=list)

    @property
    def stop(self) -> bool:
        return self.kind != "STEP_DONE"


def _event(run: PlaybookRun, kind: str, **payload: Any) -> Event:
    return Event(
        type=kind,
        tenant_id=run.tenant_id,
        payload={
            "run_id": str(run.id),
            "incident_id": str(run.incident_id) if run.incident_id else None,
            "status": run.status,
            **payload,
        },
        source="playbook.engine",
    )


def timeline(
    session: AsyncSession,
    run: PlaybookRun,
    event_type: str,
    summary: str,
    data: dict[str, Any],
    actor: Actor = ENGINE,
) -> None:
    if run.incident_id is None:
        return
    session.add(
        IncidentEvent(
            tenant_id=run.tenant_id,
            incident_id=run.incident_id,
            event_type=event_type,
            summary=summary,
            actor_type=actor.type,
            actor_id=actor.id,
            data={"run_id": str(run.id), **data},
        )
    )


async def _briefing(session: AsyncSession, run: PlaybookRun, playbook: Playbook) -> str:
    """BRIEFING: a fixed template filled from data (no LLM in Phase 1)."""
    if run.incident_id is None:
        return f"{playbook.code}: briefing prepared."
    incident = await session.get_one(Incident, run.incident_id)
    counts = await exposure.exposure_counts(session, run.incident_id)
    done = await session.scalar(
        select(func.count())
        .select_from(PlaybookRunStep)
        .where(PlaybookRunStep.run_id == run.id, PlaybookRunStep.status == "DONE")
    )
    return (
        f"Situation report: {incident.reference} · {incident.title} · severity "
        f"{incident.severity}, confidence {incident.confidence}%. Exposure: {counts.summary()}. "
        f"{playbook.code}: {done} steps completed."
    )


async def _execute(
    session: AsyncSession, run: PlaybookRun, playbook: Playbook, step: PlaybookStep
) -> tuple[str, dict[str, Any]]:
    """Run one step's action; return (timeline summary, result)."""
    config = step.action_config
    kind = step.action_type
    if kind in ("NOTIFY", "CHECKIN"):
        if run.incident_id is None:
            raise StepError(f"{kind} needs an incident")
        message = str(config.get("message") or step.name)
        translations: dict[str, str] = {}
        if config.get("message_template"):
            # MN-04: the text comes from the incident mission's template (D-31).
            incident = await session.get_one(Incident, run.incident_id)
            resolved = await templates.resolve(
                session, str(config["message_template"]), incident.mission_id
            )
            if resolved is not None:
                message = resolved.texts["en"]
                translations = {k: v for k, v in resolved.texts.items() if k != "en"}
        campaign, recipients = await create_campaign(
            session,
            incident_id=run.incident_id,
            campaign=CampaignIn(
                campaign_type="CHECKIN"
                if kind == "CHECKIN"
                else config.get("campaign_type", "ALERT"),
                message=message,
                translations=translations,
                channels=list(config.get("channels") or ["APP"]),
                audience=dict(config.get("audience") or {}),
                escalate_after_s=int(config.get("escalate_after_s", 600)),
            ),
            created_by_type="PLAYBOOK",
            created_by=str(run.id),
            actor=ENGINE,
        )
        summary = f"{step.name}: {campaign.reference} · {recipients} recipients · " + " · ".join(
            campaign.channels
        )
        return summary, {
            "campaign_id": str(campaign.id),
            "reference": campaign.reference,
            "recipients": recipients,
            "channels": campaign.channels,
        }
    if kind == "TASK":
        summary = str(config.get("summary") or step.name)
        result: dict[str, Any] = {"summary": summary}
        if config.get("notify_user_roles"):
            result["notified_roles"] = list(config["notify_user_roles"])
        return f"{step.name}: {summary}", result
    if kind == "PARTNER_REQUEST":
        partner = str(config.get("partner") or "Assistance partner")
        return (
            f"{step.name}: {partner} placed on standby (simulated)",
            {"partner": partner, "service": config.get("service"), "simulated": True},
        )
    if kind == "BRIEFING":
        report = await _briefing(session, run, playbook)
        return f"{step.name}: {report}", {"recipient": config.get("recipient"), "report": report}
    if kind == "APPROVAL_GATE":
        return f"{step.name}: approved", {}
    raise StepError(f"unknown action type {kind}")


async def advance_one(session: AsyncSession, run_id: uuid.UUID) -> Outcome | None:
    """Take the run one step further, in the caller's transaction. None if the run
    is not RUNNING (finished, paused for approval, or unknown)."""
    run = await session.scalar(
        select(PlaybookRun).where(PlaybookRun.id == run_id).with_for_update()
    )
    if run is None or run.status != "RUNNING":
        return None
    playbook = await session.get_one(Playbook, run.playbook_id)
    rows = (
        await session.execute(
            select(PlaybookRunStep, PlaybookStep)
            .join(PlaybookStep, PlaybookStep.id == PlaybookRunStep.step_id)
            .where(PlaybookRunStep.run_id == run.id)
            .order_by(PlaybookStep.seq)
        )
    ).all()
    pending = [(rs, st) for rs, st in rows if rs.status not in FINISHED]
    now = datetime.now(UTC)

    if not pending:
        run.status = "COMPLETED"
        run.completed_at = now
        timeline(
            session, run, "PLAYBOOK_STEP", f"{playbook.code} completed.", {"status": run.status}
        )
        await audit.write(
            session,
            actor_type=ENGINE.type,
            actor_id=ENGINE.id,
            action="PLAYBOOK.COMPLETE",
            entity_type="playbook_run",
            entity_id=str(run.id),
            details={"playbook": playbook.code, "steps": len(rows)},
        )
        await session.flush()
        return Outcome("RUN_COMPLETED", [_event(run, "PLAYBOOK_RUN_UPDATED")])

    run_step, step = pending[0]
    if step.requires_approval_role and run_step.approved_by is None:
        run_step.status = "AWAITING_APPROVAL"
        run.status = "AWAITING_APPROVAL"
        timeline(
            session,
            run,
            "PLAYBOOK_STEP",
            f"Step {step.seq} · {step.name}: awaiting approval by "
            f"{step.requires_approval_role.replace('|', ' or ')}.",
            {"step_id": str(step.id), "seq": step.seq, "status": run_step.status},
        )
        await audit.write(
            session,
            actor_type=ENGINE.type,
            actor_id=ENGINE.id,
            action="PLAYBOOK.STEP_AWAIT_APPROVAL",
            entity_type="playbook_run",
            entity_id=str(run.id),
            details={"seq": step.seq, "required_role": step.requires_approval_role},
        )
        await session.flush()
        return Outcome(
            "AWAITING_APPROVAL",
            [
                _event(
                    run,
                    "PLAYBOOK_STEP",
                    step_id=str(step.id),
                    seq=step.seq,
                    step_status=run_step.status,
                )
            ],
        )

    run_step.started_at = now
    try:
        summary, result = await _execute(session, run, playbook, step)
    except CONFIG_ERRORS as e:
        run_step.status = "FAILED"
        run_step.completed_at = datetime.now(UTC)
        run_step.result = {"error": str(e)}
        run.status = "FAILED"
        timeline(session, run, "PLAYBOOK_STEP", f"Step {step.seq} · {step.name} failed: {e}", {})
        await audit.write(
            session,
            actor_type=ENGINE.type,
            actor_id=ENGINE.id,
            action="PLAYBOOK.STEP_FAIL",
            entity_type="playbook_run",
            entity_id=str(run.id),
            details={"seq": step.seq, "error": str(e)},
        )
        await session.flush()
        return Outcome("RUN_FAILED", [_event(run, "PLAYBOOK_RUN_UPDATED")])

    if run_step.approved_by is not None:
        result = {**result, "approved_by": str(run_step.approved_by)}
    run_step.status = "DONE"
    run_step.completed_at = datetime.now(UTC)
    run_step.result = result
    timeline(
        session,
        run,
        "PLAYBOOK_STEP",
        f"Step {step.seq} · {summary}",
        {"step_id": str(step.id), "seq": step.seq, "status": "DONE", **result},
    )
    await audit.write(
        session,
        actor_type=ENGINE.type,
        actor_id=ENGINE.id,
        action="PLAYBOOK.STEP_DONE",
        entity_type="playbook_run",
        entity_id=str(run.id),
        details={"seq": step.seq, "action_type": step.action_type, **result},
    )
    await session.flush()
    events = [_event(run, "PLAYBOOK_STEP", step_id=str(step.id), seq=step.seq, step_status="DONE")]
    if "campaign_id" in result:
        # The deliveries are queued in this transaction (outbox); the dispatcher sends them.
        events.append(
            Event(
                type="CAMPAIGN_QUEUED",
                tenant_id=run.tenant_id,
                payload={
                    "campaign_id": result["campaign_id"],
                    "reference": result["reference"],
                    "incident_id": str(run.incident_id),
                },
                source="playbook.engine",
            )
        )
    return Outcome("STEP_DONE", events)


Sleep = Callable[[float], Awaitable[None]]


async def advance(
    engine: AsyncEngine,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    publisher: Publisher,
    *,
    step_delay_s: float = 0.0,
    sleep: Sleep = asyncio.sleep,
) -> str | None:
    """Run steps until the run completes, fails or waits for an approval. Safe to
    call again at any time (resume after a restart, a duplicate event). Returns the
    last outcome kind, or None if there was nothing to do."""
    last: str | None = None
    while True:
        async with tenant_session(tenant_id, engine) as session:
            outcome = await advance_one(session, run_id)
            await session.commit()
        if outcome is None:
            return last
        for event in outcome.events:
            await publisher.publish(event)
        last = outcome.kind
        if outcome.stop:
            return last
        if step_delay_s > 0:
            await sleep(step_delay_s)  # demo pacing, so the UI shows steps progress


async def resumable_runs(engine: AsyncEngine, tenant_id: uuid.UUID) -> list[uuid.UUID]:
    """RUNNING runs, to resume after a worker restart (plan G-01: tenants from config)."""
    async with tenant_session(tenant_id, engine) as session:
        rows = await session.scalars(
            select(PlaybookRun.id)
            .where(PlaybookRun.status == "RUNNING")
            .order_by(PlaybookRun.started_at)
        )
        return list(rows)
