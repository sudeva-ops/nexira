"""NBO-CIVIL-UNREST content (decisions.md §7, Prompt 5)."""

import uuid
from collections import Counter
from datetime import date

from nexira_sim.scenarios import nbo_civil_unrest as nbo
from nexira_sim.seed import world

TENANT = uuid.UUID("11111111-2222-3333-4444-555555555555")
W = world.build(date(2026, 10, 20), TENANT)
EVENTS = nbo.build_events(W, TENANT)
NAMES = {str(p.id): (p.full_name, p.person_type) for p in W.persons}


def test_build_is_deterministic() -> None:
    assert nbo.build_events(W, TENANT) == EVENTS


def test_every_scene_0_to_6_has_a_marker() -> None:
    markers = sorted(e.scene_no for e in EVENTS if e.event_type == "SCENE_START")
    assert markers == list(range(7))


def test_checkin_escalation_setting_is_20_seconds() -> None:
    settings = [e for e in EVENTS if e.event_type == "SCENARIO_SETTINGS"]
    assert [s.payload for s in settings] == [{"checkin_escalate_after_s": 20}]


def test_scene_1_has_three_nairobi_signals_within_two_minutes_and_paris() -> None:
    signals = [e for e in EVENTS if e.event_type == "RAW_SIGNAL"]
    assert {e.scene_no for e in signals} == {1}
    nairobi = [e for e in signals if e.payload["place_label"] != "Paris"]
    assert [e.payload["source_code"] for e in nairobi] == ["DATAMINR", "MAX", "RISKLINE"]
    assert max(e.offset_ms for e in nairobi) <= 120_000
    assert [e.payload["provider_severity"] for e in nairobi] == ["High", "Level 4", "Moderate"]
    paris = [e for e in signals if e.payload["place_label"] == "Paris"]
    assert len(paris) == 1
    assert paris[0].payload["provider_category"] == "Strike"


def test_scene_4_checkin_answers_match_section_7() -> None:
    answers = [e for e in EVENTS if e.event_type == "CHECKIN_RESPONSE"]
    assert {e.scene_no for e in answers} == {4}
    personnel: Counter[str] = Counter()
    citizens: Counter[str] = Counter()
    by_name: dict[str, str] = {}
    for e in answers:
        name, ptype = NAMES[str(e.payload["person_id"])]
        (citizens if ptype == "CITIZEN" else personnel)[str(e.payload["status"])] += 1
        by_name[name] = str(e.payload["status"])
    assert personnel == {"SAFE": 15, "NEED_HELP": 1}  # + Hana Takeda pending = 17
    assert citizens == {"SAFE": 168, "NEED_HELP": 4}  # + 40 pending = 212
    assert by_name["Peter Mwangi"] == "NEED_HELP"
    assert "Hana Takeda" not in by_name
    assert len({e.payload["person_id"] for e in answers}) == len(answers)  # one answer each


def test_event_ids_are_unique_and_tenant_specific() -> None:
    ids = [e.id for e in EVENTS]
    assert len(set(ids)) == len(ids)
    other = nbo.build_events(world.build(date(2026, 10, 20), uuid.uuid4()), uuid.uuid4())
    assert set(ids).isdisjoint(e.id for e in other)
