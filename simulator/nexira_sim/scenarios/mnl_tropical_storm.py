"""MNL-TROPICAL-STORM: a tropical storm approaches Manila (Weather, D-35, WX-07;
docs/plan-pilot-wx.md §5).

Manila's conditions worsen (WEATHER_FEED events, held against the routine feed for 6
hours, plan G-1), then xWeather warnings arrive as signals. The platform does the rest
through the existing pipeline: a 60 km STORM incident that exposes the Manila mission
(WX-04), PB-06 proposed by the Response Planner (WX-05), and the seeded TRP-8810 shown as
impacted (WX-06). Everything is simulated; nobody real is named. Every scene starts with a
SCENE_START marker for the presenter bar.
"""

import uuid

from app.modules.scenarios.service import EventIn

from nexira_sim.seed.ids import seed_id
from nexira_sim.seed.world import World

CODE = "MNL-TROPICAL-STORM"
NAME = "Tropical storm approaching Manila"
DESCRIPTION = (
    "Weather: conditions in Manila worsen, then xWeather storm and flood warnings arrive and "
    "the platform responds (PB-06). Simulated conditions and signals."
)
MISSION = "MNL"

SCENES = [
    (0, "Calm", "Manila's normal conditions; no weather incident"),
    (1, "Building", "Manila cloudy, wind 45 km/h, gusts 65"),
    (
        2,
        "Warning",
        "Manila stormy; one STORM incident (xWeather and Dataminr fused, 60 km), CRITICAL, Manila "
        "mission exposed; PB-06 proposed; TRP-8810 impacted",
    ),
    (3, "Landfall", "A separate FLOOD incident in the city (25 km), with its own exposure"),
]

# (key, scene, offset ms, conditions)
WEATHER: list[tuple[str, int, int, dict[str, object]]] = [
    (
        "building",
        1,
        0,
        {"condition": "CLOUD", "temperature_c": 28.5, "wind_kph": 45, "gust_kph": 65, "rain_mm": 2},
    ),
    (
        "storm",
        2,
        0,
        {
            "condition": "STORM",
            "temperature_c": 26.0,
            "wind_kph": 110,
            "gust_kph": 150,
            "rain_mm": 60,
        },
    ),
]

# (key, scene, offset ms, source, provider category, provider severity, (lat, lon), place)
SIGNALS = [
    # Scene 2: the storm's centre 40 km east of Manila, then a second provider within 60 km.
    (
        "STORM-XW",
        2,
        5_000,
        "XWEATHER",
        "Storm",
        "Severe",
        (14.6, 121.35),
        "Rizal · 40 km east of Manila",
    ),
    (
        "STORM-DM",
        2,
        25_000,
        "DATAMINR",
        "Tropical storm",
        "Critical",
        (14.58, 121.2),
        "Antipolo · east of Manila",
    ),
    # Scene 3: flooding in the city itself (a different category: a separate incident).
    (
        "FLOOD-XW",
        3,
        0,
        "XWEATHER",
        "Flood",
        "Major",
        (14.59, 120.98),
        "Manila · Ermita and the bay",
    ),
]
TITLES = {
    "STORM-XW": "Tropical storm warning: sustained winds 110 km/h, gusts 150 km/h, heavy rain",
    "STORM-DM": "Reports of a tropical storm making landfall east of Metro Manila",
    "FLOOD-XW": "Flood warning: rising water in low-lying districts along Manila Bay",
}


# An exercise template (plan-pilot-exr §2, G-1): scene 0's marker names the mission.
TEMPLATE = {"mission": "MNL", "theme": "Natural hazard"}


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
    for key, scene, offset_ms, change in WEATHER:
        events.append(
            EventIn(
                id=seed_id(tenant_id, "scenario_event", f"{CODE}:weather:{key}"),
                scene_no=scene,
                offset_ms=offset_ms,
                event_type="WEATHER_FEED",
                payload={"mission_code": MISSION, **change},
            )
        )
    for key, scene, offset_ms, source, category, severity, (lat, lon), place in SIGNALS:
        events.append(
            EventIn(
                id=seed_id(tenant_id, "scenario_event", f"{CODE}:signal:{key}"),
                scene_no=scene,
                offset_ms=offset_ms,
                event_type="RAW_SIGNAL",
                payload={
                    "source_code": source,
                    "external_id": f"{CODE}:{key}",  # the player appends the run id
                    "title": TITLES[key],
                    "provider_category": category,
                    "provider_severity": severity,
                    "lat": lat,
                    "lon": lon,
                    "place_label": place,
                    "language": "en",
                },
            )
        )
    return events
