"""Channel adapters (🔒 D-29), the delivery outbox and the dispatcher (CHK-04, Prompt 10)."""

import asyncio
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.db import tenant_session
from app.modules.audit.models import AuditLog
from app.modules.intel.models import Incident
from app.modules.notifications import service
from app.modules.notifications.channels import (
    Recipient,
    Sent,
    SimulatedChannelAdapter,
    UnsupportedAdapterError,
    adapter_for,
)
from app.modules.notifications.models import NotificationCampaign, NotificationDelivery
from app.modules.notifications.service import (
    CampaignIn,
    create_campaign,
    dispatch,
    refresh_receipts,
)
from app.modules.people.service import PersonIn, ensure_mission, load_persons
from app.modules.tenancy.service import SYSTEM
from app.tests.conftest import DbUrls
from app.tests.intel_helpers import ingest, intel_tenant, signal

T0 = datetime(2026, 10, 20, 6, 0, tzinfo=UTC)


# --- the adapter --------------------------------------------------------------------------


def test_only_the_simulated_adapter_exists() -> None:
    assert isinstance(adapter_for("SMS"), SimulatedChannelAdapter)
    with pytest.raises(UnsupportedAdapterError):
        adapter_for("SMS", "twilio")
    with pytest.raises(UnsupportedAdapterError):
        adapter_for("PIGEON")
    with pytest.raises(ValidationError):
        Settings.model_validate({"database_url": "x", "channel_adapter": "twilio"})


async def test_simulated_sends_are_idempotent_per_key() -> None:
    adapter = SimulatedChannelAdapter()
    who = Recipient(uuid.uuid4(), "en")
    first = await adapter.send(who, "SMS", "hello", idempotency_key="42", now=T0)
    again = await adapter.send(who, "SMS", "hello", idempotency_key="42", now=T0)
    other = await adapter.send(who, "SMS", "hello", idempotency_key="43", now=T0)
    assert first.provider_ref == again.provider_ref != other.provider_ref
    assert first.provider_ref.startswith("SIM-SMS-")


def test_simulated_receipts_move_on_over_time() -> None:
    adapter = SimulatedChannelAdapter()
    at = [adapter.receipt("ref", T0, T0 + timedelta(seconds=s)) for s in (0, 2, 5.9, 6)]
    assert at == ["SENT", "DELIVERED", "DELIVERED", "READ"]


# --- outbox and dispatcher --------------------------------------------------------------------


@dataclass
class World:
    tenant: uuid.UUID
    incident_id: uuid.UUID
    people: list[uuid.UUID]


@pytest.fixture
async def world(db: DbUrls, api_engine: AsyncEngine) -> World:
    tenant = await intel_tenant(db, api_engine)
    fused = (await ingest(api_engine, tenant, signal("DATAMINR", "High"))).fused
    assert fused is not None
    people = [uuid.uuid4() for _ in range(3)]
    async with tenant_session(tenant, api_engine) as session:
        nbo = await ensure_mission(
            session, code="NBO", city="Nairobi", country_code="KE", lat=-1.28, lon=36.82
        )
        await load_persons(
            session,
            [
                PersonIn(
                    people[0],
                    nbo,
                    "DIPLOMAT",
                    "Ana",
                    role_title="Head of Mission",
                    preferred_lang="fr",
                ),
                PersonIn(people[1], nbo, "DIPLOMAT", "Ben", role_title="Head of Mission"),
                PersonIn(people[2], nbo, "LOCAL_STAFF", "Cy", role_title="Driver"),
            ],
        )
        incident = await session.get_one(Incident, fused.incident_id)
        incident.mission_id = nbo
        await session.commit()
    return World(tenant, fused.incident_id, people)


HOMS = CampaignIn(
    campaign_type="ALERT",
    message="Alert",
    channels=["APP", "SMS"],
    audience={"mission": "incident", "role_titles": ["Head of Mission"]},
    translations={"fr": "Alerte"},
)


async def campaign(engine: AsyncEngine, w: World, spec: CampaignIn = HOMS) -> NotificationCampaign:
    async with tenant_session(w.tenant, engine) as session:
        row, recipients = await create_campaign(
            session,
            incident_id=w.incident_id,
            campaign=spec,
            created_by_type="USER",
            created_by="test",
            actor=SYSTEM,
        )
        await session.commit()
    assert recipients == 2
    return row


async def deliveries(engine: AsyncEngine, w: World) -> list[NotificationDelivery]:
    async with tenant_session(w.tenant, engine) as session:
        return list(
            await session.scalars(select(NotificationDelivery).order_by(NotificationDelivery.id))
        )


async def run_dispatch(engine: AsyncEngine, w: World, now: datetime = T0) -> service.Dispatched:
    async with tenant_session(w.tenant, engine) as session:
        result = await dispatch(session, now)
        await session.commit()
    return result


async def test_a_campaign_queues_one_delivery_per_recipient_and_channel(
    api_engine: AsyncEngine, world: World
) -> None:
    row = await campaign(api_engine, world)
    assert row.status == "SENDING"
    queued = await deliveries(api_engine, world)
    assert Counter((d.channel, d.status) for d in queued) == {
        ("APP", "QUEUED"): 2,
        ("SMS", "QUEUED"): 2,
    }
    async with tenant_session(world.tenant, api_engine) as session:
        actions = list(await session.scalars(select(AuditLog.action).order_by(AuditLog.chain_seq)))
    assert actions[-2:] == ["CAMPAIGN.CREATE", "CAMPAIGN.SEND"]


async def test_dispatch_sends_each_delivery_once_in_the_person_s_language(
    api_engine: AsyncEngine, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = await campaign(api_engine, world)
    texts: list[tuple[uuid.UUID, str, str]] = []
    real = SimulatedChannelAdapter()

    class Recording:
        name = "simulated"

        async def send(
            self, recipient: Recipient, channel: str, text: str, idempotency_key: str, now: datetime
        ) -> Sent:
            texts.append((recipient.person_id, channel, text))
            return await real.send(recipient, channel, text, idempotency_key, now)

        def receipt(self, provider_ref: str, sent_at: datetime, now: datetime) -> str:
            return real.receipt(provider_ref, sent_at, now)

    monkeypatch.setattr(service, "adapter_for", lambda channel, configured="simulated": Recording())
    result = await run_dispatch(api_engine, world)
    assert result.sent == {"APP": 2, "SMS": 2}
    assert [c.id for c in result.completed] == [row.id]
    assert (await run_dispatch(api_engine, world)).sent == {}  # nothing left
    assert len(texts) == 4
    by_person = {p: t for p, _, t in texts}
    assert by_person[world.people[0]] == "Alerte"  # preferred_lang fr
    assert by_person[world.people[1]] == "Alert"
    sent = await deliveries(api_engine, world)
    assert {d.status for d in sent} == {"SENT"}
    assert all(d.provider_ref and d.provider_ref.startswith("SIM-") for d in sent)
    async with tenant_session(world.tenant, api_engine) as session:
        stored = await session.get_one(NotificationCampaign, row.id)
        dispatched = await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "CAMPAIGN.DISPATCHED")
        )
    assert (stored.status, stored.sent_at) == ("SENT", T0)
    assert dispatched == 1


async def test_two_dispatchers_never_send_the_same_delivery(
    api_engine: AsyncEngine, world: World
) -> None:
    await campaign(api_engine, world)
    results = await asyncio.gather(*(run_dispatch(api_engine, world) for _ in range(3)))
    assert sum(sum(r.sent.values()) for r in results) == 4


async def test_a_crash_before_commit_resends_with_the_same_key(
    api_engine: AsyncEngine, world: World
) -> None:
    await campaign(api_engine, world)
    async with tenant_session(world.tenant, api_engine) as session:
        await dispatch(session, T0)
        await session.rollback()  # the worker died before committing
    assert {d.status for d in await deliveries(api_engine, world)} == {"QUEUED"}
    await run_dispatch(api_engine, world)
    rows = await deliveries(api_engine, world)
    assert len(rows) == 4  # no second delivery rows
    adapter = SimulatedChannelAdapter()
    for d in rows:  # the same key gives the same provider reference
        again = await adapter.send(Recipient(d.person_id, None), d.channel, "", str(d.id), T0)
        assert d.provider_ref == again.provider_ref


async def test_receipts_are_telemetry(api_engine: AsyncEngine, world: World) -> None:
    await campaign(api_engine, world)
    await run_dispatch(api_engine, world)
    async with tenant_session(world.tenant, api_engine) as session:
        before = await session.scalar(select(func.count()).select_from(AuditLog))
        assert await refresh_receipts(session, T0 + timedelta(seconds=3)) == 4
        assert await refresh_receipts(session, T0 + timedelta(seconds=7)) == 4
        assert await refresh_receipts(session, T0 + timedelta(seconds=8)) == 0
        await session.commit()
        after = await session.scalar(select(func.count()).select_from(AuditLog))
    assert {d.status for d in await deliveries(api_engine, world)} == {"READ"}
    assert after == before  # plan G-20: not audited
