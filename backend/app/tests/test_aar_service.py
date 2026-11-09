"""After-Action Review service (AAR-02..04; D-47; docs/plan-pilot-aar.md §2-§4): the timeline
from every source with no name copied, NOTE left out; each metric and its target, "—" without a
figure; each drafting rule firing on its evidence and silent without it. Against real PostgreSQL,
as nexira_api, on a hand-built record (the seeded Nairobi run is in the simulator's tests)."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import tenant_session
from app.modules.aar import rules, service
from app.modules.aar.schemas import MetricOut
from app.tests.auth_helpers import Idp

T0 = datetime(2026, 11, 9, 5, 53, 58, tzinfo=UTC)
NOW = T0 + timedelta(hours=1)
PT = "'SRID=4326;POINT(36.8245 -1.2838)'"
NAMES = ("Hana Takeda", "Peter Mwangi", "Ama Mensah", "Layla Haddad", "Daniel Mercer")


async def _sql(session: AsyncSession, sql: str, **params: Any) -> Any:
    return await session.scalar(text(sql), params)


async def _event(
    session: AsyncSession, incident: uuid.UUID, kind: str, summary: str, at: datetime, **data: Any
) -> None:
    await session.execute(
        text(
            "INSERT INTO incident_event (tenant_id, incident_id, event_type, summary, actor_type, "
            "occurred_at, data) VALUES (current_tenant_id(), :i, :k, :s, 'SYSTEM', :at, "
            "CAST(:d AS jsonb))"
        ),
        {"i": incident, "k": kind, "s": summary, "at": at, "d": json.dumps(data)},
    )


async def _person(session: AsyncSession, mission: uuid.UUID, kind: str, name: str) -> uuid.UUID:
    person: uuid.UUID = await _sql(
        session,
        "INSERT INTO person (tenant_id, mission_id, person_type, full_name) "
        "VALUES (current_tenant_id(), :m, :k, :n) RETURNING id",
        m=mission,
        k=kind,
        n=name,
    )
    return person


async def _world(idp: Idp, *, quiet: bool = False) -> uuid.UUID:
    """A Nairobi incident whose record shows every rule's evidence, or (quiet) none of it."""
    async with tenant_session(idp.tenant_id, idp.engine) as s:
        mission = await _sql(
            s,
            "INSERT INTO mission (tenant_id, code, city, country_code, location) VALUES "
            f"(current_tenant_id(), 'NBO', 'Nairobi', 'KE', {PT}) RETURNING id",
        )
        source = await _sql(
            s,
            "INSERT INTO intel_source (tenant_id, code, name) "
            "VALUES (current_tenant_id(), 'DATAMINR', 'Dataminr') RETURNING id",
        )
        signal = await _sql(
            s,
            "INSERT INTO raw_signal (tenant_id, source_id, external_id, title, occurred_at, "
            "received_at) VALUES (current_tenant_id(), :src, 'x-1', 'Protest', :at, :at) "
            "RETURNING id",
            src=source,
            at=T0,
        )
        incident: uuid.UUID = await _sql(
            s,
            "INSERT INTO incident (tenant_id, reference, title, category, severity, "
            "signal_severity, status, mission_id, location, opened_at) VALUES "
            "(current_tenant_id(), 'INC-2026-1042', 'Civil unrest', 'CIVIL_UNREST', 'CRITICAL', "
            f"'HIGH', 'MONITORING', :m, {PT}, :at) RETURNING id",
            m=mission,
            at=T0 + timedelta(seconds=2),
        )
        await s.execute(
            text(
                "INSERT INTO incident_signal (tenant_id, incident_id, signal_id) "
                "VALUES (current_tenant_id(), :i, :s)"
            ),
            {"i": incident, "s": signal},
        )
        await _event(
            s, incident, "SIGNAL", "Opened from Dataminr: High → HIGH.", T0 + timedelta(seconds=2)
        )
        if quiet:
            await s.commit()
            return incident
        hana = await _person(s, mission, "DIPLOMAT", "Hana Takeda")
        peter = await _person(s, mission, "LOCAL_STAFF", "Peter Mwangi")
        ama = await _person(s, mission, "CITIZEN", "Ama Mensah")
        for person, confidence in ((hana, 72), (peter, 95), (ama, 40)):
            await s.execute(
                text(
                    "INSERT INTO incident_exposure (tenant_id, incident_id, subject_type, "
                    "subject_id, confidence) VALUES (current_tenant_id(), :i, 'PERSON', :p, :c)"
                ),
                {"i": incident, "p": person, "c": confidence},
            )
        await _event(s, incident, "EXPOSURE", "Exposure: 3 people.", T0 + timedelta(seconds=2.03))
        # PB-07 with a gate the Head of Mission approves 6m 40s after it was raised.
        playbook = await _sql(
            s,
            "INSERT INTO playbook (tenant_id, code, name, category) VALUES "
            "(current_tenant_id(), 'PB-07', 'Civil unrest near mission', 'Security') RETURNING id",
        )
        step = await _sql(
            s,
            "INSERT INTO playbook_step (tenant_id, playbook_id, seq, name, action_type, "
            "requires_approval_role) VALUES (current_tenant_id(), :p, 7, "
            "'Approve evacuation route B', 'APPROVAL_GATE', 'HEAD_OF_MISSION') RETURNING id",
            p=playbook,
        )
        run = await _sql(
            s,
            "INSERT INTO playbook_run (tenant_id, playbook_id, incident_id, status, started_at, "
            "completed_at) VALUES (current_tenant_id(), :p, :i, 'COMPLETED', :a, :b) RETURNING id",
            p=playbook,
            i=incident,
            a=T0 + timedelta(seconds=10),
            b=T0 + timedelta(seconds=430),
        )
        gate = {"step_id": str(step), "run_id": str(run), "seq": 7}
        await _event(
            s,
            incident,
            "PLAYBOOK_STEP",
            "Step 7 · Approve evacuation route B: awaiting approval by HEAD_OF_MISSION.",
            T0 + timedelta(seconds=20),
            status="AWAITING_APPROVAL",
            **gate,
        )
        await _event(
            s,
            incident,
            "DECISION",
            "Step 7 · Approve evacuation route B: approved by Layla Haddad (HEAD_OF_MISSION).",
            T0 + timedelta(seconds=420),
            decision="APPROVE",
            **gate,
        )
        # The check-in, sent 2m 30s after the first signal: over the 2-minute target.
        campaign = await _sql(
            s,
            "INSERT INTO notification_campaign (tenant_id, reference, campaign_type, message, "
            "channels, created_by_type, incident_id, sent_at) VALUES (current_tenant_id(), "
            "'NTF-3103', 'CHECKIN', 'Are you safe?', '{APP}', 'USER', :i, :at) RETURNING id",
            i=incident,
            at=T0 + timedelta(seconds=150),
        )
        for person in (hana, peter, ama):
            await s.execute(
                text(
                    "INSERT INTO notification_delivery (tenant_id, campaign_id, person_id, "
                    "channel) VALUES (current_tenant_id(), :c, :p, 'APP')"
                ),
                {"c": campaign, "p": person},
            )
        await s.execute(
            text(
                "INSERT INTO checkin_response (tenant_id, campaign_id, person_id, status, "
                "responded_at) VALUES (current_tenant_id(), :c, :p, 'NEED_HELP', :at)"
            ),
            {"c": campaign, "p": peter, "at": T0 + timedelta(seconds=172)},
        )
        await _event(
            s,
            incident,
            "CHECKIN",
            "Peter Mwangi needs help (NTF-3103, APP).",
            T0 + timedelta(seconds=172),
            status="NEED_HELP",
            person_id=str(peter),
            campaign_id=str(campaign),
        )
        await _event(
            s,
            incident,
            "ESCALATION",
            "Hana Takeda has not answered NTF-3103: escalated after 28 s.",
            T0 + timedelta(seconds=180),
            scope="person",
            person_id=str(hana),
            campaign_id=str(campaign),
        )
        await _event(
            s,
            incident,
            "ESCALATION",
            "1 citizens have not answered NTF-3103: escalated to the consular team after 28 s.",
            T0 + timedelta(seconds=180),
            scope="citizens",
            count=1,
            campaign_id=str(campaign),
        )
        await _event(
            s,
            incident,
            "NOTE",
            "Called Hana Takeda's spouse.",
            T0 + timedelta(seconds=200),
        )
        await _event(
            s,
            incident,
            "FLEET",
            "VH-04 entered the impact zone of INC-2026-1042 · Waiyaki Way.",
            T0 + timedelta(seconds=300),
            code="VH-04",
            crossing="entered",
        )
        await _event(
            s,
            incident,
            "SITE",
            "Embassy Nairobi · Gate 2 · badge reader: FAULT (Fault · manual guard).",
            T0 + timedelta(seconds=310),
            sensor="G2-READER",
            status="FAULT",
        )
        await _event(
            s,
            incident,
            "SUPPLY",
            "Nairobi · Rift Valley Fuels: DELAYED (Fuel delivery postponed 24 h).",
            T0 + timedelta(seconds=320),
            supplier="SUP-121",
            status="DELAYED",
        )
        await _event(
            s,
            incident,
            "SUPPLY",
            "Nairobi · Kilima Catering: NORMAL.",
            T0 + timedelta(seconds=321),
            supplier="SUP-130",
            status="NORMAL",
        )
        # After the window (the review's start): not on the timeline, no evidence.
        await _event(
            s,
            incident,
            "FLEET",
            "VH-09 entered the impact zone of INC-2026-1042 · CBD.",
            NOW + timedelta(minutes=5),
            code="VH-09",
            crossing="entered",
        )
        await s.commit()
        return incident


async def _review(idp: Idp, incident: uuid.UUID) -> tuple[Any, list[MetricOut], list[Any]]:
    async with tenant_session(idp.tenant_id, idp.engine) as s:
        found = await service.incident(s, incident)
        assert found is not None
        return (
            await service.timeline(s, found, NOW),
            await service.metrics(s, found, NOW),
            await rules.draft(s, found, NOW),
        )


async def test_the_timeline_has_every_source_and_no_name(idp: Idp) -> None:
    lines, _, drafts = await _review(idp, await _world(idp))
    texts = [line.text for line in lines]
    assert [line.at for line in lines] == sorted(line.at for line in lines)
    assert "Check-in NTF-3103: a person needs help." in texts
    assert "Check-in NTF-3103: a staff member did not answer and was escalated." in texts
    assert "Check-in NTF-3103: 1 citizens did not answer; escalated to the consular team." in texts
    assert "Step 7 · Approve evacuation route B: approved by the Head of Mission." in texts
    assert "VH-04 entered the impact zone of INC-2026-1042 · Waiyaki Way." in texts
    assert "NTF-3103 sent: checkin, 3 recipients." in texts  # not on a playbook step
    assert not [t for t in texts if "VH-09" in t]  # after the review started
    assert not [t for t in texts if "spouse" in t]  # NOTE is free text: left out
    dumped = repr(lines) + repr(drafts)
    assert not [name for name in NAMES if name in dumped]


async def test_the_metrics_and_their_targets(idp: Idp) -> None:
    _, metrics, _ = await _review(idp, await _world(idp))
    by_key = {m.key: m for m in metrics}
    assert (by_key["detection_to_incident"].value, by_key["detection_to_incident"].met) == (
        2.0,
        True,
    )
    assert (by_key["incident_to_exposure"].value, by_key["incident_to_exposure"].met) == (
        0.03,
        True,
    )
    notified = by_key["detection_to_notification"]
    assert (notified.value, notified.target, notified.met) == (150.0, 120.0, False)
    slowest = by_key["decision_slowest"]
    assert (slowest.value, slowest.met) == (400.0, False)
    assert slowest.detail == "Step 7 · Approve evacuation route B · Head of Mission"
    assert by_key["decision_median"].detail == "1 decision by people"
    accounted = by_key["personnel_accounted"]
    assert (accounted.value, accounted.unit) == (50, "%")  # 1 of the 2 staff answered
    assert accounted.detail == "1 of 2 · NTF-3103 · in 22 s"
    assert by_key["playbook"].value == 420.0


async def test_every_rule_fires_on_its_evidence(idp: Idp) -> None:
    _, _, drafts = await _review(idp, await _world(idp))
    found = {d.rule_code: d for d in drafts}
    assert list(found) == [
        "CHECKIN_SILENT",
        "LOW_CONFIDENCE",
        "NOTIFY_LATE",
        "GATE_WAIT",
        "FLEET_ZONE",
        "SITE_FAULT",
        "SUPPLY_IMPACT",
    ]
    assert found["CHECKIN_SILENT"].finding == (
        "1 staff member did not answer NTF-3103 and was escalated."
    )
    assert found["LOW_CONFIDENCE"].evidence == {"low": 1, "exposed": 2, "lowest": 72, "floor": 80}
    assert found["NOTIFY_LATE"].finding == (
        "The first notification went out 2m 30s after the first signal (target 2m 00s)."
    )
    assert found["GATE_WAIT"].finding == (
        "1 decision waited longer than 5m 00s; the longest, Step 7 · Approve evacuation route B, "
        "waited 6m 40s for the Head of Mission."
    )
    assert found["GATE_WAIT"].owner_team == "MISSION_MANAGEMENT"
    assert found["FLEET_ZONE"].evidence == {"vehicles": ["VH-04"]}  # not VH-09: after the window
    assert found["SITE_FAULT"].finding == (
        "1 site device failed or went offline: Embassy Nairobi · Gate 2 · badge reader."
    )
    assert found["SUPPLY_IMPACT"].evidence == {"suppliers": ["SUP-121"]}  # not the NORMAL one
    assert {d.priority for d in drafts} <= {"HIGH", "MEDIUM", "LOW"}
    assert rules.LABEL == "Drafted from the platform record by rules · reviewed by people"


async def test_a_quiet_record_drafts_nothing(idp: Idp) -> None:
    lines, metrics, drafts = await _review(idp, await _world(idp, quiet=True))
    assert drafts == []
    assert [line.text for line in lines] == [
        "First signal received.",  # 2 s before the incident opened
        "Opened from Dataminr: High → HIGH.",
    ]
    by_key = {m.key: m for m in metrics}
    for key in (
        "incident_to_exposure",
        "detection_to_notification",
        "decision_median",
        "decision_slowest",
        "personnel_accounted",
        "playbook",
    ):
        assert (by_key[key].value, by_key[key].met) == (None, None), key
    assert by_key["detection_to_incident"].value == 2.0


async def test_the_window_ends_when_the_incident_closed(idp: Idp) -> None:
    incident = await _world(idp)
    async with tenant_session(idp.tenant_id, idp.engine) as s:
        await s.execute(
            text("UPDATE incident SET status = 'CLOSED', closed_at = :at WHERE id = :i"),
            {"at": T0 + timedelta(seconds=305), "i": incident},
        )
        await s.commit()
    lines, _, drafts = await _review(idp, incident)
    assert lines[-1].at <= T0 + timedelta(seconds=305)
    codes = [d.rule_code for d in drafts]
    assert "FLEET_ZONE" in codes  # at 300 s, inside
    assert "SITE_FAULT" not in codes  # at 310 s, after the incident closed


def test_durations() -> None:
    assert [service.duration(s) for s in (None, 0.4, 45, 105.09, 3900)] == [
        "—",
        "0 s",
        "45 s",
        "1m 45s",
        "1h 05m",
    ]
