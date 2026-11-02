"""ADD-VISIT: the Minister's visit to Addis Ababa (VIP & Delegation Protection, D-42, VIP-08;
docs/plan-pilot-vip.md §9).

Scene 1: simulated programme progress starts the visit (LIVE), completes the arrival and starts
the motorcade. Scene 2: a simulated planned-rally signal 1.2 km from the industrial park; fusion
opens an incident and the site visit's risk turns HIGH. Scene 3: the motorcade, the bilateral
meeting and the business forum complete. Programme status only, never a position (VIP-04). The
change to the site visit is proposed and decided by people in the browser; the scenario
approves nothing. The rally is MODERATE and no site or person is near it, so PB-07 (HIGH civil
unrest near staff) is not proposed. A replay needs `make reset-demo` (a live visit stays
live). Every scene starts with a SCENE_START marker; scene texts name no venue or time
(the presenter bar is open to non-readers, VIP-06).
"""

import uuid

from app.modules.scenarios.service import EventIn

from nexira_sim.seed import data
from nexira_sim.seed.ids import seed_id
from nexira_sim.seed.world import World

CODE = "ADD-VISIT"
NAME = "Addis Ababa visit"
DESCRIPTION = (
    "VIP & Delegation Protection: a restricted visit goes live, a planned rally raises one "
    "segment's risk, and the programme moves on. Programme status only. Simulated."
)
SCENES = [
    (0, "Planned", "The visit planned, risk MODERATE (open VIP Protection)"),
    (1, "Live", "The visit LIVE: first segment completed, the second in progress"),
    (2, "Rally", "A planned-rally signal opens an incident; one segment HIGH"),
    (3, "Forum", "Segments 2-4 completed"),
]
STEP_MS = 3_000
RALLY = (data.INDUSTRIAL_PARK[0] + 0.01078, data.INDUSTRIAL_PARK[1])  # 1.2 km north
# Scene 1, then scene 3: (segment seq or None for the visit, status).
LIVE = [(None, "LIVE"), (1, "IN_PROGRESS"), (1, "COMPLETED"), (2, "IN_PROGRESS")]
FORUM = [
    (2, "COMPLETED"),
    (3, "IN_PROGRESS"),
    (3, "COMPLETED"),
    (4, "IN_PROGRESS"),
    (4, "COMPLETED"),
]


def reference(w: World) -> str:
    return f"VV-{w.scenario_date.year}-{data.VIP_REFERENCE_NO:03d}"


def _progress(
    w: World, tenant_id: uuid.UUID, scene: int, n: int, step: tuple[int | None, str]
) -> EventIn:
    seq, status = step
    payload: dict[str, object] = {"visit": reference(w), "status": status}
    if seq is not None:
        payload["seq"] = seq
    return EventIn(
        id=seed_id(tenant_id, "scenario_event", f"{CODE}:progress:{scene}:{n}"),
        scene_no=scene,
        offset_ms=STEP_MS * n,
        event_type="VIP_PROGRESS",
        payload=payload,
    )


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
    events += [_progress(w, tenant_id, 1, n, step) for n, step in enumerate(LIVE, start=1)]
    events.append(
        EventIn(
            id=seed_id(tenant_id, "scenario_event", f"{CODE}:signal:rally"),
            scene_no=2,
            offset_ms=STEP_MS,
            event_type="RAW_SIGNAL",
            payload={
                "source_code": "DATAMINR",
                "external_id": f"{CODE}:rally",  # the player appends the run id
                "title": "Planned rally · industrial park access road",
                "provider_category": "Protest / Civil Unrest",
                "provider_severity": "Medium",
                "lat": RALLY[0],
                "lon": RALLY[1],
                "place_label": "Addis Ababa · industrial park access road",
                "language": "en",
            },
        )
    )
    events += [_progress(w, tenant_id, 3, n, step) for n, step in enumerate(FORUM, start=1)]
    return events
