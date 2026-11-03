"""NBO-SUPPLY: Nairobi's third parties during the unrest (Supply Chain, D-44, SUP-07;
docs/plan-pilot-sup.md §8).

Played while INC-<year>-1042 is ACTIVE (after NBO-CIVIL-UNREST scene 2). Scene 1 first puts
Nairobi's routes and suppliers back as seeded, so a replay starts from the same place (G-6; a
report of the same status writes nothing), then the pouch route via the CBD is blocked. Scene 2:
the fuel delivery is postponed and the guard-force shift change is at risk. Scene 3: the routes
reopen and the suppliers report normal. Reported statuses only: it activates no mitigation,
approves nothing and proposes nothing; people mitigate in the browser. Every scene starts with a
SCENE_START marker.
"""

import uuid

from app.modules.scenarios.service import EventIn

from nexira_sim.seed.ids import seed_id
from nexira_sim.seed.world import World

CODE = "NBO-SUPPLY"
NAME = "Nairobi supply chain"
DESCRIPTION = (
    "Supply Chain: during the Nairobi unrest the pouch route is blocked, the fuel delivery is "
    "delayed and the guard shift change is at risk, then all recover. Simulated."
)
SCENES = [
    (0, "Ready", "52 third parties, none impacted (play NBO-CIVIL-UNREST to scene 2 first)"),
    (1, "Pouch blocked", "Pouch route via CBD blocked: Swiftline Couriers ROUTE BLOCKED"),
    (2, "Fuel and guards", "3 third parties impacted: fuel delayed, guard shift at risk"),
    (3, "Recovery", "Routes reopen, suppliers normal: none impacted"),
]
STEP_MS = 250
ROUTES = ("R-NBO-1", "R-NBO-2", "R-NBO-3", "R-NBO-4")
SUPPLIERS = ("SUP-104", "SUP-117", "SUP-121", "SUP-126", "SUP-130")
ROAD_CLOSED = "Road closure CBD → JKIA; reroute via Southern Bypass, +55 min"
FUEL = ("SUP-121", "DELAYED", "Fuel delivery postponed 24 h")
GUARDS = ("SUP-117", "AT_RISK", "18:00 shift change: 6 guards must cross the impact zone")


def build_events(w: World, tenant_id: uuid.UUID) -> list[EventIn]:
    del w  # the routes and suppliers are named by code
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
                payload=payload,
            )
        )

    def route(scene: int, code: str, status: str, detail: str | None = None) -> None:
        payload: dict[str, object] = {"route": code, "status": status}
        if detail is not None:
            payload["detail"] = detail
        add(scene, f"route:{code}:{status}", "SUPPLY_ROUTE", payload)

    def notice(scene: int, code: str, status: str, detail: str | None = None) -> None:
        payload: dict[str, object] = {"supplier": code, "status": status}
        if detail is not None:
            payload["detail"] = detail
        add(scene, f"supplier:{code}:{status}", "SUPPLY_SUPPLIER", payload)

    # Scene 1: back to the seed (G-6), then the pouch route via the CBD is blocked.
    for code in ROUTES:
        route(1, code, "OPEN")
    for code in SUPPLIERS:
        notice(1, code, "NORMAL")
    route(1, "R-NBO-1", "BLOCKED", ROAD_CLOSED)
    # Scene 2: fuel and the guards.
    notice(2, *FUEL)
    route(2, "R-NBO-3", "DELAYED", "Delivery postponed 24 h")
    notice(2, *GUARDS)
    route(2, "R-NBO-4", "RESTRICTED", "Restricted: route crosses the impact zone")
    # Scene 3: recovery.
    for code in ("R-NBO-1", "R-NBO-3", "R-NBO-4"):
        route(3, code, "OPEN")
    for code in ("SUP-121", "SUP-117"):
        notice(3, code, "NORMAL")
    return events
