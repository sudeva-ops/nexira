# Plan · Pilot module 18: Exercise & Training (Prompt 112)

For the product owner and the coding agent. It maps EXR-01..09 (`docs/requirements-pilot.md` §89–93) and D-48 onto the code after pilot module 17, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner. An exercise is a scenario run in `EXERCISE` mode (D-48); it is scored from the record with After-Action Review's metrics (D-47); a mission's readiness is its latest exercise's score. Figures quoted from "the demo record" are from the `make acceptance` run on 2026-11-09.

## 1. Requirements against existing code

| EXR | Exists today | New work | Prompt |
|---|---|---|---|
| 01 Templates | `scenario`, `scenario_event` with a `SCENE_START` marker per scene; 12 scenarios in the demo, of which 5 carry `RAW_SIGNAL` events | a `template` block on scene 0's marker (G-1); `exercises.service.templates()` | 114, 115 |
| 02 Launch | `scenario_run.mode` (`DEMO`, `EXERCISE`; only `DEMO` written, by `scenarios.service.active_run`); the player; `require_roles("ADMIN", "DUTY_OFFICER")` | PC-51 `exercise`; launch (§6) | 113, 115 |
| 03 Label | each run's signals carry the run in `external_id` (`<id>:<run>`); `raw_signal.payload` stores the whole event payload | the run marker on exercise signals, fusion kept apart (G-2), the label on incidents and what hangs off them, Executive and Predictive leave them out (§4) | 115 |
| 04 End, abandon | the scenario API's `reset` finishes a run | end and abandon (§6) | 115 |
| 05 Scores | `aar.service.metrics()` and `decisions()`; `checkin.tally()`; `notification_delivery.status`; `playbook_run_step.status` | `exercises.service.score()` (§3); PC-52 `exercise_score` | 113, 114 |
| 06 History | `site.readiness_score`, `last_drill_on` per embassy and residence (seed `world.py`) | seeded illustrative exercises (§5), KPIs | 114 |
| 07 Readiness | People & Sites (`people/queries.py`), Site Twin (`twin/service.py`), Executive (`_READINESS`), each reading `site` | read the embassy's from the latest completed exercise (§5) | 114 |
| 08 Screen | Blueprint dark; `Kpi`, `Card`, score bars on Predictive; the header's SIMULATED DATA tag | `/exercises`, the banner, EXERCISE tags (§8) | 116 |
| 09 Demo | NBO-CIVIL-UNREST; `make acceptance` | the acceptance spec (§9) | 117 |

New backend module: `app/modules/exercises/{models,schemas,service,router}`.

## 2. Templates and the run's incident (EXR-01, EXR-02)

- **Templates.** A scenario is a template when its scene 0 `SCENE_START` payload carries `"template": {"mission": "<code>", "theme": "<text>"}` (G-1). The seed adds it to NBO-CIVIL-UNREST (NBO, Civil unrest), FRA-NATIONAL-PROTESTS (PAR, Civil unrest), DAC-CYCLONE (DAC, Natural hazard) and MNL-TROPICAL-STORM (MNL, Natural hazard). The add-on scenarios (`ADD-*`, NBO-AIR-DIVERSION, NBO-EVACUATION, NBO-FLEET, NBO-CHOLERA, NBO-SUPPLY, NBO-SITE) act on an incident another scenario opened, so they are not templates. The KPI counts 4.
- **Scenes.** The operator plays the exercise scene by scene with **Next inject**, which calls the scenario API's `next`, as the presenter bar does. The screen shows each scene's name; it does not show the scene's `expect` text, which gives away the answer.
- **The run's incident.** When the exercise ends, its incident is the earliest-opened incident at the template's mission whose first signal carries this run (§4). The run's other incidents (NBO-CIVIL-UNREST's Paris control signal opens one in Paris) are labelled too, but they are not scored.

## 3. The scores (EXR-05, §93 Q5)

They are worked out from the run's incident up to `ended_at`. Each one uses `aar.service` so the two modules agree. `score = None` shows as "—".

| Dimension | Formula | Source | Demo record (INC-2026-1042) |
|---|---|---|---|
| `DETECTION` | 100 × 120 ÷ seconds from the first signal received to the first campaign sent, capped at 100 | AAR `detection_to_notification` | 105.65 s → **100** |
| `ACCOUNTABILITY` | mission personnel asked who answered, as a % | AAR `personnel_accounted` (Executive's rule) | 16 of 17 → **94** |
| `DECISION_SPEED` | 100 × decisions waiting ≤ 300 s ÷ all decisions | AAR `decisions()` (proposals and gates, gate wait as G-2 of AAR) | 6 of 6, slowest 235.82 s → **100** |
| `COMMUNICATION` | 100 × exposed people (`incident_exposure` PERSON) with any of the incident's deliveries DELIVERED or READ ÷ exposed people | `notification_delivery` | 229 of 229 → **100** (G-5) |
| `PLAN_ADHERENCE` | 100 × the run's steps DONE ÷ all its steps, for the incident's first playbook run | `playbook_run_step` | 8 of 8 → **100** |

- **Overall:** the rounded mean of the scores that have a figure. For the demo record that is (100 + 94 + 100 + 100 + 100) ÷ 5 = 98.8 → **99**. It is shown amber below 80.
- **Measured:** each `exercise_score.measured` row stores the figure, the target and the counts, for example `{"seconds": 105.65, "target_s": 120}` or `{"answered": 16, "asked": 17, "campaign": "NTF-3103"}`.
- **Participants:** the distinct mission personnel (not citizens) who answered SAFE or NEED HELP to the run's incident's check-in. That is 16 in the demo record.

## 4. The EXERCISE label and what leaves leadership figures (EXR-03, §93 Q3, Q4)

- **Marking signals.** The player knows its run. For an `EXERCISE` run it adds `"exercise_run_id": "<run>"` to every `RAW_SIGNAL` payload, which is stored in `raw_signal.payload`. A DEMO run adds nothing, so the Phase 1 record is unchanged.
- **Keeping fusion apart (G-2).** A signal joins an ACTIVE incident only when both carry the same exercise run, or neither carries one. One condition is added to `intel.fusion.fuse()`, comparing against the incident's first signal. Without it, an exercise near a live incident would merge into that incident.
- **Telling an exercise incident.** An incident is an exercise incident when its first signal carries `exercise_run_id`. The SQL lives once in `intel/queries.py` (`EXERCISE_RUN`) and Python reads it through `intel.queries.exercise_runs(ids)`.
- **Where the label shows.** The label reaches the API as `exercise: bool` on:
  - incidents (list, detail, map);
  - proposals (by their incident);
  - campaigns and check-ins (by their incident);
  - After-Action Reviews (by their incident).
- **Left out of leadership figures:**
  - Executive's active incidents, posture, detection → notification median, personnel accounted, evacuations (by `evacuation.incident_id`) and the response timeline (lines 82–144 and 211 of `executive/service.py`);
  - Predictive's active-incident driver (`predictive/service.py:151`).
- **The banner.** `GET /api/exercises/running` returns the running exercises. The app shell shows a red "SIMULATED EXERCISE · <name>" tag beside SIMULATED DATA while any is running, and it refreshes on `EXERCISE_UPDATED`.

## 5. Seeded history and readiness (EXR-06, EXR-07, §93 Q7–Q9)

- **Seeded history.** One `ILLUSTRATIVE` COMPLETED exercise per mission (36), all from the seed's existing per-mission values:
  - its date is the embassy's `last_drill_on`;
  - its overall score is the embassy's `readiness_score` (Nairobi: 79 on 2026-10-19);
  - its kind cycles TABLETOP, FUNCTIONAL, FULL_SCALE;
  - its name is "<theme> drill", with the theme cycling Civil unrest, Natural hazard, Health, Cyber-physical and Evacuation, deterministic per mission;
  - it has five illustrative dimension scores whose rounded mean equals the overall score;
  - its participants are 75–90% of the mission's personnel, deterministic per mission.

  These rows have no scenario, run or incident, and they are labelled "Illustrative".
- **KPIs:**
  - **Exercises this year:** COMPLETED exercises dated this year.
  - **Average score:** the mean overall score this year, against last year's. That shows "—" while no exercise is dated last year, which is true of the seed.
  - **Staff who took part:** per mission, the largest `participants` over its exercises in the last 12 months, summed across missions (G-4), with the share of all personnel (1,338 in the seed).
  - **Scenario templates:** 4.
- **Readiness.** `exercises.service.readiness()` returns `{mission_id: (score, date, name, source)}` from each mission's latest COMPLETED exercise.
  - People & Sites, Site Twin and Executive read the embassy's readiness from it instead of `site.readiness_score`.
  - Executive's "illustrative until Exercises" becomes "from exercises".
  - Each figure is labelled "illustrative" while the latest exercise is the seeded one.
  - The residence keeps its seeded value (G-6).
  - The `site` columns stay as they are.

## 6. Roles, state and the API (EXR-02, EXR-04, §93 Q6)

| Action | Who | Rule | Audit |
|---|---|---|---|
| Launch `POST /api/exercises` (template, kind) | ADMIN, DUTY_OFFICER (`approvals.require_roles`) | the template's mission has no RUNNING exercise; if the scenario's active run is PLAYING, refused (409), otherwise that run is FINISHED (as `reset` does); a new `scenario_run` in `EXERCISE` mode at scene 0 | `EXERCISE.START` (template, kind, run, the finished run if any) |
| Next inject | the same | the scenario API's `next` on the exercise's run | `SCENARIO.NEXT`, as today |
| End `POST /api/exercises/{id}/end` | the same | RUNNING only; finds the incident (§2), scores (§3), freezes the scores and participants, finishes the run | `EXERCISE.END` (overall, incident) |
| Abandon `POST /api/exercises/{id}/abandon` (reason) | the same | RUNNING only; no score; finishes the run | `EXERCISE.ABANDON` |
| Read `GET /api/exercises`, `/{id}`, `/templates`, `/running` | every role | — | — |

- **Ending without an incident.** If the run produced no incident at the mission, the exercise is COMPLETED with every score "—" and no overall score.
- **Scenario API guards.** `reset` on a scenario whose active run is an EXERCISE is refused (409, "end or abandon the exercise first"). `active_run` still creates only DEMO runs.
- **Realtime.** `EXERCISE_UPDATED` carries ids only and is added to `realtime.FORWARDED`.

## 7. Check-in timing in an exercise (G-3, decided: A)

`notifications.service.scenario_escalate_after_s()` shortens check-in escalation to the scenario's own setting (20 s for NBO-CIVIL-UNREST), but only while a **DEMO** run is going. It also applies to **every** campaign, which is harmless only because "pilot tenants have no scenario runs". Once exercises exist, that assumption no longer holds.

- **A (decided, PR #142):** an EXERCISE run uses the scenario's setting too, but only for campaigns of its own incidents. A live check-in running at the same time keeps the platform default (600 s, D-07). The scripted injects are compressed in time anyway, and the acceptance spec does not wait 10 minutes.
- **B:** an exercise uses the platform default, which is more realistic. The acceptance spec waits 10 minutes, and the escalated-person finding needs that wait.

## 8. The screen (EXR-08, §93 Q11)

- **Route and nav:** `/exercises`, labelled "Exercise & Training" (icon `target`), subtitle "Readiness · Drills & scoring", under PLAN & INSIGHT before After-Action Review.
- **KPI row:** the four KPIs of §5.
- **Left: Recent exercises.** A table of name, mission, kind, date, a score bar (amber below 80) and status, with Illustrative and RUNNING tags. Selecting a row fills the right side.
- **Right: Run an exercise.** The design's line: "Exercises use the same scenario engine as the live platform. Injects arrive as simulated alerts; responses are timed and scored."
  - **Launch:** choose a template and a kind, then Launch, shown only to ADMIN and DUTY_OFFICER.
  - **While it runs:** the current scene's name, **Next inject**, **End exercise** and **Abandon** (with a reason).
- **Right: Scoring breakdown.** For the selected exercise, five bars, each with its figure and target, for example "1m 46s · target 2 min" or "16 of 17", plus the overall score. Under Communication sits the note "simulated delivery" (G-5).
- **Elsewhere:** an EXERCISE tag on incidents (list, detail, map popup), Decision Queue cards, check-in and campaign rows, and After-Action Review. The banner shows in the header (§4).
- **Tests:** Vitest.

## 9. Acceptance (§92, §93 Q12)

- **A new file, `frontend/e2e/exr-acceptance.spec.ts`.** It runs as a third command in `make acceptance`, after the After-Action Review spec, preceded by `make reset-demo` and the backend restart, as approved: "run on its own after a demo reset".
- **After the reset, the Nairobi exercise's incident is INC-<year>-1042**, labelled EXERCISE. The spec drives it like the Phase 1 run:
  - scenes 1–4 by Next inject;
  - PB-07 approved by the Duty Officer, step 7 by the Nairobi Head of Mission, and the advisory;
  - then End.
- **It checks:**
  - the five scores and the overall score against the After-Action Review metrics of the same incident, read through the AAR API without starting a review;
  - Nairobi readiness 79 (illustrative) before the end and the new score after it, on People & Sites, Site Twin and Executive;
  - Executive's active incidents and posture leave the exercise incident out;
  - a second Nairobi launch is refused;
  - `reset` is refused while the exercise runs;
  - the Viewer can read but cannot act;
  - start and end are audited and the chain verifies.
- **Cost:** about 2 minutes more for the second reset.

## 10. Gaps and conflicts, with proposed answers

| # | Gap | Proposed answer |
|---|---|---|
| G-1 | Nothing marks which scenarios are templates or names their mission; the add-ons share the `NBO-` prefix | A `template` block on scene 0's `SCENE_START` payload, written by the seed (§2). `ensure_scenario` skips codes it already has, so existing databases pick it up at the next `make reset-demo`; no schema change |
| G-2 | Fusion joins any ACTIVE incident nearby, so an exercise signal could merge into a live incident, and a live signal into an exercise | Exercise signals carry their run, and fusion joins only like with like (§4). This changes `intel.fusion`, which is not 🔒 |
| G-3 | The scripted 20 s check-in escalation applies only to DEMO runs, and to every campaign | **Decided: A** (§7, PR #142): an exercise uses the scenario's setting for its own incidents' campaigns only |
| G-4 | "Distinct people who took part" cannot count the illustrative rows, which have no people | Each exercise stores `participants`. The KPI takes the largest per mission over 12 months, summed across missions, so one person is not counted twice for the same mission |
| G-5 | The simulated adapter marks every delivery READ, so Communication scores 100 in every simulated exercise | Keep the approved formula, which separates exercises once real channels exist (Phase 2), and label it "simulated delivery" on the breakdown |
| G-6 | `site` holds readiness for the embassy and the residence (the embassy's minus 6); EXR-07 names the embassy | The embassy's comes from exercises; the residence keeps its seeded value |
| G-7 | Ending an exercise does not close its incident | It stays as people left it, still labelled and still out of leadership figures; people set it to MONITORING or CLOSED as usual, and can review it (§93 Q4) |
| G-8 | A simulated check-in answer resolves to the person's **open** CHECKIN campaign; if a live and an exercise check-in were open for the same person at once, the answer could land on either | Out of scope for the pilot (no separate sandbox, §90 "Not in this module"); the reset before the acceptance spec avoids it; recorded here for the sandbox decision |
| G-9 | 🔒 scope | Prompt 113 (migration: RLS, grants, guards) is 🔒. The API only calls `approvals.py` and `audit.py`; fusion, the player and the check-in timing are not on the D-29 list, so Prompts 114–117 are not 🔒 |

## 11. Migration 0017 (Prompt 113, 🔒)

- **The tables:** PC-51 `exercise` and PC-52 `exercise_score`.
  - FORCE RLS with `tenant_isolation`; only the grants proposed; no DELETE.
  - CHECKs on kind, status, source and dimension, and on scores of 0..100.
  - `status <> 'ABANDONED' OR reason IS NOT NULL`.
  - `source = 'ILLUSTRATIVE'` if and only if there is no scenario and no run.
  - A partial UNIQUE on `(tenant_id, mission_id) WHERE status = 'RUNNING'`.
- **Pinned `search_path` guards:**
  - same-tenant mission, scenario, run, incident and users;
  - an `EXERCISE` row is inserted RUNNING with no score, participants or end, and its run is in `EXERCISE` mode;
  - an `ILLUSTRATIVE` row is inserted COMPLETED with its score;
  - RUNNING → COMPLETED or ABANDONED once; nothing changes after that;
  - `overall_score` and `participants` only on COMPLETED;
  - `started_at` and `ended_at` written by the database;
  - `exercise_score` only for a COMPLETED exercise, frozen;
  - TRUNCATE refused.
- **Tests (as `nexira_api`):** isolation, every refusal, the backup role reads, and the downgrade restores 0016 exactly.

## 12. Prompts

As `docs/prompts-pilot.md` Prompts 113–117. Prompt 115 also covers the player's run marker, the fusion condition (G-2), the check-in timing (G-3) and the scenario API's `reset` guard.

## 13. Decisions by the product owner (2026-11-09, PR #142: "approved A")

- G-3: option A. An EXERCISE run uses the scenario's check-in escalation setting (20 s for NBO-CIVIL-UNREST) for its own incidents' campaigns only; live check-ins keep the platform default (600 s, D-07).
- G-1, G-2, G-4..G-9: as proposed.

## 14. Found while building Prompt 115

- **Next inject is on the exercises API** (`POST /api/exercises/{id}/next`). The scenario API is mounted in demo environments only (D-21), and an exercise runs on the live engine in every environment (D-48). The endpoint does what the scenario API's `next` does and is audited the same way (`SCENARIO.NEXT`, with the exercise's id), so the screen never reads a scene's `expect`.
- **The marker counts only from its own run.** Ingestion refuses a signal carrying `exercise_run_id` unless the event's source is that run (`scenario:<code>:<run>`) and the run is in EXERCISE mode (`RAW_SIGNAL.REJECT`). Without this, a live signal carrying a marker would leave leadership figures.
- **Simulated answers and the check-in clock in an exercise.** Both were accepted only while a DEMO run is going. They are now also accepted from a running exercise run, for the check-ins of the incidents that run opened only (as G-3: A). A live check-in is never answered or timed by an exercise.
- **The hazard clock stays demo-only.** `DEMO_CLOCK` events move the clock that armed playbook runs use, live ones included, so an exercise does not move it. DAC-CYCLONE and MNL-TROPICAL-STORM still run as exercises, but their clock scenes are refused (`SCENARIO.CLOCK_REJECT`) and an armed run is not brought forward.
- **What is left out.** Executive leaves exercise incidents out of the figures in §4, of the mission posture (display risk) and of the hazard drivers. Global Operations still shows them, labelled. Executive's supply, fleet and shelter drivers and Predictive's signal component are not filtered. They read their own modules' state, which an exercise rarely changes.
