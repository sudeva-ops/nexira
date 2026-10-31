"""The seed world as plain data: counts and determinism (no database)."""

import uuid
from collections import Counter
from datetime import date

from app.modules.people.location import confidence

from nexira_sim.seed import data, world

DAY = date(2026, 10, 20)
TENANT = uuid.UUID("11111111-2222-3333-4444-555555555555")


def test_build_is_deterministic() -> None:
    assert world.build(DAY, TENANT) == world.build(DAY, TENANT)


def test_ids_differ_per_tenant() -> None:
    other = world.build(DAY, uuid.uuid4())
    assert {p.id for p in world.build(DAY, TENANT).persons}.isdisjoint(
        {p.id for p in other.persons}
    )


def test_missions_and_sites() -> None:
    w = world.build(DAY, TENANT)
    assert len(w.missions) == 36
    elevated = {m.city for m in w.missions if m.risk_level == "MODERATE"}
    assert elevated == {"Baghdad", "Islamabad", "Abuja", "Jakarta"}
    assert {m.risk_level for m in w.missions} == {"LOW", "MODERATE"}
    types = Counter(s.site_type for s in w.sites)
    assert types == {"EMBASSY": 36, "RESIDENCE": 36, "HOTEL": 1}
    nbo = next(m for m in w.missions if m.code == "NBO")
    nbo_sites = {s.site_type: (s.lat, s.lon) for s in w.sites if s.mission_id == nbo.id}
    assert nbo_sites == {"EMBASSY": data.EMBASSY, "RESIDENCE": data.RESIDENCE, "HOTEL": data.HOTEL}


def test_people_counts_match_d23_and_d27() -> None:
    w = world.build(DAY, TENANT)
    nbo = next(m for m in w.missions if m.code == "NBO")
    nairobi = Counter(p.person_type for p in w.persons if p.mission_id == nbo.id)
    # Plan-pilot-dx G-2: Hana Takeda's child, moved from another mission, lives outside the
    # zone (test_seed_db checks D-23 there).
    assert nairobi == {
        "DIPLOMAT": 12,
        "LOCAL_STAFF": 2,
        "DELEGATE": 3,
        "CITIZEN": 212,
        "DEPENDANT": 1,
    }
    personnel = [p for p in w.persons if p.person_type != "CITIZEN"]
    assert len(personnel) == 926 + 412 == 1338  # demo KPI "Personnel" (plan G-10)
    staff = [p for p in w.persons if p.person_type in ("DIPLOMAT", "LOCAL_STAFF")]
    assert len(staff) == sum(m[6] for m in data.MISSIONS) == 926
    citizens = [p for p in w.persons if p.person_type == "CITIZEN"]
    assert len(citizens) == 212 + 1000
    assert len(w.delegate_ids) == 3


def test_every_person_has_one_observation() -> None:
    w = world.build(DAY, TENANT)
    assert Counter(o.person_id for o in w.observations) == Counter({p.id: 1 for p in w.persons})


def test_named_nairobi_people_score_their_demo_confidence() -> None:
    w = world.build(DAY, TENANT)
    by_id = {o.person_id: o for o in w.observations}
    names = {p.full_name: p.id for p in w.persons}
    for name, _title, place, source, expected, _ in data.NAIROBI_PEOPLE:
        obs = by_id[names[name]]
        assert obs.source == source
        assert obs.place_label == place
        assert confidence(obs.source, obs.raw, obs.observed_at, w.as_of) == expected, name


def test_named_staff_elsewhere_score_their_demo_confidence() -> None:
    w = world.build(DAY, TENANT)
    by_id = {o.person_id: o for o in w.observations}
    names = {p.full_name: p.id for p in w.persons}
    for name, _title, _city, _place, source, expected in data.OTHER_NAMED:
        obs = by_id[names[name]]
        assert (obs.source, confidence(obs.source, obs.raw, obs.observed_at, w.as_of)) == (
            source,
            expected,
        ), name


def test_advisory_templates_need_native_review_except_english() -> None:
    advisory = data.CITIZEN_ADVISORY
    assert set(advisory) == {"en", "ar", "fr", "sw"}
    assert not advisory["en"].startswith(data.REVIEW_REQUIRED)
    for lang in ("ar", "fr", "sw"):
        assert advisory[lang].startswith(data.REVIEW_REQUIRED), lang
