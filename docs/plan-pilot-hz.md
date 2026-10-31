# Plan · Pilot module 8: Natural Hazards & Climate (Prompt 53)

For the product owner and the coding agent. It maps HZ-01..11 (`docs/requirements-pilot.md` §39–43) and D-38 onto the code after pilot module 7, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner; the rest follows from approved documents. Everything is simulated (D-19, D-38); nothing external is called.

## 1. Requirements against existing code

| HZ | Exists today | New work | Prompt |
|---|---|---|---|
| 01 More hazard types | the RAW_SIGNAL → normalise → fuse → exposure pipeline; the xWeather source (STORM, FLOOD, DUST_STORM, EXTREME_HEAT) | new categories EARTHQUAKE, TROPICAL_CYCLONE, WILDFIRE, AIR_QUALITY; two new simulated sources (seismic network, air-quality network); xWeather's map gains `Tropical cyclone` and `Wildfire`; a typed `hazard` object in the signal payload (§3) | 55, 56 |
| 02 Severity and size | `normalise()` reads only the source's `severity_map`; `fusion.WEATHER_SIZES` sizes by category alone | `app/modules/intel/hazards.py`: severity from the measure and radius from the measure (§2); `normalise` and `fusion._open` call it for the hazard categories; WILDFIRE's raise in exposure (§2, G-4) | 55 |
| 03 Within range | `incident_exposure`, `exposure_counts()`; `mission.location` | nearest mission and distance (one `ST_Distance` over `mission`), exposed = a mission site or person inside the radius; "No mission within 300 km" | 55 |
| 04 Countdown | — | landfall time from the latest signal's `hazard` object; "landfall in N h" computed by the API against the clock of §5 | 55, 57 |
| 05 Arming | `playbooks.service.start_run`, `START_ROLES`, `playbook_run_live_uq`; the engine only advances RUNNING runs | PC-24; `arm_run`, `start_armed_now`, `disarm` in the playbook service; a worker loop that starts due runs (§4) | 54, 55 |
| 06 Arming proposal | Response Planner (START_PLAYBOOK on EXPOSURE_COMPUTED); action registry and policies | `ARM_PLAYBOOK` action, payload and executor; policy floor 2, `SECURITY_OFFICER\|DUTY_OFFICER`; the planner's cyclone rule (§6) | 55 |
| 07 PB-01 | PB-06 / PB-07 seeds, `matches()` with `categories` and `mission_site_exposed` | PB-01 seed and two English templates; no change to `matches()` (§7) | 55, 56 |
| 08 Climate | — | PC-25 `mission_climate_risk`; seeded through a service function as `nexira_api`; `GET /api/hazards/climate` | 54, 56 |
| 09 Screen | Global Operations map layers; Blueprint dark; `ui/motion` | the screen under MONITOR, map icons, `HAZARD` events to browsers via the existing `INCIDENT_*` keys (§8) | 57 |
| 10 Who sees what | `approvals.user_has_role`, `GET /api/me/permissions` | `entity_type=hazards`: `arm_playbook` per incident; every role reads (§8, G-1) | 55 |
| 11 DAC-CYCLONE | the scenario player, presenter bar, MNL-TROPICAL-STORM | the scenario (§9), three Dhaka homes moved into flood-prone wards | 56 |

## 2. Severity and size per hazard (§43 Q3)

One table in a new `app/modules/intel/hazards.py`, read by `normalise` (severity) and by `fusion._open` and `_match` (radius and fusion distance). Weather's `WEATHER_SIZES` moves into the same file unchanged, so STORM, FLOOD, DUST_STORM and EXTREME_HEAT keep their sizes and Weather's tests do not move.

| Category | Severity from | LOW | MODERATE | HIGH | CRITICAL | Impact radius | Fusion distance | Fusion window |
|---|---|---|---|---|---|---|---|---|
| EARTHQUAKE | `hazard.magnitude` | < 5.5 | 5.5–6.4 | 6.5–7.4 | ≥ 7.5 | 50 km < M5; 100 km M5–5.9; 200 km M6–6.9; 400 km ≥ M7 | = radius | 60 min (unchanged) |
| TROPICAL_CYCLONE | `hazard.cyclone_category` (1–5) | — | 1 | 2 | ≥ 3 | 150 km around the forecast landfall point | 150 km | **48 h** (G-3) |
| AIR_QUALITY | `hazard.aqi` | ≤ 200 discarded (G-5) | 201–300 | 301–400 | > 400 | 30 km | 30 km | **24 h** (G-3) |
| WILDFIRE | the source's `severity_map`, at most MODERATE; HIGH when a mission site is inside 20 km (G-4) | — | default | mission site exposed | — | 20 km | 20 km | 24 h (G-3) |
| STORM, FLOOD, DUST_STORM, EXTREME_HEAT | the source's `severity_map` (Weather, unchanged) | | | | | WX sizes | WX sizes | 60 min |
| anything else | unchanged | | | | | 5 km | 3 km | 60 min |

- **Measures, not guesses.** For EARTHQUAKE, TROPICAL_CYCLONE and AIR_QUALITY the measure decides the severity and the source's `severity_map` is not used. A signal of one of these categories whose `hazard` object is missing or out of range is **discarded** with the reason (`"no magnitude"`, …), as `normalise` already does for unknown values. Nothing is inferred.
- **The radius comes from the opening signal.** `impact_radius_m` is set when the incident opens and does not change (as today). A stronger later signal raises the severity (as `_join` already does) but not the radius. Recorded as G-6.

## 3. Where hazard details live

No new table (§41). The details are a typed `hazard` object inside the RAW_SIGNAL payload, which `ingest_signal` already stores whole in `raw_signal.payload`:

```
"hazard": {"magnitude": 5.2, "depth_km": 10}                      EARTHQUAKE
"hazard": {"cyclone_category": 2, "landfall_in_h": 60, "track_km": 110}   TROPICAL_CYCLONE
"hazard": {"aqi": 380}                                            AIR_QUALITY
```

- A Pydantic model per type, bounded (magnitude 0–10, depth 0–700 km, category 1–5, landfall 0–240 h, AQI 0–999). `RawSignalIn` gains `hazard: dict | None`; `hazards.parse(category, payload)` validates it.
- **Landfall** is `occurred_at + landfall_in_h`. Scenario payloads are stored once and replayed later, so the offset is relative to the signal's own time and comes out right whenever the scene is played. A real provider would send an absolute time and its adapter would convert it.
- The API reads the **latest signal** of the incident (`incident_signal` → `raw_signal`, newest `occurred_at`) for the countdown, the category and the measure.

## 4. Armed runs (PC-24): who starts them, when, restarts and missed times

**States.** `SCHEDULED` → `RUNNING` (started at its time, or "Start now") or `DISARMED` (final). The database guard of PC-24 enforces this.

**Arming** (`playbooks.service.arm_run`, the same function for a person and for the ARM_PLAYBOOK executor):
- The incident must be ACTIVE and TROPICAL_CYCLONE with a landfall time. `scheduled_for` = landfall − 36 h (§43 Q4). If that time is already past, the executor and a person both get the same answer: the run starts now (G-7).
- Steps are created PENDING at arming, as `start_run` does, so the run keeps the playbook version it was armed with.
- `started_by` and `started_by_type` name who armed it (the approver for an agent proposal, as `start_run`). `started_at` is written by the database guard when the run moves to RUNNING (G-2).
- The landfall time the arming was based on is kept in the timeline event's `data` (`{"armed_for_landfall_at": …}`). The incident shows **"forecast changed"** when the latest forecast's landfall differs from it by an hour or more (§43 Q4); `scheduled_for` stays frozen.
- Audited `PLAYBOOK.ARM`; timeline "PB-06 armed: starts <time> (36 h before landfall)"; `PLAYBOOK_RUN_ARMED` to browsers.

**Starting.** A new worker loop, `armed_loop`, every 30 s for the tenants in `WORKER_TENANT_IDS`, as `nexira_api`:
- selects `SCHEDULED` runs with `scheduled_for <= now` (§5's clock), each `FOR UPDATE SKIP LOCKED`, so two workers never start the same run;
- moves each to `RUNNING` in one transaction with its timeline entry and the `PLAYBOOK.ARMED_START` audit row (actor `SYSTEM:playbook.armed`), then publishes `PLAYBOOK_RUN_STARTED`, so the existing engine runs the steps.
- **Restarts and missed times.** The loop runs at worker start, so a run that came due while the worker was down starts on the first pass, late. The timeline says how late ("started 12 min after its time"). Nothing is lost: the state is in the database, not in memory.
- **The incident is no longer ACTIVE** at the time (MONITORING or CLOSED): the run is **DISARMED** by the system with that reason, audited, never started (a playbook only runs for an ACTIVE incident).

**Start now and disarm** (`start_armed_now`, `disarm`): `POST /api/playbook-runs/{id}/start-now` and `/disarm`. Roles through `approvals.user_has_role(…, START_ROLES, incident.mission_id)` (G-1). Audited `PLAYBOOK.ARMED_START` and `PLAYBOOK.DISARM`.

**One live run.** `playbook_run_live_uq` must count `SCHEDULED` as live, so a playbook cannot be armed twice for an incident, or armed and started at once. PC-24 does not say so: **G-8, needs a decision** (an amendment to PC-24). "Start now" on a person's own "Start playbook" button for an armed playbook converts the armed run instead of failing.

## 5. The demo clock (G-9, needs a decision)

The acceptance (§42) needs the armed playbook to start "when the scenario reaches 36 h". A scene is minutes long; 24 real hours cannot pass.

**Proposal:** a `DEMO_CLOCK` scene event `{"advance_h": 24}`, handled like `CHECKIN_CLOCK`: accepted only while a demo scenario is running, otherwise rejected and audited; each accepted one is audited `SCENARIO.CLOCK_ADVANCE`. The **hazard clock** is `now + the sum of advances since the demo started` (from those audit rows, as check-in's clock start is found). It is used in two places only: the landfall countdown and the armed-run due check. Everything else (check-in escalation, flights, audit timestamps) stays on real time. The screen shows "Demo clock +24 h" while it is ahead. Resetting the scenario ends it (the sum counts from the new start).

**Alternative:** a `ARMED_RUNS_DUE` scene event that starts the scenario's armed runs at once. Simpler, but the countdown would still say "landfall in 60 h" after the playbook started "at 36 h".

## 6. The arming proposal (HZ-06)

- **Action** `ARM_PLAYBOOK`, payload `{"playbook_code": "PB-06", "hours_before_landfall": 36}` (36 fixed in the pilot; the payload is not editable, as START_PLAYBOOK). Executor → `playbooks.service.arm_run`. Not undoable (disarm is the person's action). Policy: floor 2, `SECURITY_OFFICER|DUTY_OFFICER`, decided within 12 h or it expires, so a stale forecast is not armed by accident.
- **Rule** in the Response Planner, on EXPOSURE_COMPUTED: a TROPICAL_CYCLONE incident, ACTIVE, HIGH or CRITICAL, with a mission site or person exposed, a landfall more than 36 h away (hazard clock), and no SCHEDULED or live run of PB-06 for it. Evidence: the forecast (category, landfall time, track distance to the mission), exposure counts. Alternative: "Monitor only; reassess in 12 h" (POST_INTERNAL_NOTE, advice only).
- **One open proposal per incident:** `proposal_key = ARM_PLAYBOOK:{incident}:PB-06`, the same mechanism as START_PLAYBOOK (plan G-15). Once it is decided, no new one is made for that incident (the run exists, or it was rejected).
- PB-06's own START_PLAYBOOK rule lists STORM and FLOOD only, so a cyclone incident is not also offered "Run PB-06 now". At 36 h or less to landfall the planner offers nothing new; people can still start PB-06 from the incident.

## 7. PB-01 · Earthquake

- **Trigger:** `{"categories": ["EARTHQUAKE"], "min_severity": "HIGH", "mission_site_exposed": true}`, existing `matches()` keys.
- **Steps** (as PB-06, D-31): 1 safety check-in for exposed staff (CHECKIN); 2 staff alert, template `EARTHQUAKE_STAFF_ALERT` (NOTIFY); 3 notify the Head of Mission and Security (NOTIFY, approval HEAD_OF_MISSION, PB-06 step 2's pattern); 4 the citizen advisory from template `EARTHQUAKE_CITIZEN_ADVISORY` through the Communications agent (second person, D-31).
- **Templates:** English with `{city}`; AR/FR/SW not written until reviewed (D-15).
- The DAC-CYCLONE Ankara earthquake is LOW and outside its range, so PB-01 is not proposed in the demo; a backend test covers a HIGH one.

## 8. API and who sees what

- `GET /api/hazards`: ACTIVE and MONITORING incidents of the six hazard categories: reference, category, title, severity, measure, landfall time and "landfall in N h", nearest mission code and distance, exposed (bool), exposure **counts** (staff, homes, sites), the armed run if any (`scheduled_for`, status, forecast changed), source labels, `simulated: true`. No names, for every role (HZ-10).
- `GET /api/hazards/climate`: the climate rows, sorted by the 2050 score.
- `GET /api/me/permissions?entity_type=hazards&entity_id=<incident>`: `arm_playbook`, `start_armed`, `disarm`.
- Browsers: `PLAYBOOK_RUN_ARMED` and `PLAYBOOK_RUN_DISARMED` events; `staleKeys` maps them, and the existing `INCIDENT_*` events, to the hazards keys.

## 9. Scenario `DAC-CYCLONE` (§43 Q8)

| Scene | Events | What shows |
|---|---|---|
| 0 Calm | — | no hazard events |
| 1 Background | seismic M5.2, 210 km from Ankara; xWeather `Flood` Moderate in Jakarta (2 staff homes inside); xWeather `Extreme heat` in Riyadh; air quality AQI 380 in New Delhi; a wildfire > 300 km from every mission; xWeather `Tropical cyclone` category 1 for Dhaka, landfall in 72 h | six events; Ankara LOW, not exposed; Dhaka MODERATE; the wildfire "No mission within 300 km" |
| 2 Upgrade | category 2, landfall in 60 h, landfall point 110 km south of the Dhaka mission | fused into the same incident, HIGH, Dhaka mission exposed, "landfall in 60 h"; the arming proposal |
| 3 36 h | `DEMO_CLOCK` +24 h | "landfall in 36 h"; the armed PB-06 starts by itself |
| 4 Landfall | `DEMO_CLOCK` +36 h; xWeather `Flood` Major in Dhaka | a FLOOD incident with its own exposure (the three flood-prone homes) |
| 5 Weakening | category 1 signal | the cyclone stays HIGH (severity never falls by itself, as today) — a person sets it to MONITORING |

The background events arrive with scene 1, not with `make reset-demo`, so the Phase 1 scenario still starts with no active incident (§43 Q8).

## 10. Gaps and conflicts, with proposed answers

**G-1 · Who arms (needs a decision).** HZ-10 and §43 Q5 say SECURITY_OFFICER and DUTY_OFFICER for any mission and HEAD_OF_MISSION for their own, "as starting a playbook". But starting a playbook today is `START_ROLES = DUTY_OFFICER|SECURITY_OFFICER` only; a Head of Mission cannot start one. **Proposal:** arming, starting an armed run and disarming use `START_ROLES` exactly, so arming is never wider than starting; correct HZ-10 and §43 Q5 to match. (The other choice, adding HEAD_OF_MISSION to `START_ROLES` for their own mission, widens who starts every playbook, which is a 🔒 change of its own.)

**G-2 · `started_at` of an armed run.** It is NOT NULL with default `now()`, so it would say the arming time. **Proposal:** the PC-24 guard sets `started_at = now()` when a run moves SCHEDULED → RUNNING; the arming time is in the audit row and the timeline. Within PC-24 (its guard), no new column.

**G-3 · Fusion window for slow hazards.** The 60-minute window would open a new incident for every 6-hourly cyclone forecast, and for an AQI reading the next day. **Proposal:** a per-category window (§2): TROPICAL_CYCLONE 48 h, AIR_QUALITY and WILDFIRE 24 h; everything else 60 min, so D-23 and Weather do not move.

**G-4 · Wildfire severity.** "HIGH within 20 km of a mission" depends on exposure, which comes after fusion. **Proposal:** a WILDFIRE rule next to D-11 step 3 in `exposure.compute`: MODERATE becomes HIGH when a mission site (not a hotel) is exposed, with an ESCALATED timeline event, as D-11.

**G-5 · Air quality below 201.** §43 Q3 starts at 201. **Proposal:** readings of 200 or less are discarded ("below threshold"), so a normal day is not an incident.

**G-6 · The radius does not grow.** A later, stronger earthquake reading raises the severity but keeps the first radius (fusion's centre and radius are fixed today). **Proposal:** keep it; a stronger quake far away opens its own incident anyway.

**G-7 · Approved after the arming time.** If a proposal is approved when landfall is already less than 36 h away, the arming time has passed. **Proposal:** the run starts at once and the timeline says so; refusing would leave people unwarned. The planner never proposes at 36 h or less, so this happens only with a late approval.

**G-8 · Armed runs and the live-run index (needs a decision).** PC-24 changes the statuses but not `playbook_run_live_uq`. **Proposal:** amend PC-24 so the index covers `SCHEDULED` too; otherwise two armed runs, or an armed and a running one, could exist for one incident.

**G-9 · The demo clock (needs a decision).** §5.

**G-10 · Existing tenants.** `ensure_sources` adds new sources only, so a tenant seeded before this module keeps xWeather's old map (as Weather's G-2). **Proposal:** fine for the pilot: `make reset-demo` reseeds; the runbook says so.

**G-11 · Acceptance order.** Playwright runs the spec files alphabetically, so `hz-acceptance` runs before `jrn`, `ntf`, `ta` and `wx`. **Proposal:** it sets its own incidents to CLOSED at the end, so later specs see none of them; the Makefile comment says alphabetical.

**G-12 · Cyclone weakening.** Severity never falls by itself in the pipeline today. **Proposal:** keep that; scene 5's weaker forecast updates the countdown and measure, and a person sets the incident to MONITORING.

**G-13 · D-11 raises a cyclone over Dhaka to CRITICAL (found in Prompt 55; decided 2026-10-31: as proposed).** A protected mission site (the chancery) inside a HIGH cyclone's 150 km makes it CRITICAL by D-11 step 3, as for any incident. §42 says the Dhaka forecast "becomes a HIGH TROPICAL_CYCLONE incident". **Proposal:** keep D-11 (one rule for every incident); §42 reads "HIGH (CRITICAL with the D-11 raise)". The arming rule takes HIGH or CRITICAL, so nothing else changes.

**Review of Prompt 55 (fixed, with tests):** the ARM_PLAYBOOK payload carries the landfall the approvers read, and arming is refused if the forecast has moved by an hour or more (M1); DEMO_CLOCK events take a per-tenant lock (M2); the demo clock's advance counts only for runs armed during that demo, so a real armed run is never brought forward (M3); each due run starts in its own savepoint, so one failure does not stop the others (M4); roles are checked before the run is locked; a 5 s margin before "start at once"; arming after landfall is refused; a hazard signal dated more than 10 min ahead is discarded; lateness is real time only.

## 11. Migration 0008 (Prompt 54, 🔒)

Only as approved in PC-24 and PC-25 (and G-2, G-8 if approved):
- `playbook_run.scheduled_for timestamptz` (nullable); the status CHECK gains `SCHEDULED` and `DISARMED`; `playbook_run_live_uq` gains `SCHEDULED` (G-8).
- Guard trigger `playbook_run_guard` (pinned `search_path`): a run inserted as SCHEDULED needs `scheduled_for > now()`, a non-SCHEDULED run has none; SCHEDULED moves only to RUNNING or DISARMED; DISARMED is final; `scheduled_for` is frozen once set; `started_at = now()` on SCHEDULED → RUNNING (G-2).
- `mission_climate_risk` as PC-25: FORCE RLS, `tenant_isolation`, SELECT and INSERT for `nexira_app`, no UPDATE or DELETE; CHECKs on the scores and a non-empty `hazards`; a guard refusing a mission not visible in its own tenant (the lesson of Prompts 24 and 29).
- Review of Prompt 54: `scheduled_for` is checked against `clock_timestamp()`; a DISARMED run is final in every column; SCHEDULED and DISARMED runs cannot be deleted; climate hazards are bounded. For Prompt 55 (L7): the run-status `Literal` in `playbooks/router.py` and the list in `schemas.py` gain SCHEDULED and DISARMED; the worker's start and a person's "start now" both update with `WHERE status = 'SCHEDULED'` (or lock and re-check), so only one of them starts the run; the arming API accepts timezone-aware times only.
- `nexira_backup` reads the new table through the default privileges; the downgrade restores 0007 exactly (a SCHEDULED or DISARMED row blocks the downgrade with a clear error rather than being rewritten).

## 12. Decisions by the product owner (2026-10-31, PR #64: "approved")

- **G-1:** arming, starting an armed run and disarming use `START_ROLES` (Security Officer, Duty Officer); HZ-10 and §43 Q5 corrected. A Head of Mission does not arm.
- **G-8:** PC-24 amended: `playbook_run_live_uq` covers SCHEDULED (with G-2, the guard sets `started_at`).
- **G-9:** the demo clock (`DEMO_CLOCK`; the hazard countdown and armed runs only, while a demo runs).

G-2..G-7 and G-10..G-12 as proposed.
