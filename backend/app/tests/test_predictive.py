"""Predictive Risk (PRD-01..05; D-46; docs/plan-pilot-prd.md §2-§6): the components and their
points, the calendar's ramp and cap, the projection (incidents halve every 3 days, events on
their dates, the trend clamped) and its band, the snapshot (audited once a day), drivers, rising
risk and rule-based actions that never name a VIP visit. Against real PostgreSQL, as nexira_api.
"""

import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any, cast

from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import tenant_session
from app.core.realtime import FORWARDED
from app.modules.predictive import consumer
from app.modules.predictive import service as predictive
from app.modules.predictive.models import MissionEvent
from app.tests.auth_helpers import Idp
from app.tests.fakes import ListPublisher

D0 = date(2026, 11, 3)


def _event(start: int, weight: int, days: int = 1) -> MissionEvent:
    return cast(
        MissionEvent,
        SimpleNamespace(
            starts_on=D0 + timedelta(days=start),
            ends_on=D0 + timedelta(days=start + days - 1),
            weight=weight,
            title="Rally",
        ),
    )


def test_the_calendar_ramps_up_two_days_before_and_is_capped() -> None:
    rally = [_event(5, 30)]
    at = [predictive.event_points(rally, D0 + timedelta(days=d)) for d in range(2, 8)]
    assert at == [0, 15, 22, 30, 0, 0]  # day 3: 50%, day 4: 75%, day 5: 100%, then gone
    assert predictive.event_points([_event(0, 30), _event(0, 30)], D0) == 45  # capped


def test_signal_points_are_above_the_norm_only() -> None:
    assert predictive.signal_points(3, 0) == 6
    assert predictive.signal_points(2, 3.5) == 0
    assert predictive.signal_points(40, 1) == 10


def test_the_trend_is_clamped() -> None:
    assert predictive.trend_slope([35] * 14) == 0
    assert predictive.trend_slope(list(range(0, 140, 10))) == 1  # +10 a day, clamped
    assert predictive.trend_slope([5]) == 0


def test_the_projection_fades_incidents_adds_events_and_widens() -> None:
    c = predictive.Components(
        mission_id=uuid.uuid4(),
        code="NBO",
        city="Nairobi",
        risk_level="LOW",
        incident=("INC-2026-1042", "Civil unrest", "CRITICAL"),
        events=[_event(10, 20)],
    )
    assert predictive.total(c.points(D0)) == 80
    ahead = predictive.forecast(c, D0, 0)
    by_day = {(f.day - D0).days: f for f in ahead}
    assert by_day[3].value == round(35 + 45 / 2)  # half-life of 3 days
    assert by_day[10].value == round(35 + 45 * 2 ** (-10 / 3) + 20)
    assert (by_day[1].high - by_day[1].value, by_day[14].high - by_day[14].value) == (4, 16)
    assert by_day[14].value < predictive.total(c.points(D0))


# --- the API, the snapshot and the figures ------------------------------------------------------


async def _world(idp: Idp) -> dict[str, Any]:
    ids: dict[str, Any] = {}
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        for code, city, risk, lon, lat in (
            ("ADD", "Addis Ababa", "LOW", 38.74, 9.03),
            ("ISB", "Islamabad", "MODERATE", 73.05, 33.69),
            ("NBO", "Nairobi", "LOW", 36.82, -1.29),
        ):
            ids[code] = await session.scalar(
                text(
                    "INSERT INTO mission (tenant_id, code, city, country_code, location, "
                    "risk_level) VALUES (current_tenant_id(), :c, :city, 'XX', "
                    "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :r) RETURNING id"
                ),
                {"c": code, "city": city, "lon": lon, "lat": lat, "r": risk},
            )
        today = await predictive.db_today(session)
        for title, weight in (
            ("Rally near the industrial park", 30),
            ("Counter-demonstration", 10),
        ):
            await session.execute(
                text(
                    "INSERT INTO mission_event (tenant_id, mission_id, kind, title, starts_on, "
                    "ends_on, attendance, weight) VALUES (current_tenant_id(), :m, 'RALLY', :t, "
                    ":d, :d, 5000, :w)"
                ),
                {"m": ids["ADD"], "t": title, "d": today + timedelta(days=5), "w": weight},
            )
        await session.commit()
    ids["today"] = today
    await idp.user("viewer", [("VIEWER", None)])
    return ids


async def test_a_rally_takes_addis_over_the_threshold(client: AsyncClient, idp: Idp) -> None:
    ids = await _world(idp)
    today = ids["today"]
    response = await client.get("/api/predictive/overview", headers=idp.headers("viewer"))
    assert response.status_code == 200
    out = response.json()
    first = out["rising"][0]
    assert (first["mission_code"], first["now"], first["peak"], first["crosses"]) == (
        "ADD",
        35,
        75,
        True,
    )
    assert first["peak_day"] == (today + timedelta(days=5)).isoformat()
    assert out["actions"] == [
        {
            "mission_code": "ADD",
            "text": "Review movements and venues in Addis Ababa around Rally near the "
            f"industrial park ({(today + timedelta(days=5)).isoformat()}).",
        }
    ]
    assert out["threshold"] == 70
    assert "illustrative" in out["model"].lower()
    assert "visit" not in repr(out).lower()  # never a VIP visit (G-1)

    detail = (
        await client.get(f"/api/predictive/missions/{ids['ADD']}", headers=idp.headers("viewer"))
    ).json()
    assert detail["history"][-1] == {"day": today.isoformat(), "value": 35, "source": "LIVE"}
    # Both rallies (weight 40): 50% two days before, 75% the day before, in full on the day.
    assert [f["value"] for f in detail["forecast"][2:6]] == [55, 65, 75, 35]
    assert [(d["key"], d["points"]) for d in detail["drivers"]] == [("baseline", 35)]
    assert [e["title"] for e in detail["events"]] == [
        "Counter-demonstration",
        "Rally near the industrial park",
    ]
    missing = await client.get(
        f"/api/predictive/missions/{uuid.uuid4()}", headers=idp.headers("viewer")
    )
    assert missing.status_code == 404


async def test_an_incident_lifts_nairobi_and_eases(client: AsyncClient, idp: Idp) -> None:
    ids = await _world(idp)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(
            text(
                "INSERT INTO incident (tenant_id, reference, title, category, severity, "
                "signal_severity, location, mission_id) VALUES (current_tenant_id(), "
                "'INC-2026-1042', 'Civil unrest', 'CIVIL_UNREST', 'CRITICAL', 'HIGH', "
                "'SRID=4326;POINT(36.82 -1.28)', :m)"
            ),
            {"m": ids["NBO"]},
        )
        await session.commit()
    detail = (
        await client.get(f"/api/predictive/missions/{ids['NBO']}", headers=idp.headers("viewer"))
    ).json()
    assert detail["now"] == 80
    assert detail["forecast"][-1]["value"] < 80
    assert ("incidents", 45) in [(d["key"], d["points"]) for d in detail["drivers"]]
    assert "Civil unrest INC-2026-1042 (critical)" in [d["label"] for d in detail["drivers"]]
    out = (await client.get("/api/predictive/overview", headers=idp.headers("viewer"))).json()
    # Still above 70 the day after: kept at Elevated, as the design (§6).
    assert {
        "mission_code": "NBO",
        "text": "Keep Nairobi at Elevated until the forecast stays below 70 for 72 h.",
    } in out["actions"]
    nbo = next(r for r in out["rising"] if r["mission_code"] == "NBO")
    assert (nbo["now"], nbo["change"] <= 0) == (80, True)


async def test_the_snapshot_is_stored_and_audited_once_a_day(idp: Idp) -> None:
    await _world(idp)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        assert await predictive.snapshot(session) == 3
        assert await predictive.snapshot(session) == 3  # refreshed, not added
        await session.commit()
        rows = (
            await session.execute(
                text(
                    "SELECT (SELECT count(*) FROM risk_index WHERE source = 'COMPUTED') AS rows, "
                    "(SELECT count(*) FROM audit_log "
                    "WHERE action = 'PREDICTIVE.SNAPSHOT') AS audits, "
                    "(SELECT components FROM risk_index r JOIN mission m ON m.id = r.mission_id "
                    "WHERE m.code = 'ISB') AS isb"
                )
            )
        ).one()
    assert (rows.rows, rows.audits) == (3, 1)
    assert rows.isb["baseline"] == 50
    assert set(rows.isb) == set(predictive.KEYS)


async def test_a_change_against_a_week_ago(client: AsyncClient, idp: Idp) -> None:
    """Drivers compare with the computed row of 7 days ago (§5); history comes from the table."""
    ids = await _world(idp)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        # A past COMPUTED row as a snapshot would have left it, written as the owner would have.
        for d in range(1, 31):
            await session.execute(
                text(
                    "INSERT INTO risk_index (tenant_id, mission_id, day, value, components, "
                    "source) VALUES (current_tenant_id(), :m, :day, 50, '{\"illustrative\": 50}', "
                    "'ILLUSTRATIVE')"
                ),
                {"m": ids["ISB"], "day": ids["today"] - timedelta(days=d)},
            )
        await session.commit()
    detail = (
        await client.get(f"/api/predictive/missions/{ids['ISB']}", headers=idp.headers("viewer"))
    ).json()
    assert len(detail["history"]) == 31  # 30 illustrative days and today
    assert {h["source"] for h in detail["history"][:-1]} == {"ILLUSTRATIVE"}
    assert detail["drivers"][0]["change"] is None  # no computed components a week ago


async def test_the_worker_tick_publishes_counts_only(idp: Idp) -> None:
    """The snapshot loop (§3): PREDICTIVE_UPDATED carries a count, never a mission's figures."""
    await _world(idp)
    publisher = ListPublisher()
    assert await consumer.tick(idp.engine, idp.tenant_id, publisher) == 3
    [event] = publisher.events
    assert (event.type, event.payload) == ("PREDICTIVE_UPDATED", {"missions": 3})
    assert "PREDICTIVE_UPDATED" in FORWARDED
