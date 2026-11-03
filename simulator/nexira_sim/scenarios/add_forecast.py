"""ADD-FORECAST: a rally announced near the Addis Ababa industrial park (Predictive Risk, D-46,
PRD-08; docs/plan-pilot-prd.md §10).

Scene 1 adds two calendar entries five days after the day it is played: the rally (5,000 people,
weight 30) and a counter-demonstration (weight 10). Addis Ababa's forecast then rises from its
calm 35 to 75 on that day, rising risk lists it first, and the Forecast agent raises advice to
review movements and venues (level 4, naming no VIP visit; G-1). The scenario adds calendar
entries only: it proposes, approves and changes nothing else. Every scene starts with a
SCENE_START marker.
"""

import uuid

from app.modules.scenarios.service import EventIn

from nexira_sim.seed import data
from nexira_sim.seed.ids import seed_id
from nexira_sim.seed.world import World

CODE = "ADD-FORECAST"
NAME = "Addis Ababa forecast"
DESCRIPTION = (
    "Predictive Risk: a rally is announced near the Addis Ababa industrial park; the 14-day "
    "forecast crosses the elevated threshold and the Forecast agent advises a readiness check. "
    "Simulated."
)
SCENES = [
    (0, "Ready", "Addis Ababa forecast below 70 (the calm calendar)"),
    (1, "Rally announced", "Forecast 35 → 75 in five days; advice in the Decision Queue"),
]
RALLY_DAY = 5
CALENDAR = [
    {
        "mission": "ADD",
        "kind": "RALLY",
        "title": "Rally near the industrial park",
        "starts_in_days": RALLY_DAY,
        "weight": 30,
        "attendance": 5000,
        "place_label": "Industrial park access road",
        "lat": data.INDUSTRIAL_PARK[0],
        "lon": data.INDUSTRIAL_PARK[1] - 0.011,  # about 1.2 km west of the park
    },
    {
        "mission": "ADD",
        "kind": "RALLY",
        "title": "Counter-demonstration",
        "starts_in_days": RALLY_DAY,
        "weight": 10,
        "attendance": 800,
        "place_label": "Industrial park access road",
    },
]


def build_events(w: World, tenant_id: uuid.UUID) -> list[EventIn]:
    del w  # the calendar is named by mission code
    events = [
        EventIn(
            id=seed_id(tenant_id, "scenario_event", f"{CODE}:scene:{n}"),
            scene_no=n,
            offset_ms=0,
            event_type="SCENE_START",
            payload={"name": name, "expect": expect},
        )
        for n, name, expect in SCENES
    ]
    for n, payload in enumerate(CALENDAR, start=1):
        events.append(
            EventIn(
                id=seed_id(tenant_id, "scenario_event", f"{CODE}:1:event:{payload['title']}"),
                scene_no=1,
                offset_ms=250 * n,
                event_type="MISSION_EVENT",
                payload=dict(payload),
            )
        )
    return events
