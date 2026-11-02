# Plan · Pilot module 13: Site Twin (Prompt 83)

For the product owner and the coding agent. It maps TWN-01..07 (`docs/requirements-pilot.md` §64–68) and D-43 onto the code after pilot module 12, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner; the rest follows from approved documents. Everything is simulated (D-19, D-43); nothing external is called, NEXIRA controls nothing on site, and presence never becomes a location observation.

## 1. Requirements against existing code

| TWN | Exists today | New work | Prompt |
|---|---|---|---|
| 01 Floor plan | `site` (embassy, residence, hotel per mission) | PC-39 `site_zone`, PC-40 `site_route`, seeded through `twin.service.ensure_plans()` as `nexira_api` (§2) | 84, 86 |
| 02 Occupancy | `person` (11 Nairobi staff at "Embassy", `ACCESS_CONTROL`); `evacuations.name_scope()` | PC-41 `site_presence`; `SITE_PRESENCE` events in the worker; names by scope (§3) | 84, 85, 86 |
| 03 Sensors | `fleet_asset` GEN-NBO and SAT-NBO with their state and fuel; incident timeline (`incident_event`, free-text type) | PC-42 `site_sensor`; `SITE_SENSOR` events; SITE timeline entries for faults in an ACTIVE zone (§4) | 84, 85, 86 |
| 04 Overlays | PB-07 step 4 "Issue shelter-in-place advisory" (DONE in the Phase 1 run before the check-in); `evacuation` ACTIVE per mission | worked out on read (§5) | 85 |
| 05 Readiness | **`site.readiness_score` and `site.last_drill_on` already exist** (People & Sites shows them; Nairobi embassy: 79, drilled 3 weeks before the scenario date) | PC-42 `site_readiness_item`; the tick through `approvals.py`; the derived access item (§6, G-1) | 84, 85 |
| 06 Screen | Blueprint dark; `Kpi`, `Card`; realtime; `GET /api/me/permissions` | the screen under RESPOND after Assistance Partners; SVG plan (§8) | 87 |
| 07 NBO-SITE | scenario player; presenter bar; `FLEET` timeline precedent | the scenario: sensor and presence events (§9) | 86 |

## 2. The plan and routes (TWN-01, §68 Q1)

- **Embassy Nairobi, ground floor**, in plan units (the design's 790 × 455 viewBox):

| Code | Name | Kind | x, y, w, h | Capacity |
|---|---|---|---|---|
| ch | Chancery offices | OFFICE | 130, 30, 270, 220 | — |
| amb | Ambassador suite | SUITE | 415, 30, 160, 110 | — |
| conf | Conference room | CONFERENCE | 415, 155, 160, 95 | — |
| comms | Comms / IT room | COMMS | 590, 30, 180, 100 | — |
| safe | Safe room (hardened) | SAFE_ROOM | 590, 145, 180, 105 | 20 |
| lob | Lobby & reception | LOBBY | 130, 265, 170, 120 | — |
| cons | Consular hall | CONSULAR | 315, 265, 260, 120 | — |
| must | Muster point · courtyard | MUSTER | 590, 265, 180, 60 | 60 |
| g1 | Gate 1 | GATE | 20, 320, 95, 65 | — |
| g2 | Gate 2 | GATE | 680, 340, 90, 45 | — |

- **Routes** (PC-40): A "Route A → main road via Gate 1" and B "Route B → vehicles via Gate 2", as plan points. The design shows B during an evacuation.
- Other sites show "No floor plan yet". The hotel site (trade delegation) is not a mission building and gets no plan.

## 3. Presence (TWN-02, §68 Q2, Q3)

- **Seed:** the 11 Nairobi staff whose place is "Embassy" in the seed (Omar Siddiqui, Martin Keller, Aisha Rahman, Grace Wanjiru, Sara Lindqvist, Yusuf Al-Amin, Nadia Petrova, Karim Mansour, Ruth Achieng, David Okafor, James Otieno), in the design's rooms; "Guard 1..3" at Gate 1, Gate 2 and the lobby; "Visitor 1..11" in the consular hall (9) and the lobby (2). 25 on site.
- **The feed:** `SITE_PRESENCE {site, occupant, zone | null}` (occupant = a person's seed key or a label). It moves an occupant, adds an arrival, or removes a departure (`zone: null`). The actor is SYSTEM "access control (simulated)". Only events from the scenario player are taken (the lesson of Prompt 80, M1).
- **Names:** the `person_id` of a STAFF row is resolved to a name only when `evacuations.sees_names()` covers the mission. Others get `"Staff"`, the kind and the zone. GUARD and VISITOR rows carry labels only.
- **No location observation (D-43):** nothing is written to `location_observation`. People & Sites, exposure, the check-in and every Phase 1 figure stay as they are. A backend test checks the People & Sites figures before and after presence moves.
- **Audit:** `SITE.PRESENCE` with the zone codes and the kind, and the person id for staff (never the name).

## 4. Sensors (TWN-03, §68 Q5)

- **Seed: 43 per site plan.**
  - Gate 1 · main (GATE); Gate 2 · badge reader (BADGE_READER); the safe room (SAFE_ROOM);
  - 16 cameras (CCTV, `CAM-01..16`, spread over the zones);
  - 24 access and alarm points (ACCESS and ALARM: doors, panic buttons);
  - all OK.
- **The feed:** `SITE_SENSOR {site, code, status, detail}`. The actor is SYSTEM "building systems (simulated)". Audit `SITE.SENSOR`.
- **The generator and satellite comms** are read from Fleet (`GEN-<mission>`, `SAT-<mission>`): their state and fuel, shown as "Generator · AVAILABLE · 72%". They are not counted in the 43; the screen's "Sensors online" counts the site's sensors.
- **Timeline entries:** a change to FAULT or OFFLINE, at a site inside an ACTIVE incident's zone, writes `incident_event` type `SITE` ("Embassy Nairobi · Gate 2 badge reader: FAULT"), actor SYSTEM. A recovery writes one too. Only changes write, as Fleet's crossings (G-4 of FLT).
- **"Sensors online":** OK or DEGRADED count as online. The design shows 41 / 43 with one FAULT and one OFFLINE camera, and "CCTV 15 / 16 online" (DEGRADED counts as online, OFFLINE does not).

## 5. Overlays, worked out on every read (TWN-04, §68 Q4)

- **Shelter-in-place is active for a site** when, for an ACTIVE incident whose `mission_id` is the site's mission, a playbook run has a DONE step whose configuration carries a `citizen_advisory_template`. That step is the shelter alert: PB-07 step 4, PB-06 step 3 and PB-01's alert.
  - The Phase 1 run completes PB-07 step 4 before the check-in, so after the Phase 1 spec Nairobi shelters.
  - It clears when the incident is no longer ACTIVE.
  - The screen shows the banner, the safe room highlighted with "N / 20", and Gate 1's sensor detail ("Locked down") when the scenario has set it.
- **The evacuation route** shows while the mission has an ACTIVE evacuation (EV-05). Route B is the plan's EVACUATION route whose exit is Gate 2. With two routes, the one named in the evacuation plan's `route_label` is chosen, if it matches; otherwise Route B (G-5).
- Neither overlay is stored, so both clear by themselves.

## 6. Readiness (TWN-05, §68 Q7)

- **The score and last drill come from `site.readiness_score` and `site.last_drill_on`** (G-1). These are the values People & Sites already shows: Nairobi embassy 79, drilled on the scenario date minus 3 weeks.
- **Items (PC-42 `site_readiness_item`):** "Floor wardens assigned (3)", "Safe room supplies checked · 14 d" and "Evacuation routes A & B surveyed", seeded done by the seeded Security Officer (as VIP G-7). There is also one open item, "Generator load test witnessed", so the tick can be shown (G-6).
- **The tick:** `POST /api/sites/readiness/{id}/done`, by a Security Officer or the mission's Head of Mission through `approvals.user_has_role()`. It is done once (409 after), audited `SITE.READINESS_DONE`, and refused for a Viewer (403).
- **"All access points monitored"** is derived: open while any GATE or BADGE_READER sensor is FAULT or OFFLINE ("Gate 2 manual").

## 7. Who sees what (§68 Q3)

- Every role reads plans, counts, sensors, overlays and readiness (as Fleet). Staff names only within the people scope.
- `GET /api/me/permissions?entity_type=site&entity_id=<site>` returns `tick_readiness`.
- **Realtime:** `SITE_UPDATED {site_id, change: presence|sensor|readiness, counts}` is added to `FORWARDED`. It carries ids and counts, never names. The screen refetches on it.

## 8. The screen (TWN-06, §68 Q8)

- "Site Twin" (icon `grid-layout`, Blueprint's nearest to the design's `grid`) under RESPOND after Assistance Partners.
- **A site picker** lists the sites with a plan; it opens on the Nairobi embassy.
- **KPIs:**
  - On site now: "25", "11 staff · 3 guards · 11 visitors";
  - Safe room occupancy: "N / 20", "Sealed" while sheltering, else "Ready";
  - Sensors online: "41 / 43", "2 faults";
  - Site readiness: the score, "Last drill N weeks ago".
- **The floor plan (SVG, viewBox 790 × 455).**
  - Rooms with names and counts; occupants as dots (staff blue, guards violet, visitors orange); tooltips with a name only within scope.
  - The safe room is outlined green, filled while sheltering. A gate with a faulty sensor is outlined red.
  - The route is drawn as a dashed green path with its label.
- **Right column:** "Sensors & systems" (the gates, CCTV "15 / 16 online", the safe room, the generator and satellite comms from Fleet); "Occupancy by zone"; "Emergency readiness" with **Mark done**.
- **Banners:** "Shelter-in-place active: N staff in safe room, …" from the counts, plus "Route B approved via Gate 2" while evacuating.

## 9. Scenario `NBO-SITE` (TWN-07, §68 Q9)

| Scene | Events |
|---|---|
| 0 Ready | marker only (scene 0 plays on Play, not on Next) |
| 1 Faults | `SITE_SENSOR` Gate 2 badge reader FAULT "Fault · manual guard"; `CAM-07` OFFLINE |
| 2 Shelter | `SITE_PRESENCE`: 9 staff (chancery, conference, consular) to the safe room; the 11 visitors to the conference room; `SITE_SENSOR` Gate 1 "Locked down" (still OK) |
| 3 Recovery | Gate 2 reader OK "Online"; `CAM-07` OK; Gate 1 "Open · screening" |

- It is played after NBO-CIVIL-UNREST scene 2, so INC-<year>-1042 is ACTIVE and the embassy is inside its zone.
- Scene 1 writes two SITE timeline entries; scene 3 writes two more (the recoveries).
- Scene 1 first resets presence and sensors to the seeded state, so a replay starts from the same place, as NBO-FLEET does.
- It approves nothing and proposes nothing. The Response Planner reads no site tables.

## 10. Acceptance specs (§67)

- **`twn-acceptance.spec.ts`** runs after `ta-` and before `vip-` by name, and is added to `make acceptance`.
  - The plan, 25 on site, 43 / 43, readiness 79, and GEN-NBO from Fleet.
  - With the Phase 1 run's PB-07 step 4 done and INC-1042 ACTIVE: shelter banner on.
  - NBO-SITE scenes 1–3: 41 / 43 and the SITE entries; 9 / 20 in the safe room; 43 / 43.
  - The readiness tick (Security Officer yes, Viewer 403).
  - Names: the Viewer and the Cairo Head of Mission see none; the Duty Officer does.
  - Audit, and the chain verifies.
- **Route B needs an ACTIVE evacuation,** but EVN-1001 is completed by `ev-acceptance` before `twn-` runs. The Phase 1 spec gets one Site Twin check after scene 5 (Route B shown while EVN-1001 is ACTIVE), as it did for Fleet (G-3).
- The other specs are unchanged. The Fleet spec counts only FLEET timeline entries, so SITE entries do not change it.

## 11. Gaps and conflicts, with proposed answers

| # | Gap | Proposed answer |
|---|---|---|
| G-1 | **Needs a decision.** The `site` table already has `readiness_score` and `last_drill_on`, which People & Sites shows (Nairobi embassy 79). PC-42's `site_readiness` table would hold a second score (the design's 91). | Drop `site_readiness` from PC-42 and read the existing columns, so there is one value everywhere. §67's "readiness 91" becomes the seeded **79**. `site_readiness_item` and `site_sensor` stay as approved. |
| G-2 | "Sensors online" with DEGRADED, FAULT and OFFLINE | OK and DEGRADED count as online; FAULT and OFFLINE do not. The design's 41 / 43 is one FAULT (Gate 2 reader) and one OFFLINE camera. |
| G-3 | Route B in the acceptance needs an ACTIVE evacuation | One check in the Phase 1 spec after scene 5, as Fleet's; `twn-acceptance` checks that the route is gone after EVN-1001 completes. |
| G-4 | Shelter-in-place "after PB-07 step 4" for any playbook | Any DONE step whose configuration has a `citizen_advisory_template` (the shelter alert of PB-07, PB-06 and PB-01), for an ACTIVE incident of the site's mission. |
| G-5 | Which route an evacuation uses | The plan's EVACUATION route matching the evacuation plan's `route_label`, else Route B (Nairobi's plan names Route B). |
| G-6 | Everything seeded done leaves nothing to tick | A fourth open item, "Generator load test witnessed", so the acceptance can tick one. The three design items stay done. |
| G-7 | Who is the seeded "done by" | The seeded Security Officer, as VIP G-7. |
| G-8 | `SITE_UPDATED` in realtime | Added to `FORWARDED` with ids and counts only. Every role may see counts (§68 Q3), so forwarding to all sockets reveals nothing more. |
| G-9 | A replay of NBO-SITE | Scene 1 resets the 25 occupants and the changed sensors to the seed first (as NBO-FLEET's residence reset). No `make reset-demo` is needed. |
| G-10 | 🔒 scope | The migration (Prompt 84), and the service's tick and name scope (Prompt 85), are 🔒 under D-29. |

## 12. Migration 0013 (Prompt 84, 🔒)

- **The tables:** PC-39 `site_zone`, PC-40 `site_route`, PC-41 `site_presence`, and PC-42 `site_sensor` and `site_readiness_item` (without `site_readiness`, G-1).
  - FORCE RLS with `tenant_isolation`.
  - Only the grants proposed.
  - Pinned `search_path` guards: same-tenant site; a zone of the same site; a person of the site's mission for STAFF; label rules by kind; frozen columns; `since`, `status_at` and `done_at` written by the database; done once.
- **Deletes:** `site_presence` allows DELETE (a departure). Every other table refuses DELETE for every role.
- **Tests (as `nexira_api`):** isolation, every refusal, the backup role reads, and the downgrade restores 0012 exactly.

## 13. Prompts

As `docs/prompts-pilot.md` Prompts 84–88: the migration (🔒); the service (🔒); the seed, feeds and NBO-SITE; the screen; the acceptance. Each ships with its tests, and `make acceptance` passes at the end.
