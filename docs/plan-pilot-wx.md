# Plan · Pilot module 6: Weather (Prompt 38)

For the product owner and the coding agent. It maps WX-01..08 (`docs/requirements-pilot.md` §24–28) and D-35 onto the code after pilot module 4, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner; the rest follows from approved documents. Weather is simulated (D-19, D-35); nothing external is called.

## 1. Requirements against existing code

| WX | Exists today | New work | Prompt |
|---|---|---|---|
| 01 Current conditions | nothing | `weather_current` (PC-20); `app/modules/weather` (model, service, router `GET /api/weather`) | 39, 40 |
| 02 On the screens | Global Operations, MapLibre map, mission popup | weather panel, weather layer, popup line; `WEATHER_UPDATED` to browsers | 41 |
| 03 Warnings as intelligence | xWeather source (`Flood` → FLOOD, `Storm` → STORM), the whole signal → incident pipeline | add `Dust storm` → DUST_STORM, `Extreme heat` → EXTREME_HEAT to the xWeather map; category labels for titles | 40 |
| 04 Category-sized incidents | `FUSION_RADIUS_M = 3000`; `incident.impact_radius_m` default 5000 | one table of sizes per category (§3); fusion and the new incident's `impact_radius_m` read it; unrest unchanged | 40 |
| 05 PB-06 | Response Planner rules `{category, min_severity, max_distance_m}`; PB-07 and its templates | PB-06 seed and its templates; the planner's rule accepts a list of categories (§4) | 40 |
| 06 Weather and travel | incidents count for their mission's country (JR G-1); Travel & Air reacts to incidents | nothing new: a weather incident is an incident. A seeded staff trip to Manila for the acceptance | 40 |
| 07 Scenario | the scenario player; NBO, FRA, AIR scenarios | `MNL-TROPICAL-STORM` (§5); presenter entry | 40, 41 |
| 08 Simulated feed | the flight tracker's tick-and-feed pattern | `weather/feed.py`: a worker tick every 15 min and a `WEATHER_FEED` consumer (§2) | 40 |

## 2. The simulated feed (Prompt 40)

`app/modules/weather/feed.py`, run by the worker for the tenants in `WORKER_TENANT_IDS`, as `nexira_api` (D-01).

**Tick (every 15 minutes, WX §28 Q2):** for every mission, compute plausible conditions from the city's latitude, the month and the local hour (warmer at low latitudes and in the afternoon; a seeded, stable variation per city and day, so the same moment always gives the same weather), and upsert `weather_current`. Publish one `WEATHER_UPDATED` per tenant after commit.

**Feed events (`WEATHER_FEED`, consumer group `weather`):** a scenario names a mission code and the conditions (`condition`, `temperature_c`, `wind_kph`, `gust_kph`, `rain_mm`). The row is written with source `xWeather (simulated, scenario)`. Payloads are typed and bounded like the flight feed (review of Prompt 30): a malformed event is dropped, not retried.

**Overrides hold (G-1):** the tick leaves a row alone while its source is the scenario's and it was written within the last 6 hours, so a storm does not clear itself mid-demo; after that the city returns to its normal cycle.

**Warnings are not written here.** They are RAW_SIGNAL events of the xWeather source, from the scenario, through the existing intel consumer.

## 3. Category-sized incidents (Prompt 40)

A small table in `app/modules/intel/fusion.py`, defaults from §28 Q4:

| Category | Impact radius | Fusion distance |
|---|---|---|
| STORM | 60 km | 60 km |
| FLOOD | 25 km | 25 km |
| DUST_STORM | 40 km | 40 km |
| EXTREME_HEAT | 30 km | 30 km |
| anything else (CIVIL_UNREST, TRANSPORT_STRIKE, …) | 5 km (unchanged) | 3 km (unchanged) |

`_open` sets `impact_radius_m` from the table when it creates an incident; `_match` uses the category's fusion distance. Unrest is untouched, so the D-23 figures and the Phase 1 acceptance do not move (tested).

## 4. PB-06 · Severe weather (Prompt 40)

- **Trigger** (`playbook.trigger_rules`): `{"categories": ["STORM", "FLOOD"], "min_severity": "HIGH", "mission_site_exposed": true}`, which reads as WX §28 Q6: HIGH or CRITICAL, storm or flood, with a mission site inside the incident's radius. The planner's `matches()` gains `categories` (a list, alongside the existing single `category`) and `mission_site_exposed`; PB-07's rule is unchanged.
- **Steps** (as PB-07 v2, D-31): 1 confirm the warning (TASK); 2 notify the Head of Mission and Security (NOTIFY, approval HEAD_OF_MISSION, as PB-07 step 7's pattern); 3 staff alert to exposed personnel from template `SEVERE_WEATHER_STAFF_ALERT`; 4 safety check-in; the Communications agent proposes the citizen advisory from template `SEVERE_WEATHER_SHELTER` (second person, D-31).
- **Templates:** generic EN with `{city}`, as the Phase 1 templates; AR/FR/SW not written (English only until reviewed, D-15).

## 5. Scenario `MNL-TROPICAL-STORM` (Prompt 40)

| Scene | Events | What shows |
|---|---|---|
| 0 Calm | — | Manila's normal conditions |
| 1 Building | `WEATHER_FEED` MNL: cloud, wind 45 km/h | conditions worsen on the panel |
| 2 Warning | `WEATHER_FEED` MNL: storm, wind 110, gusts 150, rain 60 mm; xWeather `Storm` / `Severe` signal 40 km east of Manila, then a second from another provider within 60 km | one STORM incident (fused), CRITICAL, Manila mission exposed; PB-06 proposed; the seeded Manila trip impacted; Travel & Air proposes a message |
| 3 Landfall | a `Flood` / `Major` signal in the city | a FLOOD incident (separate category), exposure |

The second provider is Dataminr with a new `Tropical storm` → STORM entry in its map, so fusion and confidence work as for Nairobi.

## 6. Gaps and conflicts, with proposed answers

**G-1 · Scenario overrides vs the tick.** Without care the 15-minute tick would overwrite a scenario's storm. **Proposal:** §2's 6-hour hold, keyed on the scenario's source label; no extra column.

**G-2 · Existing tenants and the new xWeather categories.** `ensure_sources` inserts new sources only, so a tenant seeded earlier keeps the two-category map. **Proposal:** fine for the pilot (`make reset-demo` reseeds); note it in the runbook. A real deployment would update the map through an admin path later.

**G-3 · Exposure grows a lot.** A 60 km storm over Manila exposes every Manila person and site, and the D-11 escalation applies (a protected site in the zone raises the severity). **Proposal:** that is the point; the scenario is in Manila, not Nairobi, so D-23 is unaffected.

**G-4 · A storm is not "at" a point.** The pilot keeps one centre and a radius per incident; a moving track is out of scope (no forecasts, §25 "not in this module").

**G-5 · Severity mapping.** xWeather maps `Minor/Moderate/Major/Severe` to LOW..CRITICAL (the generic map). **Proposal:** keep it.

**G-6 · Stale conditions.** **Proposal:** the API returns `observed_at`; the screen flags anything older than 30 minutes (§28 Q2). The worker being stopped is the only way to see it in the demo.

**G-7 · Who reads weather.** **Proposal:** every role, like missions.

## 7. Migration 0005 (Prompt 39, 🔒)

- PC-20: `weather_current` with FORCE RLS and `tenant_isolation`; SELECT, INSERT, UPDATE for `nexira_app`; no DELETE; range CHECKs (temperature −60..60 °C, wind and gusts 0..400 km/h, gusts ≥ wind, rain 0..1000 mm); `condition` from the seven values; a guard trigger refuses a row whose mission is not visible in its own tenant (the lesson of Prompts 24 and 29: foreign keys ignore RLS). A composite foreign key would need a new UNIQUE `(tenant_id, id)` on `mission`, a schema change outside PC-20, so it is not used.
- `nexira_backup` reads it through the default privileges; the downgrade restores 0004 exactly.

## 8. Decisions needed from the product owner

None: G-1..G-7 follow from D-35 and the defaults in requirements-pilot.md §28. G-1 (a scenario's storm holds for 6 hours) and G-3 (a storm exposes a whole city) are worth a look.
