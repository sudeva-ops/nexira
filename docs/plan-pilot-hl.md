# Plan · Pilot module 9: Health Intelligence (Prompt 59)

For the product owner and the coding agent. It maps HL-01..10 (`docs/requirements-pilot.md` §44–48) and D-39 onto the code after pilot module 8, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner; the rest follows from approved documents. Everything is simulated (D-19, D-39); nothing external is called.

## 1. Requirements against existing code

| HL | Exists today | New work | Prompt |
|---|---|---|---|
| 01 Advisories | scenario events through Redis Streams to worker consumers (the `hazards` group for DEMO_CLOCK); `audit.write` | PC-26 `health_advisory`; a `HEALTH_ADVISORY` scenario event and a `health` consumer group; `health.service.ingest()` upserts by `external_id`, audited; `HEALTH_ADVISORY_UPDATED` to browsers and agents (§2) | 60, 61, 62 |
| 02 Affected missions | `mission.country_code` | `mission.country_code = ANY(advisory.countries)` for OPEN advisories; highest open level per mission (§3) | 61 |
| 03 Entry requirements | `trip.destination_country`; the trip detail | PC-28; `GET /api/health/requirements`; the trip detail gains `health_requirement` for its destination | 60, 61 |
| 04 Facilities | `incident.location`, `impact_radius_m`, `status`; PostGIS | PC-27; facilities by `ST_Distance` from the mission; the Avoid flag from ACTIVE incidents (§4) | 60, 61 |
| 05 Readiness | `exposure.STAFF_TYPES` (DIPLOMAT, LOCAL_STAFF) | PC-29, counts only; seeded through a service function as `nexira_api` (§5) | 60, 61, 62 |
| 06 Send | `notifications.compose.create_draft` (COMPOSERS), `submit`, the D-31 `gate`; `templates.resolve` | `POST /api/health/advisories/{id}/campaign` with a mission: a DRAFT from the topic's template, audience the mission's staff and citizens (§6) | 61 |
| 07 Agent proposal | the Communications agent (PLAYBOOK_STEP → SEND_EXTERNAL_MESSAGE); action registry; policies | a new action `PREPARE_HEALTH_ADVISORY` and executor; the agent observes `HEALTH_ADVISORY_UPDATED`; policy floor 2, `DUTY_OFFICER\|CONSULAR_OFFICER` (§7, G-2) | 61 |
| 08 Screen | Blueprint dark; `ui/motion`; `Kpi`, `Card` | the screen under MONITOR, before Natural Hazards (§9) | 63 |
| 09 Who sees what | `approvals.user_has_role`; `GET /api/me/permissions` | every role reads `GET /api/health/*`; `entity_type=health`: `send_advisory` per mission (§8) | 61 |
| 10 NBO-CHOLERA | the scenario player and presenter bar | the scenario (§10) | 62 |

## 2. The advisory feed

- **Scenario event** `HEALTH_ADVISORY`, payload `{external_id, topic, topic_code, countries, region_label, level, guidance, source, status}`. The worker's new `health` consumer group calls `health.service.ingest()` in one transaction:
  - an unknown `external_id` inserts a row (reference `HA-<n>` from `next_reference`), audited `HEALTH_ADVISORY.CREATE`;
  - a known one updates level, guidance and `updated_at` only (PC-26 grants), audited `HEALTH_ADVISORY.UPDATE` with the old and new level;
  - `status: CLOSED` closes it, audited `HEALTH_ADVISORY.CLOSE`. A closed advisory is final (the guard), so a later bulletin for it is refused and logged, not raised.
  - Frozen fields that differ in a newer bulletin (countries, topic) are ignored and logged: the feed cannot move an advisory to another country.
- **Events:** `HEALTH_ADVISORY_UPDATED {advisory_id, level, previous_level, status}` goes to browsers (realtime allow-list) and to the agents stream.
- **Seed:** `make reset-demo` creates the six advisories through `ensure_advisories()` (audited `HEALTH_ADVISORY.SEED`, as `CLIMATE_RISK.SEED`), publishing no event, so no agent reacts. None is HIGH or CRITICAL (cholera starts MODERATE, §48 Q2), so the Decision Queue stays empty at scene 0 of the Phase 1 scenario.
- A scenario is not needed for every update: the same `ingest()` is what a real feed adapter would call later (HLT-05).

## 3. Which missions an advisory affects

`affected(advisory) = missions WHERE country_code = ANY(advisory.countries)`, for OPEN advisories only. The list shows "Affects Nairobi mission" (or "Affects 3 missions"); each mission's level is the highest OPEN advisory for its country. Regional advisories (mpox in central Africa) list several countries. An advisory whose countries have no mission shows "No mission affected" and still counts as open.

## 4. Facilities and the Avoid flag

- Listed per mission, ordered by `ST_Distance(facility.location, mission.location)`, in km.
- **Avoid** = `EXISTS (incident i WHERE i.status = 'ACTIVE' AND ST_DWithin(f.location, i.location, i.impact_radius_m))`, computed on every read and never stored (PC-27). The row names the incident (`Avoid · inside INC-…-1042`). Any ACTIVE incident counts, unrest or hazard.
- Nairobi's four facilities follow the design. Nairobi Central Medical Centre is placed 1.4 km from the Embassy and inside INC-…-1042's 5 km zone, so it shows Avoid while that incident is ACTIVE. The other three are placed more than 5 km from the incident's centre, so they are outside it. Their distances from the mission may therefore differ from the design's (2.1, 3.8 and 9.6 km); Prompt 62 picks coordinates that keep them outside the zone.

## 5. Readiness counts

- `mission_health_readiness.staff` is the number of active DIPLOMAT and LOCAL_STAFF people of the mission when seeded (`exposure.STAFF_TYPES`); the other counts are illustrative and at most `staff` (CHECKs, PC-29).
- The screen shows "Cholera vaccine offered 9 / 14" for each topic in `vaccines_offered` that has an OPEN advisory for the mission's country, and "Blood type on file 14 / 14", "Medical insurance active 14 / 14", "Trauma kits at mission 6".
- **No names and no per-person data**, for every role (D-39). The readiness API returns counts only; nothing joins it to `person`.

## 6. Sending a health advisory (HL-06)

- `POST /api/health/advisories/{id}/campaign {mission_id}`: the caller must be a composer (`compose.COMPOSERS`, through `create_draft`, which checks it). It creates a **DRAFT** campaign:
  - kind `ADVISORY`, audience `{"missions": [mission_id], "person_types": [DIPLOMAT, LOCAL_STAFF, DEPENDANT, CITIZEN]}` (staff, their dependants and registered citizens), channels SMS and push, no incident;
  - text from the topic's template (G-1) for the mission, with its translations and `template_id`.
- The author then reviews it on Mass Notification and submits it; with citizens in the audience it goes to PENDING_APPROVAL and a second person approves it (D-31). Nothing new in the D-31 flow.
- Refused (409) for a CLOSED advisory, or a mission the advisory does not affect. Audited through `compose` (`CAMPAIGN.DRAFT`), and the health module adds `HEALTH_ADVISORY.CAMPAIGN` with the advisory and campaign references.

## 7. The Communications agent's proposal (HL-07)

- **Trigger:** `HEALTH_ADVISORY_UPDATED` where the new level is HIGH or CRITICAL and the previous level was lower (or none). For each affected mission without a PENDING proposal for this advisory and mission, it proposes:
  - Title: "Health advisory recommended for <city> staff and citizens".
  - Evidence: the advisory (topic, level, source), the vaccine count ("9 of 14 staff offered the cholera vaccine"), and whether the template's translations are reviewed (D-15).
  - Action `PREPARE_HEALTH_ADVISORY {advisory_id, mission_id, message, translations, channels}`, the message shown to the approvers.
  - Alternative: "English only" (as the citizen advisory).
- **Key:** `HEALTH_ADVISORY:<advisory id>:<mission id>:<level>`. The same bulletin twice is one proposal; a later rise to CRITICAL can propose again; at most one PENDING per advisory and mission (checked before proposing).
- **Executor (🔒):** creates the campaign through the notifications service in **PENDING_APPROVAL**, `created_by_type = AGENT`, `submitted_by` = the proposal's last approver (`Context.approved_by`). The D-31 gate already excludes `submitted_by`, so a **different** person (DUTY_OFFICER or CONSULAR_OFFICER) must approve the campaign before anything is queued (G-2). Not undoable; the campaign can be rejected or cancelled on Mass Notification instead.
- **Scope:** the proposal has no incident, so only unscoped (HQ) holders decide it (D-06, `proposals._mission`). The campaign's gate is scoped to its mission, as for any campaign.
- **Policy:** `PREPARE_HEALTH_ADVISORY`, floor 2 (never Auto), approvers `DUTY_OFFICER|CONSULAR_OFFICER`, deadline 1 h (as the design), not undoable.

## 8. API and who sees what

Every role, Viewer included (HL-09), reads:
- `GET /api/health/advisories`: OPEN and recently CLOSED (7 days), with the affected missions (code, city) and `simulated: true`.
- `GET /api/health/summary`: the KPIs (§9).
- `GET /api/health/requirements`: entry requirements for the mission countries.
- `GET /api/health/missions/{id}`: the mission's facilities (with distance and Avoid) and readiness counts.

`POST /api/health/advisories/{id}/campaign` needs a composer role (§6). `GET /api/me/permissions?entity_type=health&entity_id=<mission>` returns `send_advisory`. Browsers get `HEALTH_ADVISORY_UPDATED`; `staleKeys` maps it, and the existing `INCIDENT_*` events (for the Avoid flag), to the health keys.

## 9. The screen (HL-08)

- **Banner:** "Health intelligence fused from WHO Disease Outbreak News, national health ministries and medical-assistance partners. Simulated samples for demonstration." (D-19).
- **KPIs:**
  - open advisories, with how many affect mission countries;
  - missions with an advisory, by level;
  - staff not yet offered a vaccine for an open advisory in their country (G-3);
  - vetted facilities (those with `vetted_by`).
- **Tables and panels:**
  - the advisories table: event, location, level, published, guidance, affected missions;
  - entry requirements for the mission countries;
  - a mission picker (default: the mission with the highest advisory level, then the most staff), showing that mission's facilities with Avoid, its readiness counts, and "Send health advisory to <city>" when `send_advisory` allows it.

Under MONITOR, before Natural Hazards & Climate (§48 Q9).

## 10. Scenario `NBO-CHOLERA` (HL-10)

| Scene | Events | Expect |
|---|---|---|
| 0 Calm | — | the six seeded advisories; cholera in Kenya MODERATE |
| 1 Cholera rising | `HEALTH_ADVISORY` for the seeded cholera `external_id`: level HIGH, new guidance | cholera HIGH, "Affects Nairobi mission"; the Communications agent's proposal in the Decision Queue |
| 2 Dengue closed | `HEALTH_ADVISORY` for dengue: `status: CLOSED` | dengue drops off the open list |

Presenter bar: scene 1 opens `/health`, scene 1's proposal is decided on `/`, and scene 2 opens `/health`. The scenario needs no incident and no new people.

## 11. Gaps and conflicts, with proposed answers

| # | Gap | Proposed answer |
|---|---|---|
| G-1 | **Template kind.** §46 says a HEALTH_ADVISORY template kind is "data, not schema", but `message_template.kind` has a CHECK of `ALERT`, `ADVISORY`, `CHECKIN` (migration 0002). Templates also only fill in `{city}`, and filling in an English `{guidance}` would put English inside the AR/FR/SW texts (D-15). | **Needs a decision.** Keep kind `ADVISORY` (no schema change). One template **per topic**, coded `HEALTH_<TOPIC_CODE>` (e.g. `HEALTH_CHOLERA`), generic with `{city}`, plus Nairobi's own `HEALTH_CHOLERA` with the design's text. That needs a stable `topic_code` on the advisory, so **amend PC-26: add `topic_code text NOT NULL`** (upper-case, frozen). A topic with no template gets the generic `HEALTH_GENERAL` template ("A health advisory is in force for {city}. Follow the mission's guidance."). |
| G-2 | **Approving the proposal must not send.** `SEND_EXTERNAL_MESSAGE` queues the campaign as soon as the proposal is approved; HL-07 says approving "creates the campaign, which still needs its second person". | A new action `PREPARE_HEALTH_ADVISORY` (§7): the campaign is created PENDING_APPROVAL with the proposal's approver as `submitted_by`, so the existing D-31 gate needs a different person. `SEND_EXTERNAL_MESSAGE` is unchanged. 🔒 (executor and policy, D-29). |
| G-3 | **"Vaccinations due".** HL-08's KPI says "offered, not yet given", but readiness has no "given" count (counts of offers only, PC-29). | The KPI is **"Staff not yet offered a vaccine"**: for each OPEN advisory topic in a mission's `vaccines_offered`, `staff − offered`, summed. The design's "within 30 days" is dropped. |
| G-4 | **Nairobi's staff count.** HL-05's acceptance says "9 / 17", from the design, but Nairobi has 14 staff (12 diplomats, 2 local staff) and 3 delegates. Readiness counts staff (§5). | **Needs a decision.** Amend the acceptance to **"Cholera vaccine offered 9 / 14"** (and 14 / 14 for blood type and insurance). Counting delegates would make "staff" mean two things. |
| G-5 | **Proposals without an incident** can be decided only by unscoped holders (D-06). A Head of Mission is not an approver anyway; a mission-scoped Consular Officer could not decide it. | As D-06. The demo's Duty Officer and Consular Officer are unscoped. |
| G-6 | **One open proposal.** `proposal_key` is unique forever, so a key per advisory and mission would never propose again after a fall and a new rise. | Key by advisory, mission and level, and skip while one is PENDING (§7). |
| G-7 | **The agent stream.** The agents runner observes the events in its allow-list only. | Add `HEALTH_ADVISORY_UPDATED` to the agents' observed events and `Communications.observes`. Phase 1 events are unchanged. |
| G-8 | **Avoid and realtime.** The Avoid flag changes when an incident opens, closes or moves to MONITORING, with no health event. | `staleKeys` maps `INCIDENT_CREATED` and `INCIDENT_UPDATED` to the health keys too. |
| G-9 | **Trips.** HL-03 shows requirements "on the trip". The trip detail is the Journey Management screen. | The trip detail API gains `health_requirement` (or `null`); the trip panel shows one line "Entry: … · Recommended: …". There are no warnings and no change to risk (§45 "Not in this module"). |

## 12. Migration 0009 (Prompt 60, 🔒, after approval of G-1)

`0009_health.sql` and `versions/0009_health.py`:
- `health_advisory` (with `topic_code` if G-1 is approved):
  - a guard trigger (`health_advisory_guard`): CLOSED is final; topic, topic_code, countries, region_label, source, external_id and published_at frozen; level and status from their lists; `updated_at = now()` on UPDATE;
  - `UNIQUE (tenant_id, external_id)`; index `(tenant_id, status)`.
- `medical_facility`: a same-tenant mission and partner, checked by a guard (as `weather_current_guard`); a GiST index on `location`.
- `country_health_requirement`: PRIMARY KEY `(tenant_id, country_code)`.
- `mission_health_readiness`: PRIMARY KEY `(tenant_id, mission_id)`. CHECKs: each count is from 0 to `staff`. The guard checks each `vaccines_offered` value the same way, and that the mission is in the same tenant.
- All four tables:
  - FORCE RLS with `tenant_isolation`;
  - grants as PC-26..29 (UPDATE on `health_advisory` limited to `level, guidance, status, updated_at`), and SELECT for the backup role;
  - guard functions with a pinned `search_path`.
- The downgrade drops the four tables and restores revision 0008 exactly.

Tests run as `nexira_api` and cover: tenant isolation; every guard refusal; no DELETE; no UPDATE on the three seeded tables; the backup role reads them; and the downgrade.

## 13. Prompts

| Prompt | 🔒 | Content |
|---|---|---|
| 60 | yes | Migration 0009 (§12) |
| 61 | yes | `app/modules/health` (ingest, affected missions, facilities and Avoid, readiness, requirements, send), the trip's `health_requirement`, `PREPARE_HEALTH_ADVISORY` and its policy, the Communications agent's rule, permissions; tests against real PostgreSQL |
| 62 | no | The simulated feed, the seed (six advisories, 36 countries' requirements, about three facilities per mission and Nairobi's four, readiness for 36 missions, the HEALTH_* templates), NBO-CHOLERA, the presenter bar entry |
| 63 | no | The screen (§9), realtime keys, the trip line; Vitest |
| 64 | no | Playwright (§47, with G-4's figures); `make acceptance` |
