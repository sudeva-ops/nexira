"""NBO-CIVIL-UNREST, the Phase 1 acceptance scenario (decisions.md §7).

Only scenes 1 and 4 carry data events. The other scenes are driven by the
platform (exposure, agents) or by logged-in users (approvals, status), so the
player waits there. Every scene starts with a SCENE_START marker that carries its
name and expected result, for the presenter bar and for the acceptance test.
"""

import random
import uuid

from app.modules.scenarios.service import EventIn

from nexira_sim.seed import data
from nexira_sim.seed.ids import seed_id
from nexira_sim.seed.world import World

CODE = "NBO-CIVIL-UNREST"
NAME = "Civil unrest near the Nairobi Embassy"
DESCRIPTION = "Phase 1 acceptance scenario: scenes 0-6 from docs/decisions.md section 7."
CHECKIN_ESCALATE_AFTER_S = 20  # Prompt 5; the platform default is 600 s (D-07)
CHECKIN_CLOCK_SCENE = 4  # the 20 s run from the start of scene 4, not from sending

SCENES = [
    (0, "Calm", "No active incidents; Decision Queue empty; NBO mission LOW"),
    (1, "Signals fused", "One INC-<year>-1042 CIVIL_UNREST, confidence 92; Paris stays separate"),
    (2, "Impact", "229 people, 3 sites, 1 trip; incident CRITICAL; PB-07 proposal pending"),
    (3, "Playbook", "Duty Officer approves PB-07; step 7 needs the Nairobi Head of Mission"),
    (4, "Check-in", "Personnel 15 safe / 1 need help / 1 pending; citizens 168 / 4 / 40"),
    (5, "Decisions", "Two-person rule on START_EVACUATION (test fixture)"),
    (6, "Review", "Incident set to MONITORING; audit chain verifies"),
]

# (key, source code, provider category, provider severity, (lat, lon), place, offset ms)
SIGNALS = [
    (
        "NBO-1",
        "DATAMINR",
        "Protest / Civil Unrest",
        "High",
        data.EPICENTRE,
        "Nairobi CBD · Kenyatta Avenue",
        0,
    ),
    ("NBO-2", "MAX", "Civil Unrest", "Level 4", (-1.2990, 36.8150), "Upper Hill", 45_000),
    ("NBO-3", "RISKLINE", "Unrest", "Moderate", (-1.2864, 36.8172), "Nairobi", 100_000),
    # Control signal (plan G-12): another category and city; must stay separate.
    ("PAR-1", "FACTAL", "Strike", "Moderate", (48.86, 2.35), "Paris", 30_000),
]
TITLES = {
    "NBO-1": "Large crowds and clashes reported near Kenyatta Avenue, Nairobi",
    "NBO-2": "Protest groups moving towards Upper Hill; police deploying tear gas",
    "NBO-3": "Demonstrations in central Nairobi; avoid the CBD",
    "PAR-1": "Rail and metro strike disrupts Paris transport",
}


def _event(
    tenant_id: uuid.UUID,
    key: str,
    scene: int,
    offset_ms: int,
    kind: str,
    payload: dict[str, object],
) -> EventIn:
    return EventIn(
        id=seed_id(tenant_id, "scenario_event", f"{CODE}:{key}"),
        scene_no=scene,
        offset_ms=offset_ms,
        event_type=kind,
        payload=payload,
    )


def build_events(w: World, tenant_id: uuid.UUID) -> list[EventIn]:
    rng = random.Random(42)
    events = [
        _event(tenant_id, f"scene:{n}", n, 0, "SCENE_START", {"name": name, "expect": expect})
        for n, name, expect in SCENES
    ]
    events.append(
        _event(
            tenant_id,
            "settings",
            0,
            0,
            "SCENARIO_SETTINGS",
            {
                "checkin_escalate_after_s": CHECKIN_ESCALATE_AFTER_S,
                "checkin_clock_scene": CHECKIN_CLOCK_SCENE,
            },
        )
    )
    events.append(
        _event(
            tenant_id,
            "checkin:clock",
            CHECKIN_CLOCK_SCENE,
            0,
            "CHECKIN_CLOCK",
            {"escalate_in_s": CHECKIN_ESCALATE_AFTER_S},
        )
    )

    for key, source, category, severity, (lat, lon), place, offset_ms in SIGNALS:
        events.append(
            _event(
                tenant_id,
                f"signal:{key}",
                1,
                offset_ms,
                "RAW_SIGNAL",
                {
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

    # Scene 4 (D-07, CHK-03): every exposed Nairobi person except Hana Takeda answers.
    nbo = next(m for m in w.missions if m.code == "NBO")
    personnel = [p for p in w.persons if p.mission_id == nbo.id and p.person_type != "CITIZEN"]
    citizens = [p for p in w.persons if p.mission_id == nbo.id and p.person_type == "CITIZEN"]
    answers: list[tuple[uuid.UUID, str, str]] = []
    for p in personnel:
        if p.full_name == "Hana Takeda":
            continue  # no response: escalated 20 s into scene 4
        answers.append((p.id, "NEED_HELP" if p.full_name == "Peter Mwangi" else "SAFE", "APP"))
    shuffled = rng.sample(citizens, len(citizens))
    answers += [(p.id, "SAFE", rng.choice(["SMS", "WHATSAPP", "APP"])) for p in shuffled[:168]]
    answers += [(p.id, "NEED_HELP", "SMS") for p in shuffled[168:172]]
    # shuffled[172:] (40 citizens) do not answer.

    for n, (person_id, status, channel) in enumerate(answers):
        events.append(
            _event(
                tenant_id,
                f"checkin:{n}",
                4,
                1_000 + rng.randint(0, 15_000),
                "CHECKIN_RESPONSE",
                {
                    "person_id": str(person_id),
                    "status": status,
                    "channel": channel,
                    # Resolved by the check-in module to this person's open CHECKIN campaign.
                    "campaign": "latest_open_checkin",
                },
            )
        )
    return events
