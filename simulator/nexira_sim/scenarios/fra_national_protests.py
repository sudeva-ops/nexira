"""FRA-NATIONAL-PROTESTS: nationwide protests in France (demo scenario).

Modelled on the protests reported in France in October 2026: a movement that began
with high-school students protesting school conditions (teacher shortages,
run-down buildings) and widened into protests over the cost of living, with
trade unions and student groups. Hundreds of thousands marched on 17 and 24
October. There were clashes in Paris and other cities, city halls were set on
fire, some marches were banned, and many people were detained.

The places and the kind of events follow those public reports. The signals
themselves are simulated: the provider texts are paraphrased, not quoted, and no
real person is named. Everyone NEXIRA tracks (staff, citizens, travellers) is
fictional seed data, as everywhere else in the demo.

Only scenes 1-3 carry data events. The platform does the rest: fusion, exposure
(the Paris embassy is inside the impact radius, so the incident becomes CRITICAL)
and the agents' proposals. Every scene starts with a SCENE_START marker for the
presenter bar.
"""

import uuid

from app.modules.scenarios.service import EventIn

from nexira_sim.seed.ids import seed_id
from nexira_sim.seed.world import World

CODE = "FRA-NATIONAL-PROTESTS"
NAME = "Nationwide protests in France"
DESCRIPTION = (
    "Demo scenario modelled on the October 2026 protests in France: student-led "
    "marches over school conditions and the cost of living, clashes in Paris and "
    "other cities. Simulated signals; all tracked people are fictional."
)

SCENES = [
    (0, "Calm", "No active incidents in France; PAR mission LOW"),
    (
        1,
        "Paris marches",
        "One Paris CIVIL_UNREST incident, confidence 92; embassy exposed, so CRITICAL; PB-07 "
        "proposed, with the Paris staff alert and citizen advisory (D-31)",
    ),
    (
        2,
        "Nationwide",
        "Separate incidents in Nantes, Lyon and Marseille (no mission nearby); "
        "a Paris transport disruption stays separate",
    ),
    (3, "Second day", "A fourth source joins the Paris incident: confidence 96"),
]

# (key, scene, offset ms, source code, provider category, provider severity, (lat, lon), place)
SIGNALS = [
    # Scene 1: three providers report the same Paris march (within 3 km: one incident).
    (
        "PAR-REP",
        1,
        0,
        "DATAMINR",
        "Protest / Civil Unrest",
        "High",
        (48.8675, 2.3637),
        "Paris · Place de la République",
    ),
    (
        "PAR-BAS",
        1,
        20_000,
        "MAX",
        "Civil Unrest",
        "Level 4",
        (48.8533, 2.3692),
        "Paris · Place de la Bastille",
    ),
    (
        "PAR-VOL",
        1,
        40_000,
        "RISKLINE",
        "Unrest",
        "Moderate",
        (48.8577, 2.3797),
        "Paris · Boulevard Voltaire",
    ),
    # Scene 2: the movement elsewhere in France, and a separate transport event in Paris.
    ("NTE", 2, 0, "SAMDESK", "Protest", "Major", (47.2184, -1.5536), "Nantes · city centre"),
    (
        "LYS",
        2,
        15_000,
        "DRAGONFLY",
        "Civil unrest",
        "Major",
        (45.7640, 4.8357),
        "Lyon · Presqu'île",
    ),
    ("MRS", 2, 30_000, "FACTAL", "Unrest", "Moderate", (43.2965, 5.3698), "Marseille · Vieux-Port"),
    (
        "PAR-GDL",
        2,
        45_000,
        "MAX",
        "Strike",
        "Level 3",
        (48.8443, 2.3744),
        "Paris · Gare de Lyon",
    ),
    # Scene 3: the second day of marches; another provider reports the Paris crowds.
    (
        "PAR-DAY2",
        3,
        0,
        "FACTAL",
        "Unrest",
        "Severe",
        (48.8650, 2.3600),
        "Paris · Place de la République",
    ),
]
TITLES = {
    "PAR-REP": "Large student-led march gathers at Place de la République; police deploy tear gas",
    "PAR-BAS": "Protesters moving from République towards Bastille; clashes with riot police",
    "PAR-VOL": "Demonstrations along Boulevard Voltaire; shops closing early",
    "NTE": "Clashes in central Nantes after a march; fire reported at a municipal building",
    "LYS": "City-centre march in Lyon despite a ban; detentions reported",
    "MRS": "Mostly peaceful march on school conditions and living costs at the Vieux-Port",
    "PAR-GDL": "Rail and metro disruption around Gare de Lyon as unions join the protests",
    "PAR-DAY2": "Second day of marches in Paris; crowds again at République, heavy police presence",
}


def build_events(_w: World, tenant_id: uuid.UUID) -> list[EventIn]:
    """The scenario's events. The world is unused (no check-in answers), but the
    signature matches the other scenarios so the seed loads them the same way."""
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
