"""NBO-FLEET: Nairobi's vehicles during the unrest (Fleet & Assets, D-41, FLT-08;
docs/plan-pilot-flt.md §9).

Played while INC-<year>-1042 is ACTIVE (after NBO-CIVIL-UNREST scene 2). Scene 0 puts VH-04
back at the Ambassador's Residence, so a replay starts from the same place. Scene 1: its
simulated telematics drive it off the residence site along Waiyaki Way to Uhuru Highway, into
the impact zone (a FLEET timeline entry). Scene 2: it turns back to the residence and leaves
the zone (a second entry). Scene 3: the simulated workshop reports VH-05's brake service done
and VH-05 is available again; that is final, as a real repair (G-9). Without an ACTIVE
incident the positions still move and no entry is written. Everything is simulated; nobody
real is named. Every scene starts with a SCENE_START marker.
"""

import uuid

from app.modules.scenarios.service import EventIn

from nexira_sim.seed import data
from nexira_sim.seed.ids import seed_id
from nexira_sim.seed.world import World

CODE = "NBO-FLEET"
NAME = "Nairobi fleet"
DESCRIPTION = (
    "Fleet & Assets: during the Nairobi unrest the pickup VH-04 drives into the impact zone "
    "and back, then the sedan VH-05 returns from the workshop. Simulated."
)
VEHICLE = "VH-04"
SCENES = [
    (0, "Ready", "VH-04 at the Ambassador's Residence (play NBO-CIVIL-UNREST to scene 2 first)"),
    (1, "Into the zone", "VH-04 drives off the residence into the impact zone"),
    (2, "Back out", "VH-04 turns back to the residence and leaves the zone"),
    (3, "Workshop", "VH-05's brake service is done; it is available again"),
]
STEP_MS = 2_000
RESIDENCE = (data.RESIDENCE[0], data.RESIDENCE[1], "Residence")
# Scene 1: the first point is still at the residence gate (within 150 m, G-1); the second
# leaves the site, inside the zone.
OUT = [
    (-1.2745, 36.7945, "Residence gate"),
    (-1.2740, 36.7985, "Waiyaki Way"),
    (-1.2770, 36.8060, "Waiyaki Way · Westlands"),
    (-1.2810, 36.8130, "Museum Hill"),
    (-1.2860, 36.8200, "Uhuru Highway"),
]
BACK = [
    (-1.2810, 36.8130, "Museum Hill"),
    (-1.2770, 36.8060, "Waiyaki Way · Westlands"),
    (-1.2740, 36.7985, "Waiyaki Way"),
    RESIDENCE,
]
FUEL_START = 64
WORKSHOP = ("VH-05", "Brake service")


def _position(
    tenant_id: uuid.UUID, scene: int, n: int, point: tuple[float, float, str], fuel: int
) -> EventIn:
    lat, lon, label = point
    return EventIn(
        id=seed_id(tenant_id, "scenario_event", f"{CODE}:position:{scene}:{n}"),
        scene_no=scene,
        offset_ms=STEP_MS * n,
        event_type="VEHICLE_POSITION",
        payload={"asset_code": VEHICLE, "lat": lat, "lon": lon, "label": label, "fuel_pct": fuel},
    )


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
    events.append(_position(tenant_id, 0, 1, RESIDENCE, FUEL_START))
    route = [(1, n, p) for n, p in enumerate(OUT, start=1)] + [
        (2, n, p) for n, p in enumerate(BACK, start=1)
    ]
    for i, (scene, n, point) in enumerate(route):
        events.append(_position(tenant_id, scene, n, point, FUEL_START - 1 - i // 3))
    code, task = WORKSHOP
    events.append(
        EventIn(
            id=seed_id(tenant_id, "scenario_event", f"{CODE}:workshop"),
            scene_no=3,
            offset_ms=STEP_MS,
            event_type="WORKSHOP_DONE",
            payload={"asset_code": code, "task": task},
        )
    )
    return events
