"""NBO-EVACUATION: the Nairobi evacuation, from the muster point to arrival (Evacuation
Management, D-40, EV-10; docs/plan-pilot-ev.md §11).

It continues from NBO-CIVIL-UNREST scene 5, where two people (the Nairobi Head of Mission
and the HQ Crisis Director) activate EVP-NBO; this scenario approves nothing itself (§53
Q10). Scene 1: the simulated muster-point scanner checks two people in every second for 30
seconds. Scenes 2-4: simulated progress moves the sequence to convoy departed, flight
departed and arrival. With no ACTIVE evacuation at Nairobi its events change nothing.
Everything is simulated; nobody real is named. Every scene starts with a SCENE_START marker.
"""

import uuid

from app.modules.scenarios.service import EventIn

from nexira_sim.seed.ids import seed_id
from nexira_sim.seed.world import World

CODE = "NBO-EVACUATION"
NAME = "Nairobi evacuation"
DESCRIPTION = (
    "Evacuation Management: after NBO-CIVIL-UNREST scene 5 activates EVP-NBO, the muster "
    "point checks everyone in, the convoy and the charter leave, and the evacuees arrive in "
    "Dubai. Simulated."
)
MISSION = "NBO"

SCENES = [
    (0, "Ready", "EVP-NBO active from NBO-CIVIL-UNREST scene 5 (play that first)"),
    (1, "Muster", "The muster-point scanner checks everyone in; seats are assigned"),
    (2, "Convoy", "The convoy leaves the Embassy courtyard via Route B"),
    (3, "Charter", "The charter leaves Wilson Airport for Dubai"),
    (4, "Arrival", "The evacuees arrive; the evacuation is complete"),
]
SCAN_EVERY_MS = 1_000
SCANS = 30  # 30 scans of two: everyone on a manifest of up to 60
SCAN_COUNT = 2
PROGRESS = [(2, 4), (3, 5), (4, 6)]  # (scene, step)


def build_events(_w: World, tenant_id: uuid.UUID) -> list[EventIn]:
    """The world is unused; the signature matches the other scenarios."""
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
    events += [
        EventIn(
            id=seed_id(tenant_id, "scenario_event", f"{CODE}:scan:{i}"),
            scene_no=1,
            offset_ms=SCAN_EVERY_MS * i,
            event_type="MUSTER_SCAN",
            payload={"mission_code": MISSION, "count": SCAN_COUNT},
        )
        for i in range(1, SCANS + 1)
    ]
    events += [
        EventIn(
            id=seed_id(tenant_id, "scenario_event", f"{CODE}:step:{step}"),
            scene_no=scene,
            offset_ms=2_000,
            event_type="EVACUATION_PROGRESS",
            payload={"mission_code": MISSION, "step": step},
        )
        for scene, step in PROGRESS
    ]
    return events
