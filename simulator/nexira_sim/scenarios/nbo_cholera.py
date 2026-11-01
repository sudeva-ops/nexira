"""NBO-CHOLERA: cholera rises in Kenya and the Nairobi health advisory is proposed (Health
Intelligence, D-39, HL-10; docs/plan-pilot-hl.md §10).

The six advisories are seeded (§48 Q2), so scene 0 changes nothing. Scene 1 brings a newer
simulated WHO bulletin for the seeded Kenya cholera advisory: MODERATE to HIGH, with new
guidance. The Communications agent then proposes the Nairobi health advisory; approving it
creates the campaign, which a second person approves before it is sent (plan G-2). Scene 2
closes the dengue advisory. The bulletins carry the seeded feed ids, so they update the
seeded advisories; a closed advisory stays closed, so run `make reset-demo` to play it again.
Every bulletin is simulated; nobody real is named. Every scene starts with a SCENE_START marker.
"""

import uuid
from typing import Any

from app.modules.scenarios.service import EventIn

from nexira_sim.seed import data
from nexira_sim.seed.ids import seed_id
from nexira_sim.seed.world import World

CODE = "NBO-CHOLERA"
NAME = "Cholera rising in Nairobi"
DESCRIPTION = (
    "Health Intelligence: the Kenya cholera advisory rises to HIGH and the Communications "
    "agent proposes the Nairobi health advisory; then the dengue advisory closes. Simulated."
)

SCENES = [
    (0, "Calm", "Six seeded advisories; cholera in Kenya MODERATE"),
    (
        1,
        "Cholera rising",
        "A newer WHO bulletin: cholera in Kenya HIGH; the Communications agent proposes the "
        "Nairobi health advisory",
    ),
    (2, "Dengue closed", "The Bangladesh dengue advisory is closed"),
]

SEEDED = {row[0]: row for row in data.HEALTH_ADVISORIES}
# (key, scene, offset ms, seeded feed id, change)
BULLETINS: list[tuple[str, int, int, str, dict[str, Any]]] = [
    (
        "CHOLERA-HIGH",
        1,
        2_000,
        "who-don:cholera-ke",
        {
            "level": "HIGH",
            "guidance": "Cases rising in Nairobi county; bottled or boiled water only, avoid "
            "street food, seek care quickly if symptoms appear.",
        },
    ),
    ("DENGUE-CLOSED", 2, 2_000, "moh-bd:dengue-dhaka", {"status": "CLOSED"}),
]


def bulletin(feed_id: str, change: dict[str, Any]) -> dict[str, Any]:
    """The seeded advisory as the feed sends it, with this bulletin's change."""
    _id, topic, code, countries, region, level, guidance, source, _days = SEEDED[feed_id]
    return {
        "external_id": feed_id,
        "topic": topic,
        "topic_code": code,
        "countries": countries,
        "region_label": region,
        "level": level,
        "guidance": guidance,
        "source": source,
        **change,
    }


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
    for key, scene, offset_ms, feed_id, change in BULLETINS:
        events.append(
            EventIn(
                id=seed_id(tenant_id, "scenario_event", f"{CODE}:bulletin:{key}"),
                scene_no=scene,
                offset_ms=offset_ms,
                event_type="HEALTH_ADVISORY",
                payload=bulletin(feed_id, change),
            )
        )
    return events
