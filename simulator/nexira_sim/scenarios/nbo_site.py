"""NBO-SITE: the Nairobi embassy during the unrest (Site Twin, D-43, TWN-07;
docs/plan-pilot-twn.md §9).

Played while INC-<year>-1042 is ACTIVE (after NBO-CIVIL-UNREST scene 2), so the embassy is inside
its zone. Scene 1 first puts presence and sensors back as seeded, so a replay starts from the
same place (scene 0 plays only on Play, not on Next; G-9), then the Gate 2 badge reader faults
and camera 7 goes offline: two SITE entries on the incident's timeline. Scene 2: simulated
presence moves nine staff into the safe room, the comms team stays in the IT room, the visitors
are held in the conference room, and Gate 1 locks down. Scene 3: the reader and the camera
recover. Presence and sensors only: it approves nothing and proposes nothing. Nobody real is
named; guards and visitors are labels. Every scene starts with a SCENE_START marker.
"""

import uuid

from app.modules.scenarios.service import EventIn

from nexira_sim.seed import data
from nexira_sim.seed.ids import seed_id
from nexira_sim.seed.world import World

CODE = "NBO-SITE"
NAME = "Nairobi embassy site"
DESCRIPTION = (
    "Site Twin: during the Nairobi unrest the embassy's Gate 2 reader faults, staff shelter in "
    "the safe room and visitors are held, then the systems recover. Simulated."
)
SCENES = [
    (0, "Ready", "25 on site, 43 / 43 sensors (play NBO-CIVIL-UNREST to scene 2 first)"),
    (1, "Faults", "Gate 2 badge reader in FAULT, a camera offline: 41 / 43"),
    (2, "Shelter", "9 staff in the safe room, visitors held in the conference room"),
    (3, "Recovery", "Gate 2 reader and the camera back online: 43 / 43"),
]
STEP_MS = 250
GATE_1 = ("G1-MAIN", "OK")
OPEN, LOCKED = "Open · screening", "Locked down"
FAULTS = [("G2-READER", "FAULT", "Fault · manual guard"), ("CAM-07", "OFFLINE", "Offline")]
RECOVERY = [("G2-READER", "OK", "Online"), ("CAM-07", "OK", None), ("G1-MAIN", "OK", OPEN)]


def occupants(w: World) -> list[tuple[str, str, str]]:
    """(occupant, normal zone, shelter zone): a staff member's person id, or a label."""
    ids = {p.full_name: p.id for p in w.persons}
    return [(str(ids[name]), normal, shelter) for name, normal, shelter in data.TWIN_STAFF] + [
        (label, normal, shelter) for label, normal, shelter in data.TWIN_LABELS
    ]


def build_events(w: World, tenant_id: uuid.UUID) -> list[EventIn]:
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

    def add(scene: int, key: str, event_type: str, payload: dict[str, object]) -> None:
        step = sum(1 for e in events if e.scene_no == scene)
        events.append(
            EventIn(
                id=seed_id(tenant_id, "scenario_event", f"{CODE}:{scene}:{key}"),
                scene_no=scene,
                offset_ms=STEP_MS * step,
                event_type=event_type,
                payload={"site": data.TWIN_SITE, **payload},
            )
        )

    def sensor(scene: int, code: str, status: str, detail: str | None) -> None:
        payload: dict[str, object] = {"code": code, "status": status}
        if detail is not None:
            payload["detail"] = detail
        add(scene, f"sensor:{code}:{status}", "SITE_SENSOR", payload)

    moved = [(o, normal, shelter) for o, normal, shelter in occupants(w) if normal != shelter]
    # Scene 1: back to the seed (G-9), then the faults.
    for occupant, normal, _ in moved:
        add(1, f"reset:{occupant}", "SITE_PRESENCE", {"occupant": occupant, "zone": normal})
    for code, status, detail in RECOVERY:
        sensor(1, code, status, detail)
    for code, status, detail in FAULTS:
        sensor(1, code, status, detail)
    # Scene 2: shelter.
    for occupant, _, shelter in moved:
        add(2, f"shelter:{occupant}", "SITE_PRESENCE", {"occupant": occupant, "zone": shelter})
    sensor(2, *GATE_1, LOCKED)
    # Scene 3: recovery.
    for code, status, detail in RECOVERY:
        sensor(3, code, status, detail)
    return events
