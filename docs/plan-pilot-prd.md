# Plan · Pilot module 16: Predictive Risk (Prompt 99)

For the product owner and the coding agent. It maps PRD-01..08 (`docs/requirements-pilot.md` §79–83) and D-46 onto the code after pilot module 15, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner. The model is rule-based and labelled "illustrative model" (§83 Q2); the calendar and the first 30 days of history are simulated (D-19); nothing changes because of a forecast (PRD-06).

## 1. Requirements against existing code

| PRD | Exists today | New work | Prompt |
|---|---|---|---|
| 01 Index and history | `mission.risk_level`; ACTIVE incidents with `mission_id`; `raw_signal` with location and `received_at`; `health_intel.list_advisories()`; `hazards.list_hazards()` (`within_range`, `nearest_mission_code`); `weather_current.condition` | PC-46 `risk_index`; `predictive.service.components()`; a worker snapshot loop (§3) | 100, 101 |
| 02 Projection | — | `predictive.service.forecast()`, on read (§4) | 101 |
| 03 Drivers | — | each component now and 7 days ago (§5) | 101 |
| 04 Rising risk, actions | — | ranking and rule-based actions (§6) | 101 |
| 05 Calendar | — | PC-47 `mission_event`; seed; `MISSION_EVENT` from the scenario player (§7) | 100, 103 |
| 06 Forecast agent | the agent framework: `PhaseOneAgent`, `proposals.create()`, level 4 advice dismissed by a reviewer, `actions.ACTIONS` | the FORECAST agent; **see G-1, needs a decision** (§8) | 102 |
| 07 Screen | Blueprint dark; `Kpi`, `Card`; the Executive trend SVG | the screen, before Executive Overview (§9) | 104 |
| 08 ADD-FORECAST | scenario player; the ADD-VISIT scenario and VV-<year>-031 | the scenario (§10) | 103 |

New backend module: `app/modules/predictive/{models,schemas,service,consumer,router}`.

## 2. The index: components and points (PRD-01, §83 Q2)

Each component is worked out for a mission and a day. The index is their sum, capped at 100. The points are chosen so that one CRITICAL incident lifts a calm mission to about 80 (as the design's Nairobi), and a calm mission stays below the threshold of 70 without one.

| Component | Points | Source |
|---|---|---|
| Baseline | LOW 35, MODERATE 50, HIGH 65, CRITICAL 80 | the stored `mission.risk_level` (not `display_risk`, so an incident is not counted twice) |
| Incidents | the worst ACTIVE incident at the mission: LOW 5, MODERATE 15, HIGH 30, CRITICAL 45 | `incident.mission_id`, `severity` |
| Signals | min(10, 2 × (signals within 50 km in the last 7 days − their weekly mean over the 30 days before)), never below 0 | `raw_signal.location`, `received_at` |
| Health | the highest OPEN advisory for the mission: LOW 2, MODERATE 4, HIGH 7, CRITICAL 10 | `health_intel.list_advisories()` |
| Hazard | an ACTIVE hazard `within_range` with this mission nearest: LOW 3, MODERATE 6, HIGH 10, CRITICAL 15 | `hazards.list_hazards()` |
| Weather | 5 while the mission's current condition is STORM (VIP's severe weather) | `weather_current` |
| Events | the sum of the weights of the calendar events that count on that day, capped at 45: 100% from `starts_on` to `ends_on`, 75% the day before, 50% two days before | PC-47 `mission_event` |

- **Calm state:**
  - every mission is at its baseline plus at most its seeded events: LOW missions 35–45, the four MODERATE missions 50–65;
  - no mission's 14-day peak reaches 70 (a simulator test checks this).
- **Nairobi after NBO-CIVIL-UNREST scene 2:** 35 + 45 (CRITICAL) + 6 (three Nairobi signals) = 86, plus any open health advisory.

## 3. The snapshot and the history (PRD-01, §83 Q3)

- **`risk_index` rows:** one per mission per day (PC-46).
- **The worker** runs `snapshot(tenant)` every 15 minutes, as the weather feed does. It inserts today's row for each mission (`source COMPUTED`), or updates today's row's value and components. The guard allows UPDATE on today's row only.
- **Audit:** `PREDICTIVE.SNAPSHOT` once per tenant and day, on the first insert of the day, with the mission count. The 15-minute updates of derived figures are not audited (G-4).
- **On demand:** `snapshot` also runs after a `MISSION_EVENT` is added and when the overview is read with no row for today, so the demo is always current.
- **The seeded history (G-3):**
  - 30 days before the scenario date per mission, `source ILLUSTRATIVE`, with `components {"illustrative": value}`;
  - deterministic: the mission's calm index, ±4 of seeded noise, and a gentle drift into today's value;
  - labelled "Illustrative history (simulated)" on the chart.

## 4. The projection and the band (PRD-02)

For day d = 1..14 after today:

- **baseline:** unchanged;
- **incidents:** today's points × 2^(−d/3), a half-life of 3 days;
- **signals:** today's points × max(0, 1 − d/7), gone after a week;
- **health, hazard and weather:** today's points × max(0, 1 − d/14);
- **events:** the calendar's points for that day (§2), so a scheduled rally rises two days before;
- **trend:** the slope of the last 14 days of history, clamped to ±1 point a day, × d × 0.5;
- **total:** capped to 0..100;
- **band:** ± (3 + 0.9 × d), capped to 0..100.

The forecast is not stored. The chart and the API label it "Illustrative model · projection, not a prediction" (D-46).

## 5. Drivers (PRD-03)

For the selected mission, each non-zero component is shown with:
- its points now;
- its change against the history row of 7 days ago, where that row has components (a COMPUTED row). For an ILLUSTRATIVE row the change is "—";
- a plain label, e.g. "Scheduled public events · 2 in the next 7 days · +18", or "Civil unrest INC-<year>-1042 (critical) · +45".

## 6. Rising risk and recommended actions (PRD-04, §83 Q4, Q6)

- **Rising risk:** every mission ranked by (the forecast's 14-day peak − today), with now, peak, the day of the peak and the change. Missions whose peak reaches 70 are flagged "Crosses 70 on <day>".
- **Recommended actions (text only, no task):**

| Rule | Action text |
|---|---|
| peak ≥ 70 and a calendar event drives it | "Review movements and venues in <city> around <event title> (<date>)." |
| peak ≥ 70 and an ACTIVE incident drives it | "Keep <city> at Elevated until the forecast stays below 70 for 72 h." |
| a hazard within range | "Check shelter supplies and the continuity plan for <city>." |

  No action names a VIP visit. Restricted visits stay on VIP Protection (G-1).

## 7. The events calendar (PRD-05)

- **PC-47 `mission_event`:** seeded with about 12 illustrative events across the missions, each with kind, title, place, dates, attendance and weight (1..30). Examples:
  - "National holiday" in Addis Ababa on day +3, weight 8;
  - "Planned rallies" in Islamabad on day +2, weight 12;
  - "Election campaign event" in Abuja on day +6, weight 10.

  Weights are chosen so the calm peaks stay below 70.
- **The scenario's events:** `MISSION_EVENT {mission, kind, title, place, lat, lon, starts_on, ends_on, attendance, weight}` (dates as offsets from the scenario date). It is taken from the scenario player only. It inserts the event, audits `PREDICTIVE.EVENT` and runs the snapshot.

## 8. The Forecast agent (PRD-06, §83 Q7)

**G-1 · needs a decision.** The approved PRD-06 has the agent propose a programme change for a VIP segment. That conflicts with D-42 and VIP-06:
- A visit "does not exist" for anyone outside the protection roles. The Decision Queue is readable by every role, so a proposal naming the visit, a segment, a venue or a time would reveal it to the Viewer.
- D-42 says "no agent acts on visits".
- The VIP module lets only a Security Officer propose a change (`PROPOSER`). PC-48's approvers (Security Officer, Duty Officer, HQ Crisis Director) do not match.

The options:

| Option | What it means | Cost |
|---|---|---|
| **A** · restricted proposals | The agent proposes `PROPOSE_VIP_CHANGE` as approved, and proposals linked to a visit are hidden from everyone outside VIP-06's roles (a new `agent_proposal.restricted` and filters in every proposal read and realtime event). Approver: Security Officer only. | A schema change to `agent_proposal` (a new PC), changes across the agents module and the Decision Queue (🔒), and new ways to leak a visit to test for. |
| **B** · advice only, no visit named (**recommended**) | The agent raises a level-4 **advice** proposal `ADVISE_READINESS_CHECK` for the mission when its forecast crosses 70 within 14 days because of calendar events, e.g. "Addis Ababa risk forecast 35 → 75 by <date>: a rally is planned near the industrial park. Review movements and venues in the next 14 days." It names no visit, segment or time; it is never executed; a reviewer dismisses it. The Security Officer, who can see the visit, proposes the change on VIP Protection, where the visit already shows its segment risk and the recommendation. | No executor, no policy, no VIP data in proposals; D-42 holds as written. PC-48 shrinks to the agent row only, and Prompt 102 is no longer 🔒 under D-29. |

**With B:**
- **The agent:** FORECAST observes `MISSION_EVENT_ADDED` (published by the calendar handler) and `EXPOSURE_COMPUTED`.
- **The proposal:**
  - `proposal_key` `PRD:<mission>:<peak date>` (one per mission and peak);
  - `is_proactive` true;
  - evidence: the forecast now and at the peak, the events and their weights, and the drivers;
  - confidence: none, since the model is illustrative.
- **The demo:** the acceptance checks the advice in the Decision Queue (the Viewer can read it and finds no visit in it). Then a Security Officer proposes the virtual site visit on VIP Protection, and two people decide it as before.

## 9. The screen (PRD-07, §83 Q8)

- **"Predictive Risk"** (`/predictive`, icon `trending-up`) under PLAN & INSIGHT, before Executive Overview. The subtitle is "Analytics · 14-day risk forecast".
- **API:**
  - `GET /api/predictive/overview`: rising risk and actions for all missions;
  - `GET /api/predictive/missions/{id}`: history, forecast, band and drivers;
  - `GET /api/predictive/missions/{id}/events`.
- **Layout:**
  - the advisory banner ("Model output is advisory · illustrative model · simulated data");
  - a mission picker that opens on the highest peak;
  - the chart (inline SVG): history in blue, the dashed forecast in violet with its band, the "Today" line, and the 70 threshold dashed in red;
  - "Key drivers";
  - "Rising risk · next 14 days";
  - "Recommended actions";
  - the mission's calendar.
- **Who:** every role. Aggregates, mission references and public calendar events only.
- **Realtime:** `PREDICTIVE_UPDATED {mission_id}` (after a snapshot or an event), INCIDENT_*, EXPOSURE_COMPUTED, HEALTH_ADVISORY_UPDATED and WEATHER_UPDATED refetch it.

## 10. Scenario `ADD-FORECAST` (PRD-08, §83 Q9)

| Scene | Events |
|---|---|
| 0 Ready | marker only |
| 1 Rally announced | `MISSION_EVENT` ADD: "Rally near the industrial park" (RALLY, day +5, 5,000 people, weight 30) and "Counter-demonstration" (RALLY, day +5, weight 10) |

- Addis Ababa's forecast then rises from 35 to 75 on day +5:
  - day +3: 20 from the rallies' ramp + 8 for the holiday;
  - day +4: 30 + 0;
  - day +5: 40.
- Rising risk lists Addis first, and the action reads "Review movements and venues in Addis Ababa around Rally near the industrial park (<date>)".
- With option B, the Forecast agent's advice appears in the Decision Queue.
- **Replays:** a replay inserts no duplicate, because the event ids are seeded per scenario. The scenario approves and proposes nothing itself.
- **Phase 1:** the scenario starts with an empty Decision Queue, and the agent proposes only from `MISSION_EVENT_ADDED` with a peak of 70 or more. The seeded calendar never reaches 70, so seeding raises nothing.

## 11. Acceptance (§82)

- **The Phase 1 spec** gets two API checks, as Executive Overview did (G-1 there):
  - scene 0: 30 days of history for NBO and ADD, every 14-day peak below 70, and an empty queue;
  - after scene 2: Nairobi's index ≥ 80 and its forecast lower at day 14 than today.
- **`prd-acceptance.spec.ts`** (after `ntf-`, before `scene…`/`sup-` by name) checks:
  - ADD-FORECAST from the presenter bar: Addis's peak ≥ 70 on day +5; Addis first in rising risk; the action text;
  - the chart shows history, forecast and threshold;
  - with option B: the advice in the Decision Queue, naming no visit; the Viewer reads it; a reviewer dismisses it;
  - the Viewer sees the screen;
  - the audit (`PREDICTIVE.SNAPSHOT`, `PREDICTIVE.EVENT`, the proposal) and the chain.
- **Other specs:** ADD-VISIT's spec (`vip-`) and the Executive Overview's are unchanged. The calendar adds no incident and no proposal before ADD-FORECAST.

## 12. Gaps and conflicts, with proposed answers

| # | Gap | Proposed answer |
|---|---|---|
| G-1 | **Needs a decision.** An agent proposal about a VIP segment would reveal a restricted visit to every role (D-42, VIP-06), and D-42 says no agent acts on visits | **Option B** (§8): an advice-only, visit-free readiness proposal; the VIP change stays with the Security Officer on VIP Protection. PC-48 becomes the agent row only; Prompt 102 is not 🔒. |
| G-2 | The index's points | As §2, chosen so one CRITICAL incident gives about 80 and a calm mission never reaches 70; all in one table in `predictive/service.py`. |
| G-3 | The seeded history must meet today's computed value | It drifts into the calm index, so the line has no jump at "Today" in the calm state. |
| G-4 | Auditing a snapshot every 15 minutes would flood the audit log | Audit the first snapshot of each day per tenant; the updates are derived figures, recomputable from the audited sources. |
| G-5 | Signals near a mission and the "norm" | Within 50 km of the mission's location; the norm is the weekly mean over the 30 days before the last 7. |
| G-6 | Which incidents count | ACTIVE incidents with `mission_id` (the same rule as `display_risk`); MONITORING and CLOSED do not. |
| G-7 | Rising risk when nothing rises | Sorted by change; with no change above 0, the list shows the five highest peaks. |
| G-8 | 🔒 scope | The migration (Prompt 100) is 🔒. With option B the Forecast agent (Prompt 102) is not, since there is no policy or executor change; with option A it is, and a new PC for `agent_proposal` is needed. |

## 13. Migration 0015 (Prompt 100, 🔒)

- **The tables:** PC-46 `risk_index` and PC-47 `mission_event`.
  - FORCE RLS with `tenant_isolation`; only the grants proposed; no DELETE.
  - CHECKs on value 0..100, weight 1..30, attendance ≥ 0, `ends_on ≥ starts_on`, source lists, and kind lists.
- **Pinned `search_path` guards:**
  - same-tenant missions;
  - `risk_index` UPDATE only of the row whose `day` is today (UTC), only of the value and components;
  - `computed_at` written by the database;
  - `mission_event` frozen once inserted.
- **Tests (as `nexira_api`):** isolation, every refusal, the backup role reads, and the downgrade restores 0014 exactly.

## 14. Prompts

As `docs/prompts-pilot.md` Prompts 100–105. With option B, Prompt 102 adds the FORECAST agent (advice only) and is not 🔒; PC-48 is the agent row only.

Reply "approved with option B" (or "option A") to settle G-1; the rest follows as proposed.
