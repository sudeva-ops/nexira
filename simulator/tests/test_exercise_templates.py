"""Exercise templates (EXR-01; docs/plan-pilot-exr.md §2, G-1): four scenarios name their
mission and theme on scene 0's marker; the add-on scenarios, which act on an incident another
scenario opened, do not."""

import uuid
from datetime import date
from typing import Any, Protocol

from app.modules.scenarios.service import EventIn

from nexira_sim.scenarios import (
    add_forecast,
    add_visit,
    dac_cyclone,
    fra_national_protests,
    mnl_tropical_storm,
    nbo_air_diversion,
    nbo_cholera,
    nbo_civil_unrest,
    nbo_evacuation,
    nbo_fleet,
    nbo_site,
    nbo_supply,
)
from nexira_sim.seed import world
from nexira_sim.seed.world import World

TENANT = uuid.UUID("11111111-2222-3333-4444-777777777777")
W = world.build(date(2026, 11, 10), TENANT)


class Scenario(Protocol):
    CODE: str

    def build_events(self, w: World, tenant_id: uuid.UUID, /) -> list[EventIn]: ...


def _template(scenario: Scenario) -> Any:
    markers = [e for e in scenario.build_events(W, TENANT) if e.event_type == "SCENE_START"]
    assert all("template" not in e.payload for e in markers if e.scene_no != 0)
    return next(e.payload.get("template") for e in markers if e.scene_no == 0)


def test_four_templates_name_their_mission_and_theme() -> None:
    templates: list[Scenario] = [
        nbo_civil_unrest,
        fra_national_protests,
        dac_cyclone,
        mnl_tropical_storm,
    ]
    assert {s.CODE: _template(s) for s in templates} == {
        "NBO-CIVIL-UNREST": {"mission": "NBO", "theme": "Civil unrest"},
        "FRA-NATIONAL-PROTESTS": {"mission": "PAR", "theme": "Civil unrest"},
        "DAC-CYCLONE": {"mission": "DAC", "theme": "Natural hazard"},
        "MNL-TROPICAL-STORM": {"mission": "MNL", "theme": "Natural hazard"},
    }


def test_the_add_on_scenarios_are_not_templates() -> None:
    add_ons: list[Scenario] = [
        add_forecast,
        add_visit,
        nbo_air_diversion,
        nbo_cholera,
        nbo_evacuation,
        nbo_fleet,
        nbo_site,
        nbo_supply,
    ]
    assert [s.CODE for s in add_ons if _template(s) is not None] == []
