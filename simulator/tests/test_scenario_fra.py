"""FRA-NATIONAL-PROTESTS content (the database play-through is test_fusion_fra.py)."""

import uuid
from datetime import date

from nexira_sim.scenarios import fra_national_protests as fra
from nexira_sim.seed import data, world

TENANT = uuid.UUID("11111111-2222-3333-4444-555555555555")
EVENTS = fra.build_events(world.build(date(2026, 10, 20), TENANT), TENANT)


def test_every_scene_0_to_3_has_a_marker_and_the_build_is_deterministic() -> None:
    markers = sorted(e.scene_no for e in EVENTS if e.event_type == "SCENE_START")
    assert markers == [0, 1, 2, 3]
    assert fra.build_events(world.build(date(2026, 10, 20), TENANT), TENANT) == EVENTS


def test_every_signal_maps_through_its_own_source() -> None:
    """D-11: an unmapped category or severity would be discarded, never guessed."""
    sources = {code: (sev, cat) for code, _n, _r, sev, cat, _e, _f in data.SOURCES}
    for e in EVENTS:
        if e.event_type != "RAW_SIGNAL":
            continue
        severity_map, category_map = sources[str(e.payload["source_code"])]
        assert str(e.payload["provider_category"]) in category_map, e.payload["external_id"]
        assert str(e.payload["provider_severity"]) in severity_map, e.payload["external_id"]


def test_no_real_person_is_named() -> None:
    """The texts paraphrase public reports; nobody is named (AGENTS.md)."""
    text = " ".join(fra.TITLES.values()) + fra.DESCRIPTION
    for name in ("Macron", "Nuñez", "Nunez", "Lecornu", "Bayrou"):
        assert name not in text
