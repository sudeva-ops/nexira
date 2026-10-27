"""NBO-AIR-DIVERSION: an inbound flight diverted from Nairobi (Air Travel Tracking,
D-33, docs/plan-pilot-air.md G-2).

XW 451 (Abu Dhabi -> Nairobi) carries three London staff on the seeded TRP-8818. It is a
SCENARIO flight (plan G-3): only these FLIGHT_FEED events change its status, with times
relative to when each event arrives, so the demo can run at any time of day. It can be
played during or after NBO-CIVIL-UNREST; it does not change that scenario.
"""

import uuid

from app.modules.scenarios.service import EventIn

from nexira_sim.seed.ids import seed_id
from nexira_sim.seed.world import World

CODE = "NBO-AIR-DIVERSION"
NAME = "Inbound flight diverted from Nairobi"
DESCRIPTION = "Air Travel Tracking: XW 451 holds near Nairobi, diverts to Mombasa and lands."
FLIGHT = "XW 451"
LANDED_AFTER_MS = 60_000

SCENES = [
    (0, "Scheduled", "XW 451 Abu Dhabi -> Nairobi scheduled with 3 London staff (TRP-8818)"),
    (1, "Inbound", "XW 451 airborne, about 10 minutes from Nairobi"),
    (2, "Holding", "XW 451 HOLDING near Nairobi: arrivals restricted"),
    (3, "Diverted", "XW 451 DIVERTED to Mombasa, then LANDED; its travellers are in Mombasa"),
]

# (key, scene, offset ms, change)
FEED: list[tuple[str, int, int, dict[str, object]]] = [
    ("airborne", 1, 0, {"status": "AIRBORNE", "departed_min_ago": 230, "arrives_in_min": 10}),
    (
        "holding",
        2,
        0,
        {
            "status": "HOLDING",
            "reason": "Arrivals restricted: airport access roads affected by unrest (simulated)",
        },
    ),
    (
        "diverted",
        3,
        0,
        {
            "status": "DIVERTED",
            "to": "MBA",
            "arrives_in_min": 1,
            "reason": "Nairobi arrivals suspended (simulated)",
        },
    ),
    ("landed", 3, LANDED_AFTER_MS, {"status": "LANDED"}),
]


def build_events(w: World, tenant_id: uuid.UUID) -> list[EventIn]:
    """XW 451 departs on the scenario date (home zone), so the feed names that date."""
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
    for key, scene, offset_ms, change in FEED:
        events.append(
            EventIn(
                id=seed_id(tenant_id, "scenario_event", f"{CODE}:feed:{key}"),
                scene_no=scene,
                offset_ms=offset_ms,
                event_type="FLIGHT_FEED",
                payload={"flight_number": FLIGHT, "date": w.scenario_date.isoformat(), **change},
            )
        )
    return events
