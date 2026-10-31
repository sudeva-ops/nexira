"""Builds the seed world as plain data: missions, sites, people and observations.

Pure and deterministic: the same scenario date gives the same lists (seed 42).
Loading happens in nexira_sim.seed.load through the backend service layer.
"""

import math
import random
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta

from app.modules.people.service import ObservationIn, PersonIn, SiteIn

from nexira_sim.seed import data
from nexira_sim.seed.ids import seed_id

SEED = 42
EARTH_M_PER_DEG_LAT = 111_320.0


def scenario_as_of(scenario_date: date) -> datetime:
    """All seeded timestamps derive from 06:00 UTC on the scenario date (09:00 Nairobi)."""
    return datetime.combine(scenario_date, time(6, 0), tzinfo=UTC)


def offset(lat: float, lon: float, distance_m: float, bearing_deg: float) -> tuple[float, float]:
    """Move a point by distance_m along a bearing (equirectangular; fine below 20 km)."""
    b = math.radians(bearing_deg)
    dlat = distance_m * math.cos(b) / EARTH_M_PER_DEG_LAT
    dlon = distance_m * math.sin(b) / (EARTH_M_PER_DEG_LAT * math.cos(math.radians(lat)))
    return round(lat + dlat, 6), round(lon + dlon, 6)


def scatter(rng: random.Random, lat: float, lon: float, max_m: float) -> tuple[float, float]:
    """A uniformly random point within max_m of (lat, lon)."""
    return offset(lat, lon, max_m * math.sqrt(rng.random()), rng.uniform(0, 360))


@dataclass(frozen=True)
class MissionIn:
    id: uuid.UUID
    index: int
    code: str
    city: str
    country_code: str
    lat: float
    lon: float
    staff: int
    risk_level: str


@dataclass
class World:
    scenario_date: date
    as_of: datetime
    missions: list[MissionIn] = field(default_factory=list)
    sites: list[SiteIn] = field(default_factory=list)
    persons: list[PersonIn] = field(default_factory=list)
    observations: list[ObservationIn] = field(default_factory=list)
    delegate_ids: list[uuid.UUID] = field(default_factory=list)
    manila_trip_ids: list[uuid.UUID] = field(default_factory=list)  # data.MANILA_TRIP


def _observation_for(
    person_id: uuid.UUID,
    source: str,
    target_confidence: int,
    lat: float,
    lon: float,
    place: str | None,
    as_of: datetime,
) -> ObservationIn:
    """An observation that the Location Confidence Engine scores at exactly
    target_confidence (see app/modules/people/location.py)."""
    observed_at = as_of
    raw: dict[str, object] = {}
    if source == "MOBILE_GPS":
        raw["accuracy_m"] = (100 - target_confidence) * 10
    elif source == "ACCESS_CONTROL":
        # base 99, minus 6 points per hour: 10 minutes per point.
        observed_at = as_of - timedelta(minutes=(99 - target_confidence) * 10)
        raw["door"] = "Main entrance"
    else:
        raw["quality"] = target_confidence
    return ObservationIn(
        person_id=person_id,
        source=source,
        lat=lat,
        lon=lon,
        observed_at=observed_at,
        place_label=place,
        raw=raw,
    )


def _email(name: str, n: int) -> str:
    local = ".".join(p.lower() for p in name.replace("Amb. ", "").replace("Dr. ", "").split())
    return f"{local}.{n}@demo.nexira.invalid"


def build(scenario_date: date, tenant_id: uuid.UUID) -> World:
    rng = random.Random(SEED)
    as_of = scenario_as_of(scenario_date)
    w = World(scenario_date=scenario_date, as_of=as_of)
    by_city: dict[str, MissionIn] = {}

    for i, (code, city, _country, cc, lat, lon, staff) in enumerate(data.MISSIONS):
        m = MissionIn(
            id=seed_id(tenant_id, "mission", code),
            index=i,
            code=code,
            city=city,
            country_code=cc,
            lat=lat,
            lon=lon,
            staff=staff,
            risk_level="MODERATE" if city in data.ELEVATED else "LOW",
        )
        w.missions.append(m)
        by_city[city] = m
        readiness = 70 + (i * 37) % 29  # demo People & Sites table
        drilled = scenario_date - timedelta(weeks=1 + (i * 13) % 11)
        if code == "NBO":
            embassy, residence = data.EMBASSY, data.RESIDENCE
        else:
            embassy, residence = (lat, lon), offset(lat, lon, 2500, (i * 47) % 360)
        w.sites.append(
            SiteIn(
                seed_id(tenant_id, "site", f"{code}:EMBASSY"),
                m.id,
                "EMBASSY",
                f"Embassy {city}",
                *embassy,
                readiness,
                drilled,
            )
        )
        w.sites.append(
            SiteIn(
                seed_id(tenant_id, "site", f"{code}:RESIDENCE"),
                m.id,
                "RESIDENCE",
                f"Ambassador's Residence {city}",
                *residence,
                max(0, readiness - 6),
                drilled,
            )
        )
    nbo = by_city["Nairobi"]
    w.sites.append(
        SiteIn(
            seed_id(tenant_id, "site", "NBO:HOTEL"),
            nbo.id,
            "HOTEL",
            "Hotel · Upper Hill (trade delegation)",
            *data.HOTEL,
        )
    )

    serial = 0

    def person(
        key: str,
        mission: MissionIn,
        ptype: str,
        name: str,
        title: str | None,
        lang: str = "en",
        email: bool = True,
    ) -> uuid.UUID:
        nonlocal serial
        serial += 1
        pid = seed_id(tenant_id, "person", key)
        is_staff = ptype in ("DIPLOMAT", "LOCAL_STAFF")
        w.persons.append(
            PersonIn(
                id=pid,
                mission_id=mission.id,
                person_type=ptype,
                full_name=name,
                role_title=title,
                email=_email(name, serial) if email else None,
                preferred_lang=lang,
                hr_external_id=f"HR-{serial:05d}" if is_staff else None,
            )
        )
        return pid

    # Nairobi: the 17 named people (D-23), at the §7 coordinates.
    for n, (name, title, place, source, conf, ptype) in enumerate(data.NAIROBI_PEOPLE):
        pid = person(f"NBO:named:{n}", nbo, ptype, name, title)
        if name == "Amb. Layla Haddad":
            lat, lon = data.RESIDENCE
        elif name == "Peter Mwangi":
            lat, lon = data.PETER
        elif name == "Hana Takeda":
            lat, lon = data.HANA
        elif ptype == "DELEGATE":
            lat, lon = data.HOTEL
            w.delegate_ids.append(pid)
        else:
            lat, lon = scatter(rng, *data.EMBASSY, 780)  # within 0.8 km of the Embassy
        w.observations.append(_observation_for(pid, source, conf, lat, lon, place, as_of))

    # Nairobi: 212 registered citizens inside the zone; nobody else (D-23).
    for n in range(data.NAIROBI_CITIZENS):
        pid = person(
            f"NBO:citizen:{n}",
            nbo,
            "CITIZEN",
            _name(rng),
            None,
            lang=rng.choice(["en", "en", "ar", "fr", "sw"]),
            email=False,
        )
        lat, lon = scatter(rng, *data.EPICENTRE, data.CITIZEN_MAX_RADIUS_M)
        w.observations.append(
            _observation_for(
                pid, "MANUAL", rng.randint(55, 70), lat, lon, "Registered address", as_of
            )
        )

    others = [m for m in w.missions if m.code != "NBO"]

    # Other missions: staff per the demo array, the named OTHERS first.
    named_by_city: dict[str, list[tuple[str, str, str, str, int]]] = {}
    for name, title, city, place, source, conf in data.OTHER_NAMED:
        named_by_city.setdefault(city, []).append((name, title, place, source, conf))
    where: str | None
    for m in others:
        named = named_by_city.get(m.city, [])
        for n in range(m.staff):
            if n < len(named):
                name, title, where, source, conf = named[n]
                ptype = "DIPLOMAT"
            else:
                ptype = "DIPLOMAT" if rng.random() < 0.7 else "LOCAL_STAFF"
                titles = data.DIPLOMAT_TITLES if ptype == "DIPLOMAT" else data.LOCAL_TITLES
                name, title = _name(rng), rng.choice(titles)
                source = rng.choice(["ACCESS_CONTROL", "ACCESS_CONTROL", "MOBILE_GPS"])
                conf = rng.randint(90, 99) if source == "ACCESS_CONTROL" else rng.randint(80, 98)
                where = "Embassy" if source == "ACCESS_CONTROL" else None
            pid = person(f"{m.code}:staff:{n}", m, ptype, name, title)
            lat, lon = scatter(rng, m.lat, m.lon, 1000)
            w.observations.append(_observation_for(pid, source, conf, lat, lon, where, as_of))

    # 412 other personnel (plan G-10): the 3 Nairobi delegates plus 409 elsewhere.
    weights = [m.staff for m in others]
    for n in range(data.OTHER_PERSONNEL - len(w.delegate_ids)):
        m = rng.choices(others, weights)[0]
        ptype = rng.choices(["DEPENDANT", "CONTRACTOR", "DELEGATE"], [74, 17, 9])[0]
        title = {
            "DEPENDANT": "Dependant",
            "CONTRACTOR": "Contractor",
            "DELEGATE": "Visiting delegate",
        }[ptype]
        pid = person(f"{m.code}:other:{n}", m, ptype, _name(rng), title)
        lat, lon = scatter(rng, m.lat, m.lon, 6000)
        source, conf = (
            ("CALENDAR_HR", rng.randint(65, 80))
            if ptype != "DEPENDANT"
            else ("MANUAL", rng.randint(55, 70))
        )
        w.observations.append(_observation_for(pid, source, conf, lat, lon, None, as_of))

    # About 1,000 registered citizens across the other missions (D-27).
    for n in range(data.OTHER_CITIZENS):
        m = rng.choices(others, weights)[0]
        pid = person(f"{m.code}:citizen:{n}", m, "CITIZEN", _name(rng), None, email=False)
        lat, lon = scatter(rng, m.lat, m.lon, 15000)
        w.observations.append(
            _observation_for(
                pid, "MANUAL", rng.randint(55, 70), lat, lon, "Registered address", as_of
            )
        )

    # The Manila trip's travellers (WX-06): the first diplomats of their mission, booked at
    # the Manila hotel instead of seen at home. Nothing new is drawn from rng, so everyone
    # else is where they were.
    _ref, _purpose, home, count, *_rest, (hotel_lat, hotel_lon), hotel = data.MANILA_TRIP
    home_id = next(m.id for m in w.missions if m.code == home)
    w.manila_trip_ids = trip_travellers(w, home_id, count)
    for n, o in enumerate(w.observations):
        if o.person_id in w.manila_trip_ids:
            w.observations[n] = _observation_for(
                o.person_id, "TRAVEL_BOOKING", 89, hotel_lat, hotel_lon, hotel, as_of
            )

    # Plan G-2 (Document Expiry): Hana Takeda's child is the last generated dependant,
    # moved to Nairobi and placed at home outside the zone. Nothing is drawn from rng and
    # nobody is added, so the personnel count and D-23 stay where they are.
    n, child = next(
        (n, p) for n, p in reversed(list(enumerate(w.persons))) if p.person_type == "DEPENDANT"
    )
    w.persons[n] = replace(
        child,
        mission_id=nbo.id,
        full_name=data.DEPENDANT_CHILD,
        email=_email(data.DEPENDANT_CHILD, n + 1),
    )
    for k, o in enumerate(w.observations):
        if o.person_id == child.id:
            w.observations[k] = _observation_for(
                child.id,
                "MANUAL",
                60,
                *data.DEPENDANT_CHILD_HOME,
                data.DEPENDANT_CHILD_PLACE,
                as_of,
            )
    return w


def trip_travellers(w: World, mission_id: uuid.UUID, count: int) -> list[uuid.UUID]:
    """A seeded trip's travellers: the first diplomats of their mission."""
    return [p.id for p in w.persons if p.mission_id == mission_id and p.person_type == "DIPLOMAT"][
        :count
    ]


def _name(rng: random.Random) -> str:
    return f"{rng.choice(data.FIRST_NAMES)} {rng.choice(data.LAST_NAMES)}"
