"""DAC-CYCLONE: a tropical cyclone approaches Dhaka (Natural Hazards & Climate, D-38, HZ-11;
docs/plan-pilot-hz.md §9).

Scene 1 brings the design's background hazard events, so `make reset-demo` still starts with
no active incident (§43 Q8): an M5.2 earthquake 210 km from Ankara (LOW, outside its range),
river flooding in Jakarta, extreme heat in Riyadh, poor air quality in New Delhi, a wildfire
with no mission within 300 km, and a Category 1 forecast for Dhaka. Scene 2 upgrades it to
Category 2, landfall in 60 h: the Response Planner proposes arming PB-06 (HZ-06). Scenes 3
and 4 move the demo clock on (G-9): at 36 h before landfall the armed PB-06 starts by
itself, then landfall floods the city. Scene 5: the cyclone weakens. Every signal and
measure is simulated; nobody real is named. Every scene starts with a SCENE_START marker.
"""

import uuid
from typing import Any

from app.modules.scenarios.service import EventIn

from nexira_sim.seed.ids import seed_id
from nexira_sim.seed.world import World

CODE = "DAC-CYCLONE"
NAME = "Tropical cyclone approaching Dhaka"
DESCRIPTION = (
    "Natural hazards: background events at five missions, then a cyclone forecast for Dhaka. "
    "PB-06 is armed for 36 h before landfall and starts by itself. Simulated feeds."
)
LANDFALL = (22.815, 90.41)  # the Barishal coast, 110 km south of the Dhaka mission
LANDFALL_PLACE = "Bay of Bengal · Barishal coast, 110 km south of Dhaka"

SCENES = [
    (0, "Calm", "No hazard events"),
    (
        1,
        "Background",
        "Six hazard events: Ankara earthquake LOW and out of range, Jakarta flood, Riyadh heat, "
        "New Delhi air quality, a wildfire with no mission within 300 km, a Category 1 forecast "
        "for Dhaka",
    ),
    (
        2,
        "Upgrade",
        "Category 2, landfall in 60 h; the Dhaka mission exposed; the Response Planner proposes "
        "arming PB-06",
    ),
    (3, "36 h to landfall", "Demo clock +24 h: the armed PB-06 starts by itself"),
    (4, "Landfall", "Demo clock +36 h: flooding in Dhaka, a separate FLOOD incident"),
    (5, "Weakening", "The cyclone weakens to Category 1"),
]

# (key, scene, offset ms, source, provider category, provider severity, (lat, lon), place,
#  hazard measure or None)
SIGNALS: list[
    tuple[str, int, int, str, str, str, tuple[float, float], str, dict[str, Any] | None]
] = [
    (
        "QUAKE-ANK",
        1,
        2_000,
        "SEISMIC",
        "Earthquake",
        "M5.2",
        (38.03, 32.86),
        "Central Anatolia · 210 km south of Ankara",
        {"magnitude": 5.2, "depth_km": 10},
    ),
    (
        "FLOOD-JKT",
        1,
        4_000,
        "XWEATHER",
        "Flood",
        "Moderate",
        (-6.21, 106.86),
        "Jakarta · Ciliwung river",
        None,
    ),
    (
        "HEAT-RUH",
        1,
        6_000,
        "XWEATHER",
        "Extreme heat",
        "Moderate",
        (24.71, 46.68),
        "Riyadh · 46 °C",
        None,
    ),
    (
        "AIR-DEL",
        1,
        8_000,
        "AIRQ",
        "Air quality",
        "AQI 310",
        (28.63, 77.22),
        "New Delhi · AQI 310",
        {"aqi": 310},
    ),
    (
        "FIRE-ATT",
        1,
        10_000,
        "XWEATHER",
        "Wildfire",
        "Moderate",
        (38.10, 23.80),
        "Attica, Greece",
        None,
    ),
    (
        "CYCLONE-1",
        1,
        12_000,
        "XWEATHER",
        "Tropical cyclone",
        "Moderate",
        LANDFALL,
        LANDFALL_PLACE,
        {"cyclone_category": 1, "landfall_in_h": 72, "track_km": 160},
    ),
    (
        "CYCLONE-2",
        2,
        2_000,
        "XWEATHER",
        "Tropical cyclone",
        "Major",
        LANDFALL,
        LANDFALL_PLACE,
        {"cyclone_category": 2, "landfall_in_h": 60, "track_km": 110},
    ),
    (
        "FLOOD-DAC",
        4,
        3_000,
        "XWEATHER",
        "Flood",
        "Major",
        (23.76, 90.40),
        "Dhaka · low-lying wards",
        None,
    ),
    (
        "CYCLONE-W",
        5,
        2_000,
        "XWEATHER",
        "Tropical cyclone",
        "Moderate",
        LANDFALL,
        LANDFALL_PLACE,
        {"cyclone_category": 1, "landfall_in_h": 0, "track_km": 110},
    ),
]
TITLES = {
    "QUAKE-ANK": "Earthquake M5.2, depth 10 km, central Anatolia",
    "FLOOD-JKT": "River flooding along the Ciliwung in Jakarta",
    "HEAT-RUH": "Extreme heat warning: 46 °C in Riyadh",
    "AIR-DEL": "Very poor air quality in New Delhi: AQI 310",
    "FIRE-ATT": "Wildfire risk: active fires in Attica",
    "CYCLONE-1": "Tropical cyclone forecast (Category 1): landfall Bay of Bengal in 72 h",
    "CYCLONE-2": "Cyclone upgraded to Category 2: landfall near Barishal in 60 h",
    "FLOOD-DAC": "Flooding in Dhaka's low-lying wards after landfall",
    "CYCLONE-W": "Cyclone weakens to Category 1 inland",
}
# (key, scene, offset ms, hours): the demo clock (plan-pilot-hz §5, G-9).
CLOCK = [("36H", 3, 1_000, 24), ("LANDFALL", 4, 1_000, 36)]


# An exercise template (plan-pilot-exr §2, G-1): scene 0's marker names the mission.
TEMPLATE = {"mission": "DAC", "theme": "Natural hazard"}


def _marker(n: int, name: str, expect: str) -> dict[str, object]:
    return {"name": name, "expect": expect, **({"template": TEMPLATE} if n == 0 else {})}


def build_events(_w: World, tenant_id: uuid.UUID) -> list[EventIn]:
    """The world is unused; the signature matches the other scenarios."""
    events = [
        EventIn(
            id=seed_id(tenant_id, "scenario_event", f"{CODE}:scene:{n}"),
            scene_no=n,
            offset_ms=0,
            event_type="SCENE_START",
            payload=_marker(n, name, expect),
        )
        for n, name, expect in SCENES
    ]
    for key, scene, offset_ms, hours in CLOCK:
        events.append(
            EventIn(
                id=seed_id(tenant_id, "scenario_event", f"{CODE}:clock:{key}"),
                scene_no=scene,
                offset_ms=offset_ms,
                event_type="DEMO_CLOCK",
                payload={"advance_h": hours},
            )
        )
    for key, scene, offset_ms, source, category, severity, (lat, lon), place, hazard in SIGNALS:
        payload: dict[str, Any] = {
            "source_code": source,
            "external_id": f"{CODE}:{key}",  # the player appends the run id
            "title": TITLES[key],
            "provider_category": category,
            "provider_severity": severity,
            "lat": lat,
            "lon": lon,
            "place_label": place,
            "language": "en",
        }
        if hazard is not None:
            payload["hazard"] = hazard
        events.append(
            EventIn(
                id=seed_id(tenant_id, "scenario_event", f"{CODE}:signal:{key}"),
                scene_no=scene,
                offset_ms=offset_ms,
                event_type="RAW_SIGNAL",
                payload=payload,
            )
        )
    return events
