"""Nearby API (NBY-01..04; D-52; plan-pilot-map §3) on real PostgreSQL, as nexira_api: what is
within a radius of a point, nearest first, under RLS; people by the exposure's groups plus the
others (G-5); names only within the caller's people scope; a restricted trip's traveller never
named or counted as a traveller (D-33); partners by the nearest mission's country (G-1); not
audited (§115 Q5)."""

from typing import Any

from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import tenant_session
from app.tests.auth_helpers import Idp

EMBASSY = (36.8219, -1.2921)  # lon, lat
POINT = {"lon": EMBASSY[0], "lat": EMBASSY[1]}


def _pt(lon: float, lat: float) -> str:
    return f"'SRID=4326;POINT({lon} {lat})'"


async def _setup(idp: Idp) -> dict[str, Any]:
    async with tenant_session(idp.tenant_id, idp.engine) as s:

        async def one(sql: str, **params: Any) -> Any:
            return await s.scalar(text(sql), params)

        nbo = await one(
            "INSERT INTO mission (tenant_id, code, city, country_code, location) VALUES "
            f"(current_tenant_id(), 'NBO', 'Nairobi', 'KE', {_pt(*EMBASSY)}) RETURNING id"
        )
        cai = await one(
            "INSERT INTO mission (tenant_id, code, city, country_code, location) VALUES "
            f"(current_tenant_id(), 'CAI', 'Cairo', 'EG', {_pt(31.2357, 30.0444)}) RETURNING id"
        )

        async def person(name: str, kind: str, lon: float, lat: float, confidence: int) -> Any:
            person_id = await one(
                "INSERT INTO person (tenant_id, mission_id, person_type, full_name) VALUES "
                "(current_tenant_id(), :m, :k, :n) RETURNING id",
                m=nbo,
                k=kind,
                n=name,
            )
            await s.execute(
                text(
                    "INSERT INTO person_location_current (person_id, tenant_id, location, "
                    "confidence, primary_source) VALUES (:p, current_tenant_id(), "
                    f"{_pt(lon, lat)}, :c, 'GPS')"
                ),
                {"p": person_id, "c": confidence},
            )
            return person_id

        people = {
            "Amara Diallo": await person(
                "Amara Diallo", "DIPLOMAT", 36.8229, -1.2921, 90
            ),  # ~110 m
            "Jonas Berg": await person(
                "Jonas Berg", "LOCAL_STAFF", 36.8419, -1.2921, 80
            ),  # ~2.2 km
            "Ines Duarte": await person("Ines Duarte", "DELEGATE", 36.8219, -1.3021, 70),  # ~1.1 km
            "Tomas Novak": await person("Tomas Novak", "CITIZEN", 36.8519, -1.2921, 60),  # ~3.3 km
            "Lea Morel": await person("Lea Morel", "DEPENDANT", 36.8219, -1.2771, 100),  # ~1.7 km
            "Rafael Ortiz": await person(
                "Rafael Ortiz", "DIPLOMAT", 39.6682, -4.0435, 95
            ),  # Mombasa
            "Mira Sato": await person("Mira Sato", "DIPLOMAT", 36.8239, -1.2921, 90),  # restricted
        }

        async def trip(reference: str, restricted: bool, *travellers: Any) -> None:
            trip_id = await one(
                "INSERT INTO trip (tenant_id, reference, origin, destination, starts_on, ends_on, "
                "approval_status, restricted) VALUES (current_tenant_id(), :r, 'HQ', 'Nairobi', "
                "current_date - 1, current_date + 1, 'APPROVED', :x) RETURNING id",
                r=reference,
                x=restricted,
            )
            for traveller in travellers:
                await s.execute(
                    text(
                        "INSERT INTO trip_traveller (tenant_id, trip_id, person_id) "
                        "VALUES (current_tenant_id(), :t, :p)"
                    ),
                    {"t": trip_id, "p": traveller},
                )

        await trip("TRP-0001", False, people["Ines Duarte"])
        await trip("TRP-0002", True, people["Mira Sato"])  # a minister's visit (D-33)
        await one(
            "INSERT INTO site (tenant_id, mission_id, site_type, name, location) VALUES "
            "(current_tenant_id(), :m, 'EMBASSY', 'Embassy Nairobi', "
            f"{_pt(*EMBASSY)}) RETURNING id",
            m=nbo,
        )
        await one(
            "INSERT INTO fleet_asset (tenant_id, mission_id, code, kind, type_label, seats, "
            "location, location_label, fuel_pct) VALUES "
            "(current_tenant_id(), :m, 'VH-01', 'VEHICLE', "
            f"'Armoured SUV', 5, {_pt(36.8239, -1.2931)}, 'Embassy car park', 80) RETURNING id",
            m=nbo,
        )
        for code, name, country, sla in (
            ("KMA", "Kestrel Medical", "KE", 30),
            ("NIL", "Nile Aid", "EG", 20),
        ):
            await one(
                "INSERT INTO partner (tenant_id, code, name, services, coverage, sla_minutes) "
                "VALUES (current_tenant_id(), :c, :n, ARRAY['MEDICAL'], "
                "ARRAY[CAST(:k AS char(2))], :s) "
                "RETURNING id",
                c=code,
                n=name,
                k=country,
                s=sla,
            )
        for reference, status in (("INC-2026-1042", "ACTIVE"), ("INC-2026-1001", "MONITORING")):
            await one(
                "INSERT INTO incident (tenant_id, reference, title, category, severity, "
                "signal_severity, status, mission_id, location) VALUES (current_tenant_id(), :r, "
                f"'Unrest', 'CIVIL_UNREST', 'HIGH', 'HIGH', :s, :m, {_pt(36.8269, -1.2861)}) "
                "RETURNING id",
                r=reference,
                s=status,
                m=nbo,
            )
        await s.commit()
    users = {}
    for sub, role, mission in (
        ("duty", "DUTY_OFFICER", None),
        ("hom-cairo", "HEAD_OF_MISSION", cai),
        ("viewer", "VIEWER", None),
    ):
        users[sub] = await idp.user(sub, [(role, mission)])
    async with tenant_session(idp.tenant_id, idp.engine) as s:
        for label, lon, status in (
            ("Checkpoint · Uhuru Highway", 36.8249, "ACTIVE"),
            ("Old", 36.8259, "GONE"),
        ):
            annotation = await s.scalar(
                text(
                    "INSERT INTO map_annotation (tenant_id, mission_id, kind, symbol, shape, "
                    "label, created_by) VALUES (current_tenant_id(), :m, 'MARK', 'CHECKPOINT', "
                    f"{_pt(lon, -1.2921)}, :l, :u) RETURNING id"
                ),
                {"m": nbo, "l": label, "u": users["duty"]},
            )
            if status == "GONE":
                await s.execute(
                    text(
                        "UPDATE map_annotation SET status = 'WITHDRAWN', reason = 'Cleared', "
                        "withdrawn_by = :u WHERE id = :a"
                    ),
                    {"u": users["duty"], "a": annotation},
                )
        await s.commit()
    return {"people": people}


async def _nearby(client: AsyncClient, idp: Idp, who: str, **params: Any) -> Any:
    return await client.get("/api/nearby", params={**POINT, **params}, headers=idp.headers(who))


async def test_everything_within_ten_kilometres_nearest_first(
    client: AsyncClient, idp: Idp
) -> None:
    await _setup(idp)
    response = await _nearby(client, idp, "duty")
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["radius_m"], body["mission_code"], body["country_code"]) == (10_000, "NBO", "KE")
    people = body["people"]
    # Mombasa is out of range; the restricted traveller is counted as staff but never named.
    assert (people["staff"], people["delegates"], people["citizens"], people["others"]) == (
        3,
        1,
        1,
        1,
    )
    assert people["confidence"] == round((90 + 80 + 70 + 60 + 100 + 90) / 6, 1)
    assert [p["name"] for p in people["named"]] == [
        "Amara Diallo",
        "Ines Duarte",
        "Lea Morel",
        "Jonas Berg",
        "Tomas Novak",
    ]
    assert people["unnamed"] == 1
    assert [p["group"] for p in people["named"]] == [
        "STAFF",
        "DELEGATE",
        "OTHER",
        "STAFF",
        "CITIZEN",
    ]
    distances = [p["distance_m"] for p in people["named"]]
    assert distances == sorted(distances)
    assert 100 < distances[0] < 130
    assert "Mira Sato" not in response.text
    assert body["travellers"] == {"people": 1, "trips": 1}  # TRP-0002 is restricted (D-33)
    assert [s["name"] for s in body["sites"]] == ["Embassy Nairobi"]
    assert body["sites"][0]["distance_m"] == 0
    assert [(v["code"], v["status"]) for v in body["vehicles"]] == [("VH-01", "AVAILABLE")]
    assert [p["name"] for p in body["partners"]] == ["Kestrel Medical"]  # covers KE (G-1)
    assert [i["reference"] for i in body["incidents"]] == ["INC-2026-1042"]  # ACTIVE only
    assert [a["label"] for a in body["annotations"]] == ["Checkpoint · Uhuru Highway"]


async def test_the_radius_bounds_what_is_listed(client: AsyncClient, idp: Idp) -> None:
    await _setup(idp)
    near = (await _nearby(client, idp, "duty", radius_m=1_000)).json()
    assert [p["name"] for p in near["people"]["named"]] == ["Amara Diallo"]
    assert near["people"]["unnamed"] == 1  # the restricted traveller, 220 m away
    wide = (await _nearby(client, idp, "duty", radius_m=50_000)).json()
    assert "Rafael Ortiz" not in {p["name"] for p in wide["people"]["named"]}  # 440 km
    for radius in (999, 50_001):
        assert (await _nearby(client, idp, "duty", radius_m=radius)).status_code == 422
    assert (await _nearby(client, idp, "duty", lon=181)).status_code == 422


async def test_names_only_within_the_people_scope(client: AsyncClient, idp: Idp) -> None:
    w = await _setup(idp)
    for who in ("viewer", "hom-cairo"):
        response = await _nearby(client, idp, who)
        assert response.status_code == 200, (who, response.text)
        people = response.json()["people"]
        assert (people["staff"], people["delegates"], people["citizens"], people["others"]) == (
            3,
            1,
            1,
            1,
        )
        assert people["named"] == []
        assert people["unnamed"] == 6
        for name in w["people"]:
            assert name not in response.text, (who, name)


async def test_it_is_a_read_and_not_audited(client: AsyncClient, idp: Idp) -> None:
    await _setup(idp)
    assert (await _nearby(client, idp, "duty")).status_code == 200
    async with tenant_session(idp.tenant_id, idp.engine) as s:
        actions = list(await s.scalars(text("SELECT action FROM audit_log")))
    assert not [a for a in actions if "NEARBY" in a]
