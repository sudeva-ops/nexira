# Plan · Pilot module 12: VIP & Delegation Protection (Prompt 77)

For the product owner and the coding agent. It maps VIP-01..08 (`docs/requirements-pilot.md` §59–63) and D-42 onto the code after pilot module 11, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner; the rest follows from approved documents. Everything is simulated (D-19, D-42); nothing external is called, and no position of a principal, team or motorcade is ever stored or shown.

## 1. Requirements against existing code

| VIP | Exists today | New work | Prompt |
|---|---|---|---|
| 01 Programme | `trip.restricted` (D-33; frozen once submitted); `mission`; reference counters | PC-35 `vip_visit`, PC-36 `vip_segment`, seeded through `vip.service.ensure_visits()` as `nexira_api`; a new restricted TRP-8834 (§2) | 78, 80 |
| 02 Risk | incidents (`location`, `impact_radius_m`, `severity`, ACTIVE); `weather_current.condition`; `country_risk.level` | `vip.service` works out each segment's risk with reasons on every read (§3) | 79 |
| 03 Detail and checklist | fleet assets; `medical_facility` (three per mission); partner coverage (Kestrel); sites | the detail is read from Fleet, Health and Partners at read time; PC-37 `vip_checklist_item` (§4) | 78, 79 |
| 04 Live status | the scenario player and worker consumers | start, progress (person or `VIP_PROGRESS`), complete, cancel; no positions (§5) | 79, 80 |
| 05 Changes | `approvals.Gate` and `decide()` (D-05, D-16) | PC-38 `vip_segment_change`; propose and decide through `approvals.decide()` (§6) | 78, 79 |
| 06 Restriction | `approvals.user_has_role()`; realtime forwards per tenant | `vip.service.reader_scope()`; 404 for everyone else; **no realtime forwarding** (§7, G-3) | 79 |
| 07 Screen | Blueprint dark; `Kpi`, `Card`; `GET /api/me/permissions` | the screen under RESPOND after Fleet & Assets, its nav entry shown only to readers (§8) | 81 |
| 08 ADD-VISIT | scenario player; presenter bar; RAW_SIGNAL fusion | the scenario: progress events and a rally signal (§9) | 80 |

## 2. The visit and the seed (VIP-01, §63 Q1)

- **VV-2026-031**, "Minister's visit to Addis Ababa":
  - mission ADD; principal role "Minister of Foreign Affairs";
  - from scenario day +4 to +6; status PLANNED;
  - linked to **TRP-8834**, a new restricted trip (Abu Dhabi → Addis Ababa). Its travellers are two fictional HQ delegation staff; the principal is not a person in the system (G-6).
  - The reference comes from the `VV` counter (with year).
- **Six segments, as the design.** Times are Addis local (UTC+3), stored in UTC.

| # | Kind | Segment | Venue | When | Attendees |
|---|---|---|---|---|---|
| 1 | ARRIVAL | Arrival · Bole Intl. Airport (VIP terminal) | Bole airport | day +4, 09:30 | — |
| 2 | MOTORCADE | Motorcade · Airport → Hotel | the hotel | day +4, 09:50 for 14 min | — |
| 3 | MEETING | Bilateral meeting · Ministry of Foreign Affairs | the Ministry | day +4, 11:00 | — |
| 4 | EVENT | Business forum · Conference centre | the conference centre | day +4, 14:00 | 600 |
| 5 | SITE_VISIT | Site visit · Industrial park | the industrial park, about 11 km east of the airport (G-4) | day +5, 10:00 | — |
| 6 | DEPARTURE | Departure | Bole airport | day +6, 16:00 | — |

- **The detail** (PC-35 `detail`; labels only, §63 Q3):
  - team lead "Close-protection lead (sample)"; advance team "3 officers"; team size 8; a medic;
  - vehicles `["VH-11", "VH-12"]`;
  - safe havens: "Embassy", "Hotel safe floor", and the nearest hospital.
- **The checklist** (PC-37), all done by the seeded Security Officer except the last:
  - "Threat assessment issued", "Host-nation security liaison confirmed" and "Hospital & evacuation plan", done;
  - "Industrial park venue survey", due day +3, open (G-7).

## 3. Segment risk (VIP-02, §63 Q5)

The rules are applied on every read, in one SQL query per visit, with every reason kept:

- **Incidents.** For each ACTIVE incident, the distance from the venue to the edge of its zone is `greatest(0, ST_Distance(venue, i.location) − i.impact_radius_m)`.
  - Up to 2 km gives **HIGH**; up to 5 km gives **MODERATE**.
  - The reason reads "unrest 1.2 km away · INC-…", using the distance to the incident's centre and the category label.
  - Weather warnings are incidents too (D-35), so storms count here.
- **Weather.** The mission's `weather_current.condition` is STORM or a similarly severe condition: MODERATE ("severe weather").
- **Attendees.** 500 or more: MODERATE ("600 attendees").
- **Motorcades.** At least MODERATE ("exposed movement").
- **The visit's risk** is the highest segment risk, or `country_risk.level` of the mission's country if that is higher.
- **The recommendation** for a HIGH segment, as text: "Move it out of the window, or replace it with a virtual alternative".
- **Completed segments** are shown with their risk, but the visit's risk uses only open segments.

Before the demo this gives the motorcade and the forum MODERATE, the rest LOW, and the visit MODERATE (as the design). After the rally (§9) the site visit is HIGH.

## 4. Detail, safe havens and the checklist (VIP-03)

- **Vehicles:** the codes in `detail` are read from `fleet_asset`, with the live Fleet state (available, blocked, in zone or maintenance). Fleet itself never shows a visit link (G-8).
- **Medical:** the nearest `medical_facility` of the mission that is not marked Avoid (HL-04), plus the active MEDICAL partner covering the country (Kestrel).
- **Safe havens:** the labels in `detail`, with the hospital name filled in at read time.
- **The checklist:** `POST /api/vip/checklist/{id}/done` by a Security Officer or the mission's Head of Mission, through `approvals.user_has_role()`. It is done once (409 after), and audited `VIP.CHECKLIST_DONE`.

## 5. During the visit (VIP-04, §63 Q4)

- **Start.** `POST /api/vip/visits/{id}/start` by a Security Officer or the mission's Head of Mission: PLANNED → LIVE (`VIP.START`).
- **Progress.** `POST /api/vip/segments/{id}/progress` moves a segment one step forward (PLANNED → IN_PROGRESS → COMPLETED), by the same roles, while LIVE (`VIP.SEGMENT`). The worker's `VIP_PROGRESS {visit, seq, status}` events do the same as the SYSTEM actor "visit progress (simulated)".
- **Complete.** The departure COMPLETED completes the visit.
- **Cancel.** `POST /api/vip/visits/{id}/cancel` by the HQ Crisis Director, with a reason (`VIP.CANCEL`).
- **No positions.** No position field exists anywhere in the VIP tables, APIs or events.

## 6. Two-person changes (VIP-05, §63 Q7)

- **Propose.** `POST /api/vip/segments/{id}/changes` `{new_starts_at, new_ends_at | make_virtual, reason}` by a Security Officer, for any visit status but final ones. One PENDING change per segment (PC-38). Audit `VIP.CHANGE_PROPOSE`.
- **Decide.** `POST /api/vip/changes/{id}/approve | reject` `{note}` goes through `approvals.decide()` with a `Gate`:
  - `required_role` = `HEAD_OF_MISSION|HQ_CRISIS_DIRECTOR`;
  - `mission_id` = the visit's mission;
  - `deciders_of_other_steps` = {the proposer}.

  On approval, the segment's times or `virtual` are written in the same transaction (the PC-36 guard checks that). Audit `VIP.CHANGE_APPROVE` or `REJECT`.
- **After a change,** the segment's risk is worked out again on the next read. Moving the site visit to 08:00 does not lower its risk by itself while the rally incident is ACTIVE; making it virtual does (a virtual segment has no venue risk). The screen shows both options (G-5).

## 7. Who sees a visit (VIP-06, §63 Q2)

- **`reader_scope(user)`.** The union of SECURITY_OFFICER, HQ_CRISIS_DIRECTOR and DUTY_OFFICER grants (unscoped or per mission) and HEAD_OF_MISSION per mission, as `evacuations.name_scope()`. A visit is visible when its mission is in the scope.
- **Everyone else** gets 404 for every visit URL, `[]` for the list, and `{visible: false}` from `GET /api/vip/access`. The screen and the nav use that call.
- **No realtime (G-3).** Realtime forwards to every socket of a tenant (`app/core/realtime.py`), so a `VIP_UPDATED` event would tell everyone that a visit exists. VIP events are **not forwarded**. The screen refetches every 10 s while it is open and after its own actions. Changing the realtime fan-out to filter by role would touch a 🔒 file and is not needed for the pilot.
- **Audit and the rest.** Audit uses `entity_type = 'vip_visit'` and the reference; details give references, statuses and counts, never venues, times or the principal's role. Nothing reaches the map, notifications, agents (no agent reads VIP tables) or Air Travel (TRP-8834 is restricted, so its flights are never tracked; D-33).

## 8. The screen (VIP-07, §63 Q8)

- **Placement:** "VIP Protection" (icon `shield`), under RESPOND after Fleet & Assets. The nav entry is shown only when `GET /api/vip/access` says visible. For others, the URL shows a restricted message and no data.
- **As the design:**
  - the banner: the visit and dates, the linked trip, and **Start visit** when allowed; LIVE shows a green "LIVE" tag, "programme status only";
  - KPIs: programme segments · "N rated High"; close-protection team · "2 vehicles · 1 medic"; venues surveyed (survey checklist items done out of venues); visit risk;
  - "Programme & route risk": segment, time, risk with its reasons, status, and progress buttons when allowed. A HIGH segment gets an amber recommendation box with **Propose change** (time or virtual, with a reason). A pending change shows **Approve** and **Reject** for the decider, and "waiting for …" for others;
  - "Protection detail";
  - "Pre-visit checklist" with **Mark done**.
- **Other:** a visit picker when there are several. The incident behind a HIGH risk links to Incidents.

## 9. Scenario `ADD-VISIT` (VIP-08, §63 Q9)

| Scene | Events |
|---|---|
| 0 Planned | marker only (scene 0 plays on Play, not on Next) |
| 1 Live | `VIP_PROGRESS` to start: the visit LIVE; the arrival IN PROGRESS, then COMPLETED; the motorcade IN PROGRESS |
| 2 Rally | a simulated RAW_SIGNAL (category CIVIL_UNREST, severity Moderate, "Planned rally · industrial park access road") 1.2 km from the industrial park; fusion opens an Addis Ababa incident, and the site visit is HIGH |
| 3 Forum | the motorcade, the meeting and the forum COMPLETED |

The change is proposed and decided by people in the browser; the scenario approves nothing. The rally is MODERATE, so the Response Planner's PB-07 trigger (HIGH civil unrest near staff) is not met. This is checked in Prompt 80.

## 10. Acceptance specs (§62)

`vip-acceptance.spec.ts` (after `ta-`, before `wx-`, by name; added to `make acceptance`) covers:
- **The seeded visit:** six segments, MODERATE risk, three of four checklist items, VH-11 and VH-12 from Fleet;
- **ADD-VISIT** from the presenter bar: LIVE; the rally gives the site visit HIGH;
- **The change:** the Security Officer proposes it and is refused the approval; it is decided (G-1); the segment moves;
- **The checklist:** the survey is ticked;
- **Restriction:** the Viewer, Travel Desk and the Cairo Head of Mission get 404, empty lists and no nav entry; no position in any response;
- **Audit:** the trail, and the chain verifies.

The Phase 1 spec is unchanged.

## 11. Gaps and conflicts, with proposed answers

| # | Gap | Proposed answer |
|---|---|---|
| G-1 | **Needs a decision.** §62 says the Addis Ababa Head of Mission approves the change, but the demo realm has Head of Mission users only for Nairobi and Cairo. | The **HQ Crisis Director** decides in the demo and the acceptance: VIP-05 allows either. `hom.nairobi` and `hom.cairo` still show the mission scoping (refused). Adding an `hom.addis` demo user would change the Keycloak realm and the seeded roles for one click. |
| G-2 | The visit's "venues surveyed" KPI | Count of checklist items whose label starts "… venue survey" done, out of the segments with a venue (5 of the 6; the departure shares the arrival's airport). Design: 4 / 5. |
| G-3 | Realtime would reveal visits to everyone in the tenant | VIP events are not forwarded; the screen polls every 10 s while open (§7). |
| G-4 | A 5 km unrest zone over the city would make every venue HIGH | The industrial park sits about 11 km east of Bole airport and 16 km from the city venues, so only it is near the rally (as the design: one HIGH segment). |
| G-5 | Does moving the time lower the risk? | Not while the incident stays ACTIVE (the rules use place, not time). The design's recommendation offers both options; the demo moves it to 08:00 as the design, and the screen notes that the risk stands until the incident ends or the segment is virtual. |
| G-6 | The principal is not a person | The trip's travellers are two fictional HQ delegation staff; the principal's role is a label on the visit. No person, name or position of the principal exists. |
| G-7 | Seeded checklist items need a done-by user | The seeded Security Officer (`security.officer`), whose user exists after the identities are seeded. |
| G-8 | Fleet shows VH-11 and VH-12 to everyone | Fleet keeps showing the vehicles and their states, but never the visit or "assigned to visit": the link lives only in the visit. |
| G-9 | The Duty Officer is a reader, but should it act? | It reads only. Acting stays with the Security Officer, the mission's Head of Mission (start, progress, checklist) and the HQ Crisis Director (decide, cancel). |
| G-10 | 🔒 scope | The migration (Prompt 78) and the service's visibility and approval checks (Prompt 79) are 🔒 under D-29. |

## 12. Migration 0012 (Prompt 78, 🔒)

- **The tables:** PC-35..38 as approved.
  - FORCE RLS with `tenant_isolation`.
  - `SELECT, INSERT` and column UPDATE grants only, with no DELETE; the guards refuse a delete for the owner too.
  - Pinned `search_path` guards that check same-tenant references and write the times.
- **`vip_visit` guard:** forward-only status; final states; the trip restricted; `started_*` and `cancelled_*` set only with their transition.
- **`vip_segment` guard:**
  - forward-only status, only while the visit is LIVE, and only one step at a time;
  - `starts_at`, `ends_at` and `virtual` change only when the same transaction approved a PENDING change for the segment. The guard looks for a `vip_segment_change` of this segment with `status = 'APPROVED'` and `decided_at = now()`, as the evacuation manifest's activation check.
- **`vip_checklist_item` guard:** done once, by a real user of the tenant.
- **`vip_segment_change` guard:** decided once; `decided_by <> proposed_by` and a real user; the partial unique index allows one PENDING change per segment.
- **Tests (as `nexira_api`):** isolation, every refusal, no DELETE, the backup role reads, and the 0012 downgrade restores 0011 exactly.

## 13. Prompts

As `docs/prompts-pilot.md` Prompts 78–82: the migration (🔒); the service (🔒); the seed and ADD-VISIT; the screen; the acceptance. Each ships with its tests, and `make acceptance` passes at the end.
