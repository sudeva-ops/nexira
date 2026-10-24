"""Ingestion, normalisation and fusion (INC-01..04, D-09, D-10, D-11, Prompt 6)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.core.events import Event
from app.modules.audit.models import AuditLog
from app.modules.intel.fusion import confidence
from app.modules.intel.models import Incident, IncidentEvent, IncidentSignal, IntelSource, RawSignal
from app.modules.intel.normalise import normalise
from app.modules.intel.service import ensure_sources
from app.tests.conftest import DbUrls, create_tenant
from app.tests.intel_helpers import (
    EPICENTRE,
    KM_LAT,
    SOURCES,
    T0,
    ingest,
    intel_tenant,
    signal,
)


@pytest.fixture
async def tenant(db: DbUrls, api_engine: AsyncEngine) -> uuid.UUID:
    return await intel_tenant(db, api_engine)


async def incidents(engine: AsyncEngine, tenant: uuid.UUID) -> list[Incident]:
    async with tenant_session(tenant, engine) as session:
        return list(await session.scalars(select(Incident).order_by(Incident.reference)))


# --- pure functions ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reliabilities", "expected"),
    [
        (["0.60"], 60),
        (["0.60", "0.55"], 82),
        (["0.60", "0.55", "0.55"], 92),  # D-10 Nairobi
        (["0.50"], 50),
        (["0.50"] * 8, 99),  # 99.6 is capped at 99
        ([], 0),
    ],
)
def test_confidence_formula(reliabilities: list[str], expected: int) -> None:
    assert confidence(Decimal(r) for r in reliabilities) == expected


@pytest.mark.parametrize(
    ("category", "severity", "has_location", "expected"),
    [
        ("Unrest", "Moderate", True, ("CIVIL_UNREST", "MODERATE", None)),
        ("Riot", "Moderate", True, (None, "MODERATE", "unknown category 'Riot'")),
        ("Unrest", "Extreme", True, ("CIVIL_UNREST", None, "unknown severity 'Extreme'")),
        ("Unrest", "Bogus", True, ("CIVIL_UNREST", None, "unknown severity 'Bogus'")),
        (None, "Moderate", True, (None, "MODERATE", "unknown category None")),
        ("Unrest", "Moderate", False, ("CIVIL_UNREST", "MODERATE", "no location")),
    ],
)
def test_normalise_uses_only_the_sources_own_maps(
    category: str | None,
    severity: str,
    has_location: bool,
    expected: tuple[str | None, str | None, str | None],
) -> None:
    riskline = SOURCES[2]
    result = normalise(
        category_map=riskline.category_map,
        severity_map=riskline.severity_map,
        provider_category=category,
        provider_severity=severity,
        has_location=has_location,
    )
    assert (result.category, result.severity, result.reason) == expected


# --- with the database --------------------------------------------------------------------


async def test_three_nairobi_signals_fuse_into_one_incident_and_paris_stays_separate(
    api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    year = datetime.now(UTC).year
    results = [
        await ingest(api_engine, tenant, signal("DATAMINR", "High")),
        await ingest(
            api_engine,
            tenant,
            signal(
                "FACTAL",
                "Moderate",
                at=timedelta(seconds=30),
                where=(48.86, 2.35),
                category="Strike",
                place="Paris",
            ),
        ),
        await ingest(
            api_engine,
            tenant,
            signal("MAX", "Level 4", at=timedelta(seconds=45), where=(-1.2990, 36.8150)),
        ),
        await ingest(
            api_engine,
            tenant,
            signal("RISKLINE", "Moderate", at=timedelta(seconds=100), where=(-1.2864, 36.8172)),
        ),
    ]
    assert [r.outcome for r in results] == ["FUSED"] * 4
    assert [r.fused.created for r in results if r.fused] == [True, True, False, False]
    assert [r.fused.confidence for r in results if r.fused] == [60, 50, 82, 92]

    nbo, paris = await incidents(api_engine, tenant)
    assert nbo.reference == f"INC-{year}-1042"
    assert (nbo.category, nbo.confidence, nbo.signal_severity, nbo.severity) == (
        "CIVIL_UNREST",
        92,
        "HIGH",
        "HIGH",  # Prompt 7 escalates to CRITICAL (D-11)
    )
    assert nbo.last_signal_at == T0 + timedelta(seconds=100)
    assert nbo.opened_at == T0
    assert nbo.title == "Civil unrest · Nairobi"
    assert paris.reference == f"INC-{year}-1043"
    assert (paris.category, paris.signal_severity, paris.confidence) == (
        "TRANSPORT_STRIKE",
        "MODERATE",
        50,
    )

    async with tenant_session(tenant, api_engine) as session:
        linked = await session.execute(
            select(IntelSource.code, RawSignal.norm_severity, RawSignal.norm_status)
            .join(RawSignal, RawSignal.source_id == IntelSource.id)
            .join(IncidentSignal, IncidentSignal.signal_id == RawSignal.id)
            .where(IncidentSignal.incident_id == nbo.id)
            .order_by(RawSignal.occurred_at)
        )
        # D-11 step 1: each signal on its own; Riskline "Moderate" stays MODERATE.
        assert linked.all() == [
            ("DATAMINR", "HIGH", "FUSED"),
            ("MAX", "HIGH", "FUSED"),
            ("RISKLINE", "MODERATE", "FUSED"),
        ]
        timeline = await session.scalars(
            select(IncidentEvent.event_type)
            .where(IncidentEvent.incident_id == nbo.id)
            .order_by(IncidentEvent.occurred_at)
        )
        assert timeline.all() == ["SIGNAL", "FUSED", "FUSED"]
        actions = await session.scalars(
            select(AuditLog.action)
            .where(AuditLog.action.like("INCIDENT.%") | AuditLog.action.like("RAW_SIGNAL.%"))
            .order_by(AuditLog.chain_seq)
        )
        assert actions.all() == [
            "RAW_SIGNAL.NORMALISE",
            "INCIDENT.CREATE",
            "RAW_SIGNAL.NORMALISE",
            "INCIDENT.CREATE",
            "RAW_SIGNAL.NORMALISE",
            "INCIDENT.FUSE_SIGNAL",
            "RAW_SIGNAL.NORMALISE",
            "INCIDENT.FUSE_SIGNAL",
        ]


async def test_a_duplicate_event_is_ignored(api_engine: AsyncEngine, tenant: uuid.UUID) -> None:
    first = await ingest(api_engine, tenant, signal("DATAMINR", "High", external_id="dup-1"))
    again = await ingest(api_engine, tenant, signal("DATAMINR", "High", external_id="dup-1"))
    assert (first.outcome, again.outcome) == ("FUSED", "DUPLICATE")
    async with tenant_session(tenant, api_engine) as session:
        assert len((await session.scalars(select(RawSignal))).all()) == 1
        assert len((await session.scalars(select(IncidentSignal))).all()) == 1


async def test_osint_never_fuses(api_engine: AsyncEngine, tenant: uuid.UUID) -> None:
    disabled = await ingest(api_engine, tenant, signal("OSINT", "Major"))
    assert (disabled.outcome, disabled.reason) == ("DISCARDED", "source disabled")

    async with tenant_session(tenant, api_engine) as session:
        await session.execute(
            update(IntelSource).where(IntelSource.code == "OSINT").values(is_enabled=True)
        )
        await session.commit()
    # Enabled but outside fusion (D-09): normalised, joins nothing and opens nothing,
    # even next to an active incident of the same category.
    await ingest(api_engine, tenant, signal("DATAMINR", "High"))
    enabled = await ingest(api_engine, tenant, signal("OSINT", "Major", at=timedelta(minutes=1)))
    assert (enabled.outcome, enabled.fused) == ("NORMALISED", None)
    (incident,) = await incidents(api_engine, tenant)
    assert incident.confidence == 60


async def test_unknown_values_are_discarded_with_an_audit_entry(
    api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    unknown_severity = await ingest(api_engine, tenant, signal("RISKLINE", "Extreme"))
    unknown_category = await ingest(api_engine, tenant, signal("MAX", "Level 4", category="Riot"))
    outside_d08 = await ingest(api_engine, tenant, signal("RISKLINE", "Bogus"))
    assert [r.outcome for r in (unknown_severity, unknown_category, outside_d08)] == [
        "DISCARDED"
    ] * 3
    assert await incidents(api_engine, tenant) == []
    async with tenant_session(tenant, api_engine) as session:
        statuses = await session.scalars(select(RawSignal.norm_status))
        assert set(statuses.all()) == {"DISCARDED"}
        rows = await session.scalars(
            select(AuditLog).where(AuditLog.action == "RAW_SIGNAL.DISCARD")
        )
        reasons = sorted(r.details["reason"] for r in rows)
    assert reasons == [
        "unknown category 'Riot'",
        "unknown severity 'Bogus'",
        "unknown severity 'Extreme'",
    ]


async def test_unknown_source_and_bad_payload_are_rejected_and_audited(
    api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    valid = await ingest(api_engine, tenant, signal("DATAMINR", "High"))
    bad = Event(type="RAW_SIGNAL", tenant_id=tenant, payload={"source_code": "X"}, source="t")
    no_source = signal("DATAMINR", "High")
    no_source.payload["source_code"] = "NOPE"
    rejected = [await ingest(api_engine, tenant, e) for e in (bad, no_source)]
    assert valid.outcome == "FUSED"
    assert [r.outcome for r in rejected] == ["REJECTED", "REJECTED"]
    assert rejected[1].reason == "unknown source 'NOPE'"
    async with tenant_session(tenant, api_engine) as session:
        count = len(
            (
                await session.scalars(
                    select(AuditLog).where(AuditLog.action == "RAW_SIGNAL.REJECT")
                )
            ).all()
        )
    assert count == 2


@pytest.mark.parametrize(
    ("km_north", "minutes", "category", "joins"),
    [
        (2.9, 0, "Unrest", True),
        (3.1, 0, "Unrest", False),  # > 3 km
        (0, 59, "Unrest", True),
        (0, 61, "Unrest", False),  # > 60 min after last_signal_at
        (0, -30, "Unrest", True),  # a late-arriving, earlier signal
        (0, 0, "Strike", False),  # another category
    ],
)
async def test_fusion_rule_boundaries(
    api_engine: AsyncEngine,
    tenant: uuid.UUID,
    km_north: float,
    minutes: int,
    category: str,
    joins: bool,
) -> None:
    await ingest(api_engine, tenant, signal("DATAMINR", "High"))
    second = signal(
        "FACTAL",
        "Moderate",
        at=timedelta(minutes=minutes),
        where=(EPICENTRE[0] + km_north * KM_LAT, EPICENTRE[1]),
        category=category,
    )
    result = await ingest(api_engine, tenant, second)
    assert result.fused is not None
    assert result.fused.created is not joins
    assert len(await incidents(api_engine, tenant)) == (1 if joins else 2)


async def test_window_follows_last_signal_at(api_engine: AsyncEngine, tenant: uuid.UUID) -> None:
    for minutes in (0, 50, 100, 150):  # each within 60 min of the previous one
        await ingest(api_engine, tenant, signal("DATAMINR", "High", at=timedelta(minutes=minutes)))
    (incident,) = await incidents(api_engine, tenant)
    assert incident.last_signal_at == T0 + timedelta(minutes=150)


async def test_location_does_not_move_and_the_nearest_incident_wins(
    api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    north = (EPICENTRE[0] + 2.0 * KM_LAT, EPICENTRE[1])
    south = (EPICENTRE[0] - 2.0 * KM_LAT, EPICENTRE[1])
    a = await ingest(api_engine, tenant, signal("DATAMINR", "High", where=north))
    b = await ingest(api_engine, tenant, signal("DATAMINR", "High", where=south))
    assert a.fused is not None
    assert b.fused is not None
    assert b.fused.created  # 4 km apart: separate incidents
    # 1.5 km south of the epicentre: 3.5 km from north, 0.5 km from south.
    near_south = (EPICENTRE[0] - 1.5 * KM_LAT, EPICENTRE[1])
    c = await ingest(api_engine, tenant, signal("MAX", "Level 4", where=near_south))
    assert c.fused is not None
    assert c.fused.incident_id == b.fused.incident_id
    # 1 km north of the epicentre: 1 km from north, 3 km from south -> north.
    d = await ingest(
        api_engine, tenant, signal("MAX", "Level 4", where=(EPICENTRE[0] + KM_LAT, EPICENTRE[1]))
    )
    assert d.fused is not None
    assert d.fused.incident_id == a.fused.incident_id


async def test_only_active_incidents_take_signals(
    api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    await ingest(api_engine, tenant, signal("DATAMINR", "High"))
    async with tenant_session(tenant, api_engine) as session:
        await session.execute(update(Incident).values(status="MONITORING"))
        await session.commit()
    result = await ingest(api_engine, tenant, signal("MAX", "Level 4"))
    assert result.fused is not None
    assert result.fused.created


async def test_one_source_counts_once_and_severity_takes_the_highest(
    api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    await ingest(api_engine, tenant, signal("DATAMINR", "Medium"))
    second = await ingest(api_engine, tenant, signal("DATAMINR", "Critical", at=timedelta(1 / 24)))
    assert second.fused is not None
    assert (second.fused.confidence, second.fused.signal_severity) == (60, "CRITICAL")
    (incident,) = await incidents(api_engine, tenant)
    assert (incident.signal_severity, incident.severity) == ("CRITICAL", "CRITICAL")


async def test_a_raised_severity_is_kept_when_a_lower_signal_joins(
    api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    await ingest(api_engine, tenant, signal("DATAMINR", "High"))
    async with tenant_session(tenant, api_engine) as session:
        await session.execute(update(Incident).values(severity="CRITICAL"))  # as D-11 step 3
        await session.commit()
    await ingest(api_engine, tenant, signal("RISKLINE", "Moderate"))
    (incident,) = await incidents(api_engine, tenant)
    assert (incident.signal_severity, incident.severity) == ("HIGH", "CRITICAL")


async def test_another_tenants_incident_is_never_joined(
    db: DbUrls, api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    other = await create_tenant(db, "Other")
    async with tenant_session(other, api_engine) as session:
        await ensure_sources(session, SOURCES)
        await session.commit()
    await ingest(api_engine, other, signal("DATAMINR", "High"))
    result = await ingest(api_engine, tenant, signal("MAX", "Level 4"))
    assert result.fused is not None
    assert result.fused.created
    assert result.fused.confidence == 55
