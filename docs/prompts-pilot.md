# NEXIRA · Pilot prompts for the AI coding tool · v0.1

For the coding agent, after the product owner approves `docs/requirements-pilot.md`. They continue the numbering of `docs/prompts.md`, which ended at Prompt 16. The rules are the same:
- one prompt at a time, in order, with one branch and one PR per prompt;
- `make test lint` before declaring a prompt done;
- 🔒 prompts need a named human reviewer's sign-off (D-29);
- the Phase 1 acceptance scenario (`make acceptance`) must still pass after every prompt (D-30).

Sources of truth, in this order: `docs/decisions.md` (D-30, D-31), `docs/requirements-pilot.md` (MN-01..12), `docs/schema/proposed-changes.md` (PC-07, PC-08).

---

## Pilot module 1 · Mass Notification

### Prompt 17 · Read and plan (no code)
```
Read AGENTS.md, docs/decisions.md (D-05, D-15, D-16, D-29, D-30, D-31),
docs/requirements-pilot.md and the notifications, checkin, playbooks and agents modules.
Write docs/plan-pilot-ntf.md:
- how each MN requirement maps to existing code, and what is new;
- the API you will add (paths, request and response shapes, roles);
- gaps or conflicts between the documents, each with a proposed answer;
- the migration you will write for PC-07 and PC-08 (only after they are approved).
No code changes.
```

### Prompt 18 · Templates and campaign approval columns (migration) 🔒
```
PC-07 and PC-08 were approved by the product owner on 2026-10-25 (PR #16).

- New Alembic migration (never edit 0001):
  - message_template (PC-07) with FORCE RLS, the tenant_isolation policy and grants to
    nexira_app;
  - the notification_campaign changes (PC-08), including the trigger that refuses
    approved_by = created_by.
- nexira_backup gets SELECT through the default privileges in infra/postgres/backup-grants.sql.
  Check this, and do not add grants by hand.
- Seed templates for: the generic civil-unrest shelter-in-place advisory (with {city}),
  the Nairobi advisory (today's PB-07 text, unchanged) and a Paris advisory.
  EN plus AR/FR/SW, all marked "not reviewed" (D-15).

Tests (real PostgreSQL, as nexira_api): tenant isolation on message_template; the trigger
refuses self-approval; test_backup_role still passes; the migration round-trips.
```

### Prompt 19 · Per-mission templates in PB-07 and the Communications agent
```
MN-03, MN-04.
- A template service: resolve(kind, mission_id) returns the mission's template, otherwise the
  generic one, with {city} filled in.
- PB-07 step 4 references a template code instead of carrying advisory text in its config.
  Update the seed: the Nairobi template keeps today's text exactly.
- The Communications agent builds its SEND_EXTERNAL_MESSAGE proposal from the resolved
  template. Its policy (level 2, DUTY_OFFICER|CONSULAR_OFFICER) and EDITABLE_FIELD do not change.

Tests: the Nairobi acceptance scenario is unchanged (make acceptance); the France scenario's
advisory contains no "Nairobi", "CBD" or "Upper Hill"; the generic fallback fills in {city}.
```

### Prompt 20 · Composer backend: draft, approve, send 🔒
```
MN-01, MN-02, MN-05 to MN-08, MN-12 (MN-11 deferred, plan G-1). 🔒 because it adds the
second-person approval for external messages. The channel adapters are not changed.
- POST /api/campaigns (create a DRAFT); PATCH /api/campaigns/{id} (edit a DRAFT);
  POST /api/campaigns/{id}/preview (recipient count and split by person type);
  /submit, /approve, /reject (with a reason), /cancel and /test-send.
- Audiences: missions[], person_types[], exposed_to_incident. Reuse resolve_audience,
  extended for "no incident".
- The second-person rule (D-31) goes through approvals.decide with a Gate. Do not write a new
  role check. Staff-only campaigns are sent by the author.
- In APP_ENV=pilot, refuse to send with an unreviewed translation (409, naming the language).
- Sending queues deliveries exactly as playbook campaigns do (outbox, idempotency); there is no
  second sending path.
- Every action is audited through app/core/audit.py.
- No endpoint may write created_by, created_by_type or submitted_by from the request
  (review of Prompt 18): set them in the service only, and test that a PATCH with those
  fields changes nothing. Approve only from PENDING_APPROVAL, with the row locked, and
  set status SENDING in the same UPDATE as approved_by. PATCH only DRAFT campaigns: the
  content is frozen once submitted. The status only moves forward, and a pending campaign
  reaches SENDING only together with its approval. The database refuses anything else
  (PC-10, PC-11, PC-12).

Tests: author approval → 403; a Viewer → 403; a second Duty Officer → deliveries queued; a
staff-only campaign is sent by its author; cancel and test-send queue nothing; pilot mode
blocks unreviewed translations.
```

### Prompt 21 · Mass Notification screen
```
MN-01 to MN-10 in the UI (Blueprint dark; visual reference only: the demo's Mass Notification
composer).
- Composer: kind, template picker, message, channels, audience builder with a live recipient
  count, and the phone preview panel for test-send.
- Campaign history with filters; the campaign detail page has a delivery funnel per channel
  that updates live (WebSocket CAMPAIGN_UPDATED).
- Approve and reject are shown only to users who can do them. Use GET /api/me/permissions,
  extended for campaigns (plan G-07).
- Add the screen to the navigation under RESPOND.

Tests: Vitest for the composer, the funnel and the permission-driven buttons.
```

### Prompt 22 · Mass Notification acceptance
```
Playwright, real stack, as in Prompt 15 (requirements-pilot.md §6):
- A Duty Officer composes an advisory to the Paris citizens from a template, test-sends it,
  and submits it.
- Self-approval is refused, and a second Duty Officer approves.
- The funnel reaches read for every recipient, and GET /api/audit/verify is intact.
- make acceptance (Nairobi) still passes, and the France scenario's advisory names Paris.
Report the real output.
```

---

## Pilot module 2 · Journey Management (approved 2026-10-26, PR #24)

Sources: D-32, `docs/requirements-pilot.md` §9–13 (JR-01..09), PC-14..16.

### Prompt 23 · Read and plan (no code)
```
Read D-08, D-22, D-29, D-30, D-32, requirements-pilot.md §9-13, the travel and intel
modules and the Mass Notification composer (the pattern to follow). Write
docs/plan-pilot-jrn.md: requirement-to-code mapping, the API (paths, roles), gaps with
proposed answers, and the migration for PC-14..16 (only after they are approved).
No code changes.
```

### Prompt 24 · Trip itinerary, approval and country risk (migration) 🔒
```
PC-14, PC-15 and PC-16 were approved on 2026-10-26 (PR #24). A new migration (never edit 0001/0002):
trip_segment and country_risk with FORCE RLS and tenant_isolation; the trip columns and
statuses; the guard triggers on trip, trip_traveller and trip_segment; REVOKE DELETE as
PC-15 says. Seed country_risk (simulated) and a handful of trips: TRP-8812 unchanged
(the Nairobi acceptance depends on it), plus draft, pending and approved trips elsewhere.
Tests (as nexira_api): isolation on the new tables; every guard refusal (self-approval,
approval from DRAFT, edits after submission, backward status); backup role can read the
new tables; the 0003 downgrade restores 0002 exactly.
```

### Prompt 25 · Trips backend 🔒
```
JR-01..07, JR-09. 🔒 because it adds an approval path (D-29: approvals).
- /api/trips: create and edit a DRAFT (TRAVEL_DESK, DUTY_OFFICER), travellers and segments,
  checklist ticks, submit, approve, reject (reason), cancel; GET with filters and an
  "impacted by" field from incident_exposure; GET /api/me/permissions for trips.
- Destination risk at submission (D-32, PC-16 + ACTIVE incidents in the country); the
  approver follows the risk; the gate goes through approvals.decide with the requester as
  a decider of the first step. LOW is approved on submission. HIGH/CRITICAL need the four
  checklist items. "Risk now X" when the live risk exceeds approved_risk_level.
- Author fields never from a request (extra="forbid"); everything audited.
Tests: every role and scope refusal; the checklist block; LOW auto-approval; risk from an
incident; impacted flag in the Nairobi scenario; the database backstop for each rule.
```

### Prompt 26 · Journey Management screen
```
JR-08 (visual reference: the demo's Journey Management screen). Trips table with filters
and an "Impacted" status; detail with itinerary timeline, travellers, checklist (tick
boxes for those allowed), destination risk breakdown (labelled simulated), approve /
reject / cancel from permissions; KPIs from data. Navigation under MONITOR.
Tests: Vitest for the table, the checklist, the permission-driven buttons.
```

### Prompt 27 · Journey Management acceptance
```
Playwright, real stack (requirements-pilot.md §12): plan a Paris trip during the France
scenario (HIGH), refusals for the requester and the Travel Desk, the checklist block,
approval by the Security Officer, TRP-8812 impacted in the Nairobi scenario, audit verifies;
make acceptance still passes. Report the real output.
```

---

## Later pilot modules
## Pilot module 3 · Air Travel Tracking (approved 2026-10-27, PR #30)

Sources: D-33, `docs/requirements-pilot.md` §14–18 (AT-01..08), PC-17..19. Simulated flights only.

### Prompt 28 · Read and plan (no code)
```
Read D-19, D-22, D-24, D-29, D-30, D-32, D-33, requirements-pilot.md §14-18, the travel,
people/location, intel/exposure and scenarios modules and the worker. Write
docs/plan-pilot-air.md: requirement-to-code mapping, the tracker's loop (how flights are
created, moved, disrupted and landed; how scenario events reach it; time compression),
the API (paths, roles), how AT-05 (restricted trips) is enforced at every layer, gaps with
proposed answers, and the migration for PC-17..19 (only after they are approved).
No code changes.
```

### Prompt 29 · Airports, flights and restricted trips (migration) 🔒
```
PC-17..19, once approved. A new migration (never edit 0001-0003): airport, flight and
flight_event with FORCE RLS and tenant_isolation; grants as PC-19 (the tracker also runs
as nexira_api, so guard triggers keep flight_event append-only and flight status forward-
only); the trip_segment flight columns
(frozen with the segment); trip.restricted (frozen once the trip leaves DRAFT, in the
PC-15 guard); a database backstop that refuses a flight for a restricted or unapproved
trip. Seed airports (simulated) and the Nairobi scenario's approved trip with XW 451 AUH
-> NBO for 3 HQ staff, plus one restricted trip with a flight.
Tests (as nexira_api): isolation; every guard refusal; backup role reads the new tables;
the downgrade restores 0003 exactly.
```

### Prompt 30 · Flight tracker and flights API
```
AT-01, AT-03, AT-04, AT-06, AT-08. The tracker in the worker (simulated feed): ensures a
flight for each FLIGHT segment of an APPROVED, not restricted trip from 24 h before
departure; moves it along a great-circle route on the clock; applies scenario events
(DELAYED >= 30 min, HOLDING, DIVERTED, CANCELLED) as flight events; on LANDED adds a
FLIGHT location observation per traveller at the landing airport (people/location), then
recompute and exposure as today; stops tracking when the trip is cancelled. Publishes
FLIGHT_UPDATED. Audits creation and each status change (actor SYSTEM).
GET /api/flights (filters: status, disrupted) and /api/flights/{id} with events, travellers
and trip; the trip API gains each flight segment's live status. Nairobi scenario: XW 451
holds when the airport roads are affected, then diverts to Mombasa and lands (the Phase 1
acceptance must still pass unchanged).
Tests: restricted and unapproved trips never produce a flight or appear anywhere; every
transition; landing moves the travellers; time compression; isolation of the API.
Ask for an independent review: AT-05 is a safety rule even though it is not a D-29 path.
```

### Prompt 31 · Air Travel screen, and flight fields in the planner
```
AT-02, AT-07 (visual reference: the demo's Air Travel Tracking screen). Under MONITOR:
KPIs from data (officials airborne, disrupted flights, position source "simulated");
air picture on the self-hosted map (D-24) with routes and positions; tracked-flight table;
detail with travellers, trip link and the event timeline; banners for HOLDING and DIVERTED;
live over FLIGHT_UPDATED; a "Safeguards" card stating AT-01 and AT-05. The Journey planner
gains flight number and airports for FLIGHT segments and a "Restricted (VIP/ministerial)"
switch; the trip detail shows each flight's live status.
Tests: Vitest for the table, the banners, the planner fields and the restricted switch.
```

### Prompt 32 · Air Travel acceptance
```
Playwright, real stack (requirements-pilot.md §17): XW 451 on the air picture; HOLDING,
then DIVERTED · Mombasa, then LANDED, live; the 3 travellers' location becomes Mombasa
(source FLIGHT); the restricted trip's flight never appears (API and UI); audit verifies;
make acceptance (Nairobi, Mass Notification, Journey) still passes. Report the real output.
```

---

## Pilot module 4 · Travel & Air agent (approved 2026-10-27, PR #36)

Sources: D-12 to D-17, D-34, `docs/requirements-pilot.md` §19–23 (TA-01..09).

### Prompt 33 · Read and plan (no code)
```
Read D-12..D-17, D-29, D-31..D-34, requirements-pilot.md §19-23, app/modules/agents (runner,
proposals, actions, the Phase 1 agents), notifications/service.py (audiences), travel
(trips, tracker). Write docs/plan-pilot-ta.md: triggers and the events they come from,
proposal keys and evidence, the two executors and the service functions they call (an
agent path for cancelling a trip), the "trip travellers" audience, approval scope (an
incident's mission, else HQ only, D-06), the seed (agent, policies, a Paris trip for the
acceptance), and gaps with proposed answers. Confirm no schema change is needed, or
propose one. No code changes.
```

### Prompt 34 · Travel actions, policies and the trip audience 🔒
```
TA-05, TA-06 (D-29: executors and policies). NOTIFY_TRAVELLERS and CANCEL_TRIP payload
schemas and executors in agents/actions.py, calling only the notification service (new
audience {"trip_id"}: that trip's travellers; citizens refused, D-31) and the trips
service (cancel by the agent, approver recorded, audited). ADVISE_REBOOKING has no
executor and no policy (level 4). Seed the TRAVEL_AIR agent (level 2, no observe logic
yet) and the policies (deadline 60 min).
Tests: each executor through the approval flow as a user would; the audience refuses a
citizen; level 4 never executes; policies fail closed; a restricted trip cannot be
cancelled or notified through these actions.
```

### Prompt 35 · Travel & Air agent: what it watches
```
TA-01..04, TA-07, TA-08. The agent observes FLIGHT_UPDATED, EXPOSURE_COMPUTED and
incident events; proposes NOTIFY_TRAVELLERS, ADVISE_REBOOKING and CANCEL_TRIP (with the
notify alternative) as §20 says; never for restricted trips; one proposal per trip or
flight and cause; evidence from flight events, the incident and the risk breakdown. The
scenarios: NBO-AIR-DIVERSION (holding, diversion), NBO-CIVIL-UNREST (TRP-8812 impacted;
the Phase 1 counts and proposals must not change — check), FRA-NATIONAL-PROTESTS (a
seeded approved Paris trip).
Tests: each trigger, idempotency, restricted trips, the kill switch.
```

### Prompt 36 · Decision Queue and AI Agents for travel
```
TA-09. Decision Queue cards for travel proposals: the trip and flight with links to
Journey and Air, the advice card for ADVISE_REBOOKING (dismiss only), the alternative on
CANCEL_TRIP. AI Agents lists Travel & Air with its policies. Journey and Air show a
trip's or flight's pending proposals.
Tests: Vitest for the cards and links.
```

### Prompt 37 · Travel & Air agent acceptance
```
Playwright, real stack (requirements-pilot.md §22). Report the real output; make
acceptance (all specs) still passes.
```

---

## Pilot module 6 · Weather (approved 2026-10-30, PR #43)

Sources: D-35, `docs/requirements-pilot.md` §24–28 (WX-01..08), PC-20. Simulated weather only.

### Prompt 38 · Read and plan (no code)
```
Read D-09..D-11, D-19, D-22, D-30, D-32, D-34, D-35, requirements-pilot.md §24-28, the intel
pipeline (normalise, fusion, exposure), the Response Planner, playbooks and templates,
the flight tracker (the pattern for a simulated feed). Write docs/plan-pilot-wx.md:
requirement-to-code mapping, the simulated feed and how scenarios override it, how
category-sized radii fit fusion and exposure without changing unrest (D-23 must not
move), PB-06's steps and trigger, the MNL-TROPICAL-STORM scenario, gaps with proposed
answers, and the migration for PC-20 (only after it is approved). No code changes.
```

### Prompt 39 · Current weather table (migration) 🔒
```
PC-20, once approved. A new migration: weather_current with FORCE RLS and
tenant_isolation, grants as PC-20, range CHECKs. Seed nothing (the feed fills it).
Tests (as nexira_api): isolation; refusals; backup role reads it; the downgrade
restores the previous revision exactly.
```

### Prompt 40 · Weather feed, warnings and PB-06
```
WX-01, WX-03..06, WX-08. The simulated feed in the worker (every 15 min, a daily cycle
per city; WEATHER_FEED events from scenarios override a city), GET /api/weather,
WEATHER_UPDATED to browsers. xWeather categories (§28 Q3) and category-sized radii
(Q4) in normalisation, fusion and exposure. PB-06 (severe weather) and a per-mission
severe-weather advisory template; the Response Planner's rule for it. The
MNL-TROPICAL-STORM scenario and a seeded staff trip to Manila.
Tests: the feed and overrides; radii per category; unrest unchanged (the Phase 1
acceptance and D-23 counts); PB-06 proposed for STORM/FLOOD HIGH+ near a mission only.
```

### Prompt 41 · Weather on the screens
```
WX-02, WX-07. Global Operations weather panel (worst first, stale flagged), map weather
layer and mission popup, the presenter bar entry for MNL-TROPICAL-STORM.
Tests: Vitest for the panel, stale flag and layer data.
```

### Prompt 42 · Weather acceptance
```
Playwright, real stack (requirements-pilot.md §27). Report the real output; make
acceptance (all specs) still passes.
```

---

## Pilot module 5 · Assistance Partners (approved 2026-10-30, PR #49)

Sources: D-36, `docs/requirements-pilot.md` §29–33 (AS-01..08), PC-21, PC-22. Simulated partners only.

### Prompt 43 · Read and plan (no code)
```
Read D-05, D-14, D-16, D-19, D-22, D-29, D-30, D-33, D-36, requirements-pilot.md §29-33,
the playbook engine (PARTNER_REQUEST), Safety Check-in (NEED_HELP), the location engine,
the channel adapters (the pattern for a simulated external system) and the flight
tracker. Write docs/plan-pilot-ast.md: requirement-to-code mapping, the simulated partner
adapter and its timing, how PB-07 step 6 creates a request without moving the Phase 1
figures (D-23), the SOS suggestion rule, coverage gaps, the seed partners, gaps with
proposed answers, and the migration for PC-21/22 (only after they are approved). No code.
```

### Prompt 44 · Partner tables (migration) 🔒
```
PC-21 and PC-22, once approved. A new migration: partner and partner_request with FORCE
RLS and tenant_isolation, grants as proposed, the REQ reference series, the guard
trigger. Tests (as nexira_api): isolation; every refusal of the guard; no DELETE; the
backup role reads them; the downgrade restores the previous revision exactly.
```

### Prompt 45 · Requests, the simulated partner and PB-07 🔒
```
AS-02..06, AS-08. app/modules/partners: service (request, cancel, complete; role checks
through app/core/approvals.py), the simulated partner adapter in the worker (accept,
ETA, en route; declines per §33 Q4), PARTNER_REQUESTED/PARTNER_REQUEST_UPDATED events to
browsers, the SOS suggestion, coverage. PB-07 step 6 creates the Kestrel standby
request. Seed the five partners. 🔒: the adapter is an external-system boundary (D-29).
Tests: the status table, roles, refusals (service, coverage, restricted traveller),
the adapter's timing with a fake clock, PB-07 unchanged in the D-23 figures.
```

### Prompt 46 · Assistance Partners screen
```
AS-01, AS-03, AS-06, AS-07. The screen (as the design, Blueprint dark): partner network,
requests with status and ETA (live), coverage KPI and gaps, the SOS banner with the
suggested partner; "Request partner" on Safety Check-in next to a NEED_HELP; the
navigation entry. Tests: Vitest for the list, the request form, the status updates and
the suggestion.
```

### Prompt 47 · Assistance Partners acceptance
```
Playwright, real stack (requirements-pilot.md §32). Report the real output; make
acceptance (all specs) still passes.
```

---

## Pilot module 7 · Document Expiry (approved 2026-10-30, PR #57)

Sources: D-37, `docs/requirements-pilot.md` §34–38 (DX-01..09), PC-23. Simulated documents only; no document numbers.

### Prompt 48 · Read and plan (no code)
```
Read D-05, D-08, D-12..D-17, D-19, D-29, D-30, D-31, D-37, requirements-pilot.md §34-38,
the person and mission model, Mass Notification (audience_filter, staff campaigns), the
Travel & Air agent (the pattern for a rule-based agent with its own action type and
audience), and Journey Management's checklist. Write docs/plan-pilot-dx.md:
requirement-to-code mapping, urgency and travel-readiness rules, the Compliance agent's
trigger and its one-open-proposal-per-mission rule, the seed (§38 Q1), gaps with proposed
answers, and the migration for PC-23 (only after it is approved). No code.
```

### Prompt 49 · Document table (migration) 🔒
```
PC-23, once approved. A new migration: travel_document with FORCE RLS and
tenant_isolation, the grants as proposed, the guard trigger with a pinned search_path.
Tests (as nexira_api): isolation; every refusal of the guard; no DELETE; column grants;
the backup role reads it; the downgrade restores the previous revision exactly.
```

### Prompt 50 · Register, renewals, reminders and the Compliance agent 🔒
```
DX-01..07, DX-09. app/modules/documents: service (list with urgency and readiness,
renewal steps, reminders through the notification service with a "document holders"
audience; role checks through app/core/approvals.py), router, DOCUMENT_UPDATED events to
browsers. The Compliance agent and its policy (START_DOCUMENT_RENEWAL, level 2, floor 2;
executor calls the same services). The trip warning (DX-06). Seed the documents (§38 Q1).
🔒: agent policy and executor (D-29).
Tests: urgency and readiness at the boundaries (29/30, 89/90, 179/180 days), roles and
mission scope, the forward-only renewal, reminders never to citizens, the agent's trigger,
one open proposal per mission, the executor writing the same rows and audit as a person.
```

### Prompt 51 · Document Expiry screen
```
DX-02, DX-03, DX-08, DX-09. The screen (as the design, Blueprint dark): KPIs, expiring
documents with urgency, impact and renewal, filters, "Send renewal reminders" and renewal
actions from /api/me/permissions; KPIs only for a Viewer; the trip warning on Journey
Management; the navigation entry; rows flash on change (ui/motion). Tests: Vitest for
the list, filters, actions by role and the Viewer view.
```

### Prompt 52 · Document Expiry acceptance
```
Playwright, real stack (requirements-pilot.md §37). Report the real output; make
acceptance (all specs) still passes.
```

## Pilot module 8 · Natural Hazards & Climate (Prompts 53–58)

Sources: D-38, `docs/requirements-pilot.md` §39–43 (HZ-01..11), PC-24, PC-25. Simulated hazard feeds and illustrative climate scores only.

### Prompt 53 · Read and plan (no code)
```
Read D-05, D-12..D-17, D-19, D-29, D-30, D-35, D-38, requirements-pilot.md §24-28 and
§39-43, Weather (feed, categories, sizing in intel/fusion.py, PB-06), the playbook engine
and run statuses, and the Response Planner. Write docs/plan-pilot-hz.md: requirement-to-code
mapping, severity and radius rules per hazard (§43 Q3), where hazard details live (the
latest signal payload), the scheduled-run design (who starts it, at what time, restarts
and missed times), the arming proposal and its one-open-proposal-per-incident rule, PB-01,
the DAC-CYCLONE scenes, gaps with proposed answers, and the migration for PC-24 and PC-25
(only after they are approved). No code.
```

### Prompt 54 · Armed runs and climate table (migration) 🔒
```
PC-24 and PC-25, once approved. A new migration: playbook_run scheduled_for and the
SCHEDULED/DISARMED statuses with their guard; mission_climate_risk with FORCE RLS,
tenant_isolation and the grants as proposed; pinned search_path. Tests (as nexira_api):
isolation; every refusal of the guards; no UPDATE/DELETE on the climate table; the backup
role reads it; the downgrade restores the previous revision exactly.
```

### Prompt 55 · Hazard events, arming and PB-01 🔒
```
HZ-01..07, HZ-10. The new categories with their severity and radius rules; hazard details
from the signal payload; nearest mission and distance; arm, start-now and disarm through
the playbook service (roles through app/core/approvals.py, audited); the worker starts
SCHEDULED runs when due; the ARM_PLAYBOOK action, its executor and policy (floor 2,
SECURITY_OFFICER|DUTY_OFFICER); the Response Planner's arming proposal and PB-01 proposal;
GET /api/hazards and /api/me/permissions for arming. Tests against real PostgreSQL.
```

### Prompt 56 · Simulated feeds, climate seed and DAC-CYCLONE
```
HZ-08, HZ-11. Simulated seismic, air-quality and xWeather hazard signals; the illustrative
climate scores for all 36 missions (§43 Q7); PB-01 in the seed; the DAC-CYCLONE scenario
(§43 Q8) with Dhaka homes in flood-prone wards; the presenter bar entry. The Phase 1 scenario
still starts with no active incident. Tests in the simulator.
```

### Prompt 57 · Natural Hazards & Climate screen
```
HZ-03, HZ-04, HZ-09, HZ-10. The screen (as the design, Blueprint dark): KPIs, live events
with type tabs and mission exposure, the countdown, the arming banner and its actions from
/api/me/permissions, the climate table; hazard icons on the Global Operations map; the nav
entry under MONITOR; rows flash on change (ui/motion). Tests: Vitest for the list, tabs,
the countdown, arming by role and the Viewer view.
```

### Prompt 58 · Natural Hazards acceptance
```
Playwright, real stack (requirements-pilot.md §42). Report the real output; make
acceptance (all specs) still passes.
```

## Pilot module 9 · Health Intelligence (approved 2026-10-31, PR #70)

Sources: D-39, `docs/requirements-pilot.md` §44–48 (HL-01..10), PC-26..29. Simulated advisories, sample facilities and illustrative requirements only.

### Prompt 59 · Read and plan (no code)
```
Read D-05, D-12..D-17, D-19, D-29, D-30, D-31, D-36, D-39, requirements-pilot.md §1-6 and
§44-48, Mass Notification (campaigns, templates, second person), the Communications agent,
exposure and incidents, and Journey Management's trip detail. Write docs/plan-pilot-hl.md:
requirement-to-code mapping, the advisory feed and its updates, the "affects a mission"
rule, the Avoid flag query, readiness counts, the send flow and the agent proposal with its
one-open-proposal rule, the NBO-CHOLERA scenes, gaps with proposed answers, and the
migration for PC-26..29 (only after they are approved). No code.
```

### Prompt 60 · Health tables (migration) 🔒
```
PC-26..29, once approved. A new migration: health_advisory, medical_facility,
country_health_requirement and mission_health_readiness with FORCE RLS, tenant_isolation
and the grants as proposed; the advisory guard (closed is final; content frozen except
level, guidance, status, updated_at); readiness CHECKs; pinned search_path. Tests (as
nexira_api): isolation; every refusal; no DELETE; the backup role reads them; the
downgrade restores the previous revision exactly.
```

### Prompt 61 · Advisories, facilities, readiness and the health proposal 🔒
```
HL-01..07, HL-09. Advisory ingest and update (audited); affected missions; facilities by
distance with the Avoid flag from ACTIVE incidents (PostGIS); readiness counts; entry
requirements, also on the trip detail; "send health advisory" creating a Mass Notification
draft from the HEALTH_ADVISORY template (roles through app/core/approvals.py); the
Communications agent's health proposal and its policy (floor 2, DUTY_OFFICER|
CONSULAR_OFFICER); GET /api/health/* and /api/me/permissions. Tests against real PostgreSQL.
```

### Prompt 62 · Simulated feed, seed and NBO-CHOLERA
```
HL-01, HL-10. The simulated advisory feed; the six advisories, entry requirements for the
36 mission countries, sample facilities and readiness counts in the seed; the
HEALTH_ADVISORY templates; the NBO-CHOLERA scenario and its presenter bar entry. The Phase 1
scenario still starts with no active incident and an empty Decision Queue. Tests in the
simulator.
```

### Prompt 63 · Health Intelligence screen
```
HL-08, HL-09. The screen (as the design, Blueprint dark): the simulated-sources banner,
KPIs, the advisories table with affected missions, entry requirements, facilities with the
Avoid flag and readiness for a chosen mission, the send button from /api/me/permissions;
the nav entry under MONITOR; rows flash on change (ui/motion); realtime refresh. Tests:
Vitest for the list, the mission choice, the Avoid flag, sending by role and the Viewer view.
```

### Prompt 64 · Health Intelligence acceptance
```
Playwright, real stack (requirements-pilot.md §47). Report the real output; make
acceptance (all specs) still passes.
```

## Pilot module 10 · Evacuation Management (approved 2026-11-01, PR #77)

Sources: D-40, `docs/requirements-pilot.md` §49–53 (EV-01..10), PC-30..32. Simulated plans, scanner and partners only.

### Prompt 65 · Read and plan (no code)
```
Read D-05, D-06, D-12..D-17, D-19, D-29, D-30, D-31, D-36, D-37, D-40, decisions.md §7,
requirements-pilot.md §1-6 and §49-53, the START_EVACUATION action and its Phase 1 stub,
approvals.py, check-in, Assistance Partners requests, Document Expiry's evacuation flag and
Mass Notification. Write docs/plan-pilot-ev.md: requirement-to-code mapping, the two ways to
activate and how both stay two-person, building the manifest, check-in and seats, the
sequence and the partner requests it follows, the movement message and its second person,
stand-down, who sees names, the NBO-EVACUATION scenes, what changes in the Phase 1 and pilot
acceptance specs, gaps with proposed answers, and the migration for PC-30..32 (only after
they are approved). No code.
```

### Prompt 66 · Evacuation tables (migration) 🔒
```
PC-30..32, once approved. A new migration: evacuation_plan, evacuation and
evacuation_manifest with FORCE RLS, tenant_isolation and the grants as proposed; the guards
(forward-only status and step, final states, activator ≠ requester, one live evacuation per
mission, manifest inserted only at activation, check-in final); pinned search_path. Tests
(as nexira_api): isolation; every refusal; no DELETE; the backup role reads them; the
downgrade restores the previous revision exactly.
```

### Prompt 67 · Activation, manifest, check-in and sequence 🔒
```
EV-02..07, EV-09. Activation through app/core/approvals.py, from the screen (request and
confirm) and from START_EVACUATION's executor (replacing the Phase 1 stub, still writing the
note); the manifest at activation; check-in by hand and by the simulated scanner, with
seats; the sequence following the partner requests or a person; the partner requests and
the movement-message campaign at activation (PENDING_APPROVAL, neither activator may send
it); stand-down; names by people scope; GET /api/evacuations/* and /api/me/permissions.
Every step audited. Tests against real PostgreSQL; Phase 1 scene 5 still passes.
```

### Prompt 68 · Plans, scanner, seed and NBO-EVACUATION
```
EV-01, EV-10. Plans for every mission in the seed (EVP-NBO as the design); the EVACUATION
templates; the simulated muster-point scanner in the worker; the NBO-EVACUATION scenario
and its presenter bar entry. The Phase 1 scenario still starts with no active incident and
an empty Decision Queue. Tests in the simulator.
```

### Prompt 69 · Evacuation Management screen
```
EV-08, EV-09. The screen (as the design, Blueprint dark): the banner with Activate when
allowed, KPIs, the manifest with document flags, seats and status, the sequence with times,
the options; the mission picker; every button from /api/me/permissions; the nav entry under
RESPOND; rows flash on change; realtime refresh. Tests: Vitest for the manifest, activation
by role, check-in, the sequence, stand-down and the Viewer view.
```

### Prompt 70 · Evacuation Management acceptance
```
Playwright, real stack (requirements-pilot.md §52). Report the real output; make
acceptance (all specs) still passes.
```

## Pilot module 11 · Fleet & Assets (approved 2026-11-01, PR #84)

Sources: D-41, `docs/requirements-pilot.md` §54–58 (FLT-01..08), PC-33..34. Simulated assets and telematics only.

### Prompt 71 · Read and plan (no code)
```
Read D-05, D-12, D-19, D-29, D-30, D-36, D-40, D-41, requirements-pilot.md §1-6 and §54-58,
the check-in, incidents and impact zones (HL-04's Avoid), evacuations and the manifest,
Assistance Partners coverage and approvals.py. Write docs/plan-pilot-flt.md:
requirement-to-code mapping, the derived states and how they clear, capacity, maintenance,
telematics events and the geofence alert with its timeline entry, who sees driver names, the
NBO-FLEET scenes, what changes in the acceptance specs, gaps with proposed answers, and the
migration for PC-33..34 (only after they are approved). No code.
```

### Prompt 72 · Fleet tables (migration) 🔒
```
PC-33..34, once approved. A new migration: fleet_asset and fleet_maintenance with FORCE RLS,
tenant_isolation and the grants as proposed; the guards (frozen columns, the MAINTENANCE
reason, done once); pinned search_path. Tests (as nexira_api): isolation; every refusal; no
DELETE; the backup role reads them; the downgrade restores the previous revision exactly.
```

### Prompt 73 · Register, states, capacity and maintenance 🔒
```
FLT-01..05, FLT-07. The service: derived states (blocked, in zone, assigned), capacity with
the partner suggestion, maintenance alerts; status and maintenance actions through
app/core/approvals.py; telematics positions from the worker with the geofence alert and
the FLEET timeline entry; driver names by people scope; GET /api/fleet/* and
/api/me/permissions. Every change audited. Tests against real PostgreSQL.
```

### Prompt 74 · Seed, telematics and NBO-FLEET
```
FLT-01, FLT-08. The register and maintenance items for every mission in the seed (Nairobi as
the design); the VEHICLE_POSITION and workshop events in the worker; the NBO-FLEET scenario
and its presenter bar entry. The Phase 1 scenario still starts with no active incident and
an empty Decision Queue. Tests in the simulator.
```

### Prompt 75 · Fleet & Assets screen
```
FLT-06, FLT-07. The screen (as the design, Blueprint dark): KPIs, the assets table with
fuel bars and statuses, the capacity card, the maintenance alerts, the geofence alert; the
mission filter; every button from /api/me/permissions; the nav entry under RESPOND after
Evacuation Management; rows flash on change; realtime refresh. Tests: Vitest for statuses,
capacity, maintenance, the alert and the Viewer view.
```

### Prompt 76 · Fleet & Assets acceptance
```
Playwright, real stack (requirements-pilot.md §57). Report the real output; make
acceptance (all specs) still passes.
```

## Pilot module 12 · VIP & Delegation Protection (approved 2026-11-01, PR #91)

Sources: D-42, `docs/requirements-pilot.md` §59–63 (VIP-01..08), PC-35..38. Simulated visits only; never a position.

### Prompt 77 · Read and plan (no code)
```
Read D-05, D-12, D-16, D-19, D-29, D-30, D-33, D-36, D-41, D-42, requirements-pilot.md §1-6
and §59-63, restricted trips, incidents and impact zones, weather warnings, country risk,
Fleet, medical facilities and approvals.py. Write docs/plan-pilot-vip.md: requirement-to-code
mapping, who sees a visit and how it stays invisible to everyone else (API, screen, map,
events, audit), the risk rules, the detail and safe havens, the checklist, live status
without positions, two-person changes, the ADD-VISIT scenes, what changes in the acceptance
specs, gaps with proposed answers, and the migration for PC-35..38 (only after approval).
No code.
```

### Prompt 78 · VIP tables (migration) 🔒
```
PC-35..38, once approved. A new migration: vip_visit, vip_segment, vip_checklist_item and
vip_segment_change with FORCE RLS, tenant_isolation and the grants as proposed; the guards
(forward-only status, final states, the restricted trip, segment times only through an
approved change, decided once by another person, done once); pinned search_path. Tests (as
nexira_api): isolation; every refusal; no DELETE; the backup role reads them; the downgrade
restores the previous revision exactly.
```

### Prompt 79 · Visits, risk, checklist and changes 🔒
```
VIP-01..06. The service: visibility (only the protection roles and the host Head of Mission;
404 for everyone else); segment risk from incidents, weather and attendees with reasons and
the recommendation; the detail from Fleet, Health and Partners; checklist ticks; start,
progress and cancel; two-person changes through app/core/approvals.py; GET /api/vip/* and
/api/me/permissions; realtime with ids only; audit without venues or times. Tests against
real PostgreSQL, including that no other role learns a visit exists.
```

### Prompt 80 · Seed and ADD-VISIT
```
VIP-01, VIP-08. VV-2026-031 with its six segments, detail and checklist, linked to a new
restricted TRP-8834; the VIP_PROGRESS events in the worker; the rally signal near the
industrial park; the ADD-VISIT scenario and its presenter bar entry. The Phase 1 scenario
still starts with no active incident and an empty Decision Queue. Tests in the simulator.
```

### Prompt 81 · VIP Protection screen
```
VIP-07. The screen (as the design, Blueprint dark): the banner with Start visit, KPIs, the
programme with risk, reasons and Propose change, the change decision, the protection detail,
the checklist; the nav entry under RESPOND after Fleet & Assets, shown only to roles that may
see visits; every button from /api/me/permissions; realtime refresh. Tests: Vitest for risk,
the change flow, the checklist, live status and the restricted view.
```

### Prompt 82 · VIP Protection acceptance
```
Playwright, real stack (requirements-pilot.md §62). Report the real output; make
acceptance (all specs) still passes.
```

## Pilot module 13 · Site Twin (approved 2026-11-02, PR #98)

Sources: D-43, `docs/requirements-pilot.md` §64–68 (TWN-01..07), PC-39..42. Simulated building systems only; presence never feeds location confidence.

### Prompt 83 · Read and plan (no code)
```
Read D-05, D-16, D-19, D-29, D-30, D-40, D-41, D-43, requirements-pilot.md §1-6 and §64-68,
sites and people, location confidence, Fleet equipment, PB-07 step 4, evacuations and
approvals.py. Write docs/plan-pilot-twn.md: requirement-to-code mapping, the seeded floor plan,
presence and who sees names, sensors and the Fleet link, the derived shelter and route
overlays, readiness, the SITE timeline entries, the NBO-SITE scenes, what changes in the
acceptance specs, gaps with proposed answers, and the migration for PC-39..42 (only after
approval). No code.
```

### Prompt 84 · Site Twin tables (migration) 🔒
```
PC-39..42, once approved. A new migration: site_zone, site_route, site_presence, site_sensor,
site_readiness and site_readiness_item with FORCE RLS, tenant_isolation and the grants as
proposed; the guards (same-tenant and same-site references, frozen columns, times written by
the database, done once); pinned search_path. Tests (as nexira_api): isolation; every
refusal; the backup role reads them; the downgrade restores the previous revision exactly.
```

### Prompt 85 · Plan, presence, sensors, overlays and readiness 🔒
```
TWN-01..05. The service: the plan; presence with names only within the people scope; sensors
with the generator and satellite comms from Fleet; shelter-in-place and the route worked out
on read; readiness with the derived access item; the readiness tick through
app/core/approvals.py; SITE timeline entries for faults in an ACTIVE zone; GET /api/sites/*
and /api/me/permissions; SITE_UPDATED with ids and counts only; audit. Tests against real
PostgreSQL, including that People & Sites figures do not change.
```

### Prompt 86 · Seed, simulated feeds and NBO-SITE
```
TWN-01, TWN-07. The Nairobi embassy's plan, routes, sensors, readiness and presence (the 11
staff at "Embassy", 3 guards, 11 visitors); SITE_PRESENCE and SITE_SENSOR in the worker; the
NBO-SITE scenario and its presenter bar entry. The Phase 1 scenario still starts with no
active incident and an empty Decision Queue. Tests in the simulator.
```

### Prompt 87 · Site Twin screen
```
TWN-06. The screen (as the design, Blueprint dark): site picker, KPIs, the SVG floor plan
with counts, dots and overlays, sensors & systems, occupancy by zone, emergency readiness;
the nav entry under RESPOND after Assistance Partners; every button from
/api/me/permissions; realtime refresh. Tests: Vitest for the plan, names by scope, overlays,
sensors and readiness.
```

### Prompt 88 · Site Twin acceptance
```
Playwright, real stack (requirements-pilot.md §67). Report the real output; make
acceptance (all specs) still passes.
```

## Pilot module 14 · Supply Chain & Third-Party Risk (approved 2026-11-02, PR #112)

Sources: D-44, `docs/requirements-pilot.md` §69–73 (SUP-01..07), PC-43..45. Simulated suppliers and routes only; NEXIRA contacts no supplier.

### Prompt 89 · Read and plan (no code)
```
Read D-05, D-16, D-19, D-29, D-30, D-41, D-44, requirements-pilot.md §1-6 and §69-73,
missions, incidents and impact zones, Fleet equipment (GEN-<mission>), the incident timeline
and approvals.py. Write docs/plan-pilot-sup.md: requirement-to-code mapping, the seeded
register and routes (Nairobi as the design), reported and shown statuses, the incident link
and SUPPLY timeline entries, the fuel stock from Fleet, mitigations and who may act, the
NBO-SUPPLY scenes, what changes in the acceptance specs, gaps with proposed answers, and the
migration for PC-43..45 (only after approval). No code.
```

### Prompt 90 · Supply Chain tables (migration) 🔒
```
PC-43..45, once approved. A new migration: supplier, logistics_route and supply_mitigation
with FORCE RLS, tenant_isolation and the grants as proposed; the guards (same-tenant
references, frozen columns, times written by the database, one active mitigation, stand
down once); pinned search_path. Tests (as nexira_api): isolation; every refusal; the backup
role reads them; the downgrade restores the previous revision exactly.
```

### Prompt 91 · Register, statuses, disruption and mitigation 🔒
```
SUP-01..04, SUP-06. The service: the register with dependencies; reported and shown
statuses (ROUTE BLOCKED, ALTERNATE, impacted) worked out on read; routes tagged by ACTIVE
impact zones; the fuel stock from Fleet; SUPPLY timeline entries; activate and stand down
through app/core/approvals.py; names within the people scope; GET /api/supply/* and
/api/me/permissions; SUPPLY_UPDATED with ids and statuses only; audit. Tests against real
PostgreSQL.
```

### Prompt 92 · Seed, simulated feeds and NBO-SUPPLY
```
SUP-01, SUP-02, SUP-07. The 52 suppliers and 37 routes (Nairobi as the design);
SUPPLY_ROUTE and SUPPLY_SUPPLIER in the worker; the NBO-SUPPLY scenario and its presenter
bar entry. The Phase 1 scenario still starts with no active incident and an empty Decision
Queue. Tests in the simulator.
```

### Prompt 93 · Supply Chain Risk screen
```
SUP-05. The screen (as the design, Blueprint dark): impact banner, KPIs, suppliers table
with a mission filter, the supplier card with dependencies and mitigation, logistics routes;
the nav entry under PLAN & INSIGHT after Document Expiry; every button from
/api/me/permissions; realtime refresh. Tests: Vitest for statuses, the banner, dependencies,
mitigation and names by scope.
```

### Prompt 94 · Supply Chain acceptance
```
Playwright, real stack (requirements-pilot.md §72). Report the real output; make
acceptance (all specs) still passes.
```

## Pilot module 15 · Executive Overview (approved 2026-11-03, PR #119)

Sources: D-45, `docs/requirements-pilot.md` §74–78 (EXE-01..06). Derived from existing data only; no schema change.

### Prompt 95 · Read and plan (no code)
```
Read D-08, D-19, D-20, D-30, D-45, requirements-pilot.md §1-6 and §74-78, and the incident,
signal, campaign, check-in, site readiness, evacuation, health, hazard, supply and fleet code.
Write docs/plan-pilot-exe.md: requirement-to-code mapping, each figure's query and rule
(posture, detection to notification, personnel accounted, readiness, the trend, regional
exposure, attention drivers, the timeline), the country-to-region mapping, the export, what the
acceptance checks, and gaps with proposed answers. No code.
```

### Prompt 96 · The overview service
```
EXE-01, EXE-02, EXE-04. app/modules/executive: GET /api/executive/overview (and the export's
audit, EXECUTIVE.EXPORT through app/core/audit.py), every figure worked out on read, no names.
Tests against real PostgreSQL, including the seeded calm state and the Nairobi incident's
figures.
```

### Prompt 97 · Executive Overview screen and the briefing
```
EXE-03, EXE-05. The screen (as the design, Blueprint dark), last under PLAN & INSIGHT; the
trend chart; realtime refresh; "Export briefing" opening the print-ready page. Tests: Vitest
for the figures, the attention list, the timeline and the briefing.
```

### Prompt 98 · Executive Overview acceptance
```
Playwright, real stack (requirements-pilot.md §77). Report the real output; make
acceptance (all specs) still passes.
```

## Pilot module 16 · Predictive Risk (approved 2026-11-03, PR #126)

Sources: D-46, `docs/requirements-pilot.md` §79–83 (PRD-01..08), PC-46..48. An illustrative, explainable model; advisory only.

### Prompt 99 · Read and plan (no code)
```
Read D-08, D-12..D-19, D-29, D-30, D-42, D-46, requirements-pilot.md §1-6 and §79-83, the
agents framework (proposals, policies, executor), VIP changes, incidents, signals, health,
hazards and weather. Write docs/plan-pilot-prd.md: each index component and its points, the
projection and band, the snapshot job, the seeded history and calendar, drivers, rising risk
and the action rules, the Forecast agent's trigger, evidence and executor path, ADD-FORECAST,
what changes in the acceptance specs, gaps with proposed answers, and the migration for
PC-46..47 (only after approval). No code.
```

### Prompt 100 · Risk index and events calendar tables (migration) 🔒
```
PC-46, PC-47, once approved. A new migration: risk_index and mission_event with FORCE RLS,
tenant_isolation and the grants as proposed; the guards (same-tenant references, today's row
only updated, times written by the database, frozen columns); pinned search_path. Tests (as
nexira_api): isolation; every refusal; the backup role reads them; the downgrade restores the
previous revision exactly.
```

### Prompt 101 · The index, the projection and the screen's API
```
PRD-01..05, PRD-07 (API). app/modules/predictive: the components, the daily snapshot (worker
and on demand), the projection and band, drivers, rising risk, recommended actions,
GET /api/predictive/*; audit. Tests against real PostgreSQL.
```

### Prompt 102 · The Forecast agent (advice only; plan-pilot-prd G-1, option B)
```
PRD-06, PC-48 (the agent row). The FORECAST agent: on MISSION_EVENT_ADDED and
EXPOSURE_COMPUTED, an ADVISE_READINESS_CHECK (level 4, no policy, never executed) when
calendar events take a mission's forecast to 70 or more within 14 days; evidence; one per
mission and peak; no VIP visit, segment, venue or time in it. Tests: the trigger, no
proposal below 70, idempotency, nothing restricted in the text.
```

### Prompt 103 · Seed, history and ADD-FORECAST
```
PRD-01, PRD-05, PRD-08. The 30-day illustrative history and the calendar; the ADD-FORECAST
scenario and its presenter bar entry. The Phase 1 scenario still starts with no active
incident and an empty Decision Queue. Tests in the simulator.
```

### Prompt 104 · Predictive Risk screen
```
PRD-07. The screen (as the design, Blueprint dark), under PLAN & INSIGHT before Executive
Overview; the chart with history, forecast, band and threshold; drivers; rising risk;
recommended actions. Tests: Vitest.
```

### Prompt 105 · Predictive Risk acceptance
```
Playwright, real stack (requirements-pilot.md §82). Report the real output; make
acceptance (all specs) still passes.
```

## Pilot module 17 · After-Action Review (approved 2026-11-09, PR #134)

Sources: D-47, `docs/requirements-pilot.md` §84–88 (AAR-01..09), PC-49..50. Built from the platform record; rules draft, people decide; roles, not names.

### Prompt 106 · Read and plan (no code)
```
Read D-05, D-19, D-20, D-29, D-30, D-45, D-47, requirements-pilot.md §1-6 and §84-88, the
incident timeline, playbook runs and gates, campaigns, check-in, proposals and decisions, and
what evacuations, fleet, site twin, supply and documents record at a mission. Write
docs/plan-pilot-aar.md: the timeline's sources and order, each metric's formula and target,
each drafting rule with its evidence, owner team and priority, the reviewer roles, the state
rules (draft, final, items), the export, the screen, what changes in the acceptance specs,
gaps with proposed answers, and the migration for PC-49..50 (only after approval). No code.
```

### Prompt 107 · Review tables (migration) 🔒
```
PC-49, PC-50, once approved. A new migration: after_action_review and aar_item with FORCE RLS,
tenant_isolation and the grants as proposed; the guards (same-tenant references, the status
transitions, nothing but done on a final review, times written by the database, frozen
columns); pinned search_path. Tests (as nexira_api): isolation; every refusal; the backup role
reads them; the downgrade restores the previous revision exactly.
```

### Prompt 108 · The timeline, the metrics and the drafting rules
```
AAR-02, AAR-03, AAR-04. app/modules/aar: the reconstructed timeline and the metrics worked out
on read, and the drafting rules, each firing only when the record shows it, with evidence and
no names. Tests against real PostgreSQL as nexira_api: each source in the timeline, each metric
and its "—", each rule firing and not firing, no name in any output.
```

### Prompt 109 · Start, decide, finalise and export (API)
```
AAR-01, AAR-05, AAR-06, AAR-07. Start (MONITORING or CLOSED only, one per incident), accept,
reject, add, mark done, finalise (metrics frozen), export (audited). Role checks through
app/core/approvals.py; every change through app/core/audit.py; realtime AAR_UPDATED (ids only).
Tests: each role and refusal, every audited action, the frozen metrics, the Viewer reads only.
```

### Prompt 110 · After-Action Review screen and print-ready review
```
AAR-08. The screen (as the design, Blueprint dark) under PLAN & INSIGHT after Predictive Risk;
the KPIs, metrics, timeline, lessons and actions with Accept, Reject, Add and Done; Finalise;
"Export review" opening a standalone print-ready page; "Start after-action review" on the
Incidents screen. Tests: Vitest.
```

### Prompt 111 · After-Action Review acceptance
```
Playwright, real stack (requirements-pilot.md §87), after the Phase 1 run. Report the real
output; make acceptance (all specs) still passes.
```

## Pilot module 18 · Exercise & Training (approved 2026-11-09, PR #141)

Sources: D-48, `docs/requirements-pilot.md` §89–93 (EXR-01..09), PC-51..52. An exercise is a scenario run in `EXERCISE` mode; scored from the record; readiness from exercises.

### Prompt 112 · Read and plan (no code)
```
Read D-05, D-19, D-21, D-29, D-30, D-43, D-45, D-46, D-47, D-48, requirements-pilot.md §1-6
and §89-93, the scenario engine (runs, modes, the player, external ids per run), what a
response records, After-Action Review's metrics, and where readiness is shown. Write
docs/plan-pilot-exr.md: the templates, how a run's incident is found, how EXERCISE is labelled
and left out of Executive and Predictive, each score's formula and its "—", participants, the
seeded history, readiness on People & Sites, Site Twin and Executive, the state rules, the
screen, the acceptance spec and how it runs after a reset, gaps with proposed answers, and the
migration for PC-51..52 (only after approval). No code.
```

### Prompt 113 · Exercise tables (migration) 🔒
```
PC-51, PC-52, once approved. A new migration: exercise and exercise_score with FORCE RLS,
tenant_isolation and the grants as proposed; the guards (same-tenant references, RUNNING to
COMPLETED or ABANDONED once, scores only on COMPLETED, one RUNNING per mission, times written
by the database, no TRUNCATE); pinned search_path. Tests (as nexira_api): isolation; every
refusal; the backup role reads them; the downgrade restores the previous revision exactly.
```

### Prompt 114 · Scoring, history and readiness
```
EXR-05, EXR-06, EXR-07. app/modules/exercises: the five scores from a run's incident using
After-Action Review's metrics, the overall score, participants, the KPIs; the seeded
illustrative history (matching today's seeded readiness); readiness read from the latest
completed exercise on People & Sites, Site Twin and Executive. Tests against real PostgreSQL
as nexira_api: each score and its "—", the mean, participants, readiness before and after.
```

### Prompt 115 · Launch, end and the EXERCISE label (API)
```
EXR-01..04. Templates; launch (a scenario run in EXERCISE mode, one per mission), end (score
and freeze) and abandon (reason); the EXERCISE label on the run's incident, proposals,
campaigns and check-in; exercise incidents left out of Executive and Predictive. Role checks
through app/core/approvals.py; every change through app/core/audit.py; realtime
EXERCISE_UPDATED (ids only). Tests: each role and refusal, every audited action, frozen scores.
```

### Prompt 116 · Exercise & Training screen
```
EXR-08. The screen (as the design, Blueprint dark) under PLAN & INSIGHT before After-Action
Review: KPIs, recent exercises, Run an exercise (template, kind, Launch, End, Abandon), the
scoring breakdown; the SIMULATED EXERCISE banner while one runs; EXERCISE tags where the
incident appears. Tests: Vitest.
```

### Prompt 117 · Exercise & Training acceptance
```
Playwright, real stack (requirements-pilot.md §92), run on its own after a demo reset. Report
the real output; make acceptance (all specs) still passes.
```

## Pilot module 19 · AI Risk Copilot, simulated (D-50)

Requirements COP-01..08 (`docs/requirements-pilot.md` §94–98); plan `docs/plan-pilot-cop.md`. None of these prompts is 🔒.

### Prompt 118 · Questions, grounding and citations (API)
```
COP-01..03, COP-05, COP-06. app/modules/copilot: the question types (plan §2), facts from the
platform's read functions as the asker with a source each (§3), the Writer protocol in
app/core/llm.py with TemplateWriter (§5); POST /api/copilot/ask; names per plan G-1; restricted
trips never; COPILOT.ASK audited with type and references, never the text. Tests: every type,
every sentence cited, the Viewer and a scoped Head of Mission, unknown declined, no network import.
```

### Prompt 119 · Situation report and export (API)
```
COP-04. The report's sections from the record, rule-based recommendations labelled (plan §4);
POST /api/copilot/report and /report/export (COPILOT.REPORT_EXPORT). Tests: every heading,
every sentence cited, the rules, the export audited, names per G-1.
```

### Prompt 120 · AI Risk Copilot screen
```
COP-07. /copilot under RESPOND after Safety Check-in (plan §6), as the design, Blueprint dark:
the conversation with suggestions and the composer, source chips linking to records, the
simulated label, Grounding context, Guardrails, Export as PDF after a report; the conversation
lives in the tab. Tests: Vitest.
```

### Prompt 121 · AI Risk Copilot acceptance
```
Playwright, real stack (requirements-pilot.md §97; plan §7), in make acceptance's second command
before the After-Action Review spec. Report the real output; make acceptance (all specs) still passes.
```

## Pilot modules 20–21 · Incident Replay and Site Twin camera coverage (D-51)

Requirements RPL-01..07 and TWN-08..11 (`docs/requirements-pilot.md` §99–108); plan `docs/plan-pilot-rpl.md`. None of these prompts is 🔒.

### Prompt 122 · Replay payload (API)
```
RPL-01, RPL-04, RPL-05. app/modules/replay: GET /api/incidents/{id}/replay (plan §2), for the
Incidents readers; the window per G-1 and G-2; AAR-02's timeline reused (G-6) with sensor and
site_id on SITE entries; people with no name or id; trips counted, restricted ones never (G-4);
tally_end from the Safety Check-in's function. Tests on real Postgres: the window, the state
inputs, no name anywhere in the payload, the Viewer, an exercise incident, a restricted trip.
```

### Prompt 123 · Replay screen
```
RPL-02, RPL-03, RPL-06, RPL-07. /incidents/replay (plan §3): ReplayMap on the self-hosted tiles,
the figures, the timeline, the bar with marks, speeds and keys; state at t as a pure function
(screens/replay/state.ts) checked against tally_end; reduced motion steps entry to entry; links
from Incidents, After-Action Review and Exercise & Training; t in the address. Tests: Vitest.
```

### Prompt 124 · Camera mounts (migration and API)
```
TWN-08, PC-53. Migration 0018: the five site_sensor columns, existing CCTV rows filled (plan §4),
then the CHECK; the same mounts in the seed; the twin API's sensor carries them. Tests on real
Postgres: the CHECK both ways, nexira_api cannot update them, the API returns them.
```

### Prompt 125 · Coverage on the plan, handoff and KPI
```
TWN-09..11. screens/twin/coverage.ts (plan §5): clipped cones, the grid, the KPI, the uncovered
list; the "Camera coverage" toggle; red dashed cones for cameras that are down; place → camera
from the plan, Sensors & systems and the incident's SITE entries (/twin?site=…&camera=…, G-8).
Tests: Vitest, including the seeded gap and CAM-07 offline.
```

### Prompt 126 · Acceptance
```
Playwright, real stack (§102, §107; plan §6): rpl-acceptance.spec.ts after the After-Action Review
spec; the coverage checks in twn-acceptance.spec.ts. Report the real output; make acceptance (all
specs) still passes.
```

## Pilot modules 22–24 · Map annotations, Nearby and map search (D-52)

Requirements ANN-01..06, NBY-01..06 and SRC-01..04 (`docs/requirements-pilot.md` §109–115); plan `docs/plan-pilot-map.md`. Prompt 127 is 🔒 (D-29).

### Prompt 127 · Annotations table (migration) 🔒
```
ANN-01, ANN-03, PC-54. Migration 0020: map_annotation as PC-54 (plan §2): the geometry type
checked against the kind, the guard (kind, author, incident and mission fixed; ACTIVE → WITHDRAWN
once with a reason; times by the database), FORCE RLS, the column grants, no DELETE. Tests on real
Postgres as nexira_api: RLS across tenants, the guard each way, no DELETE, the downgrade. Needs a
named human reviewer's sign-off in the PR (D-29).
```

### Prompt 128 · Annotations API
```
ANN-01..06. app/modules/annotations (plan §2): list, add, edit, withdraw; roles and mission scope
through approvals.py (G-2); the author's role, never the person; audit.write for each change; an
ANNOTATION incident_event for a linked incident; annotation.changed published; AAR-02's timeline
and the replay payload carry annotations (G-4). Tests on real Postgres: each role, the Head of
Mission's scope, the Viewer refused, the audit rows, no name in any response.
```

### Prompt 129 · Annotations on the map
```
ANN-01..04, ANN-06. map/annotations.ts (pure) and the layers on Global Operations: marks, lines,
areas; the toolbar from zoom 5 (G-6); the form; the popup with Edit and Withdraw where allowed;
the layer switch; realtime refresh; annotations on the replay map at t. Tests: Vitest for the
drawing state and the GeoJSON.
```

### Prompt 130 · Nearby API
```
NBY-01..04. GET /api/nearby (plan §3): each kind with distance, nearest first; people by the
exposure groups (G-5) with names only within name_scope(); restricted trips never (D-33);
partners by the nearest mission's country (G-1); not audited. Tests on real Postgres: the radius
bounds, the Viewer gets counts, a restricted traveller left out, RLS across tenants.
```

### Prompt 131 · Nearby panel
```
NBY-01, NBY-02, NBY-05, NBY-06. The panel on Global Operations: right-click without a drag
(G-10), long press, and from a mission, site or incident popup; radius chips; the circle; rows
that open their screen or fly the map; ?near=…&r=… in the address. Tests: Vitest.
```

### Prompt 132 · Map search
```
SRC-01..04. infra/scripts/build-places.py and frontend/src/map/places.json (Natural Earth,
public domain, checked by SHA-256); map/search.ts (coordinates, DMS, geo: URIs, records, places);
the box on Global Operations and Air (/ to focus, keys, fly and mark, "What's nearby"); the
gazetteer loaded on first focus (G-11). Tests: Vitest for the parser and the ranking.
```

### Prompt 133 · Acceptance
```
Playwright, real stack (§114; plan §5): map-acceptance.spec.ts before the Copilot spec, and the
replay's annotation check in rpl-acceptance.spec.ts. Report the real output; make acceptance (all
specs) still passes.
```

## Pilot module 25 · Site Twin live activity (D-53)

Requirements TWN-12..TWN-16 (`docs/requirements-pilot.md` §116–120); plan `docs/plan-pilot-twa.md`. None of these prompts is 🔒.

### Prompt 134 · The normal day
```
TWN-13 (plan §2, G-1..G-4). app/modules/twin/ambient.py in the worker: a deterministic day
script over the seeded occupants through twin.service.presence() every 60 s (±15 s); paused by
shelter, an ACTIVE evacuation or an NBO-SITE run; the switch per G-2 (TWIN_NORMAL_DAY, off for
reset-demo and acceptance; presenter bar "Normal day", audited). Tests on real Postgres: a tick
moves one occupant and audits it, each pause, the band, the switch.
```

### Prompt 135 · Recent movements
```
TWN-14 (plan §3, G-5). GET /api/sites/{id}/twin/movements: the last 20 SITE.PRESENCE entries as
kind and zones, and today's arrivals, departures and visitors waiting; no person id, label or
name. Tests on real Postgres: the order, the figures, nothing identifying in the response.
```

### Prompt 136 · People who move, and rooms
```
TWN-12, TWN-16 (plan §4, G-6, G-7, G-9). screens/twin/motion.ts and furniture.ts (pure, tested);
the plan draws dots at stable places with drift, walks on a zone change, the share tint, the
furniture; reduced motion and Calm still; the movements strip under the plan. Tests: Vitest.
```

### Prompt 137 · Activity on the camera wall
```
TWN-15 (plan §5, G-8). The count from presence on each tile; the stylised walkers over the clips
as in the generated views; NO SIGNAL unchanged. Tests: Vitest.
```

### Prompt 138 · Acceptance
```
Playwright, real stack (§119; plan §6): twa-acceptance.spec.ts last in make acceptance, with the
normal day on; every other spec with it off. Report the real output; make acceptance (all
specs) still passes.
```

## Pilot module 26 · UI polish pass (D-54)

Requirements UIP-01..UIP-08 (`docs/requirements-pilot.md` §121–125); plan `docs/plan-pilot-uip.md`. None of these prompts is 🔒.

### Prompt 139 · Ticker and sidebar
```
UIP-01, UIP-06, UIP-07 (plan §1, G-1, G-2, G-5). The ticker: open incidents (ACTIVE and
MONITORING) most severe first, then events; faded edges; still with one copy when it fits,
scrolling only when it overflows (pure scrolls(), ResizeObserver). Sidebar: unique icons
(symbol-cross, helper-management, clipboard-file); Audit only for ADMIN, display only. Tests:
Vitest for the order, scrolls(), unique icons, Audit per role.
```

### Prompt 140 · Screen fixes
```
UIP-02..UIP-05, UIP-08 (plan §1, G-3). ui/Clip.tsx (ellipsis plus title); "Open AAR" with the
reference as tooltip and header actions on one line; Clip on the cut subtitles and source labels;
the Site Twin cameras button in the CCTV row; Check-in names on one line, a small minimal
"Request partner", the phone header on one line; a taller Air Travel map. Tests: Vitest; before
and after screenshots in the PR.
```

### Prompt 141 · Acceptance
```
Playwright, real stack (§124; plan G-4): uip-acceptance.spec.ts over every screen at 1440 × 900
and 1920 × 1080 as the Duty Officer, plus the specific cases; in make acceptance before
twa-acceptance.spec.ts. Report the real output; make acceptance (all specs) still passes.
```

## Pilot module 27 · Graphics (D-55)

Requirements GFX-01..GFX-08 (`docs/requirements-pilot.md` §126–130); plan `docs/plan-pilot-gfx.md`. None of these prompts is 🔒.

### Prompt 143 · The NASA globe
```
GFX-01..GFX-04 (plan §1, G-1..G-5). build-tiles.sh: Blue Marble December 2004 and Black Marble
2016 pinned by SHA-256, GDAL from a digest-pinned container, earth-day/earth-night.pmtiles at zoom
0-5. style.ts: the raster under the vector layers, toned down, fading out by zoom 6, the dark
fills clear at world zoom, "Imagery: NASA Earth Observatory"; the fallback without the file.
Night lights: a short spike, otherwise today's shade (G-4, recorded in the PR). The band outside
the rim: find the cause first, pixel check before the fix. Tests: Vitest for the style with and
without imagery; screenshots of Operations and Air in the PR; file sizes in the PR.
```

### Prompt 144 · The trend and sparklines
```
GFX-05, GFX-07 (plan G-6, G-7). executive/service.py: illustrative days on read, deterministic
from the date, before the first live data; TrendDayOut.source. ExecutiveScreen: illustrative
days lighter and labelled; totals count live days only. Kpi gains an optional trend drawn with
Sparkline; Signals · 24h, Active incidents, Awaiting decision. Tests: pytest (30 days, source,
same counts on every read, live days match the record) as nexira_api; Vitest (no history, no line).
```

### Prompt 145 · Resting states and the mini-map
```
GFX-06, GFX-08 (plan G-8, G-9). Decision Queue: "Watching now" from existing hooks and each
agent's latest check; Executive: quiet for N days and the last incident on record; layout per
G-8. map/MiniMap.tsx on incident detail: still, flat, the incident, mission and people exposed;
a click opens Global Operations on the incident. Tests: Vitest for the texts and the click;
screenshots in the PR.
```

### Prompt 146 · Acceptance
```
Playwright, real stack (§129): gfx-acceptance.spec.ts. After make reset-demo: the trend is not
flat and illustrative days are labelled; Queue and Executive pass the G-8 check at 1440 × 900;
imagery tiles load from /tiles/ with no request leaving the stack; nothing outside the globe's
disc on Operations and Air; after scene 1 the mini-map shows the incident and opens Global
Operations. In make acceptance before twa-acceptance.spec.ts. Report the real output; make
acceptance (all specs) still passes.
```

## Pilot module 28 · Design consistency (D-56)

Requirements DC-01..DC-08 (`docs/requirements-pilot.md` §131–135); plan `docs/plan-pilot-dc.md`. None of these prompts is 🔒.

### Prompt 147 · Shared components and the style fixes
```
DC-03..DC-08 (plan §1, G-5..G-8). ui/: Empty, ContextLine, TileRow, Card's chip, plural().
Every card's NonIdealState and dim sentence becomes Empty; NonIdealState stays for errors, no
access and not found (G-6). Panel spinners become SkeletonRows (G-7). Header counts move to the
chip. ContextLine on Executive, Site Twin, Decision Queue, AI Agents and Health (G-8). Sentences
out of monospace. Tests: Vitest for each component; existing tests updated, none deleted.
Screenshots of every changed screen in the PR.
```

### Prompt 148 · Tile rows
```
DC-01, DC-05 (G-1..G-4). TileRow on Incidents, Response Playbooks, Predictive Risk and Audit;
Safety Check-in and After-Action Review show theirs at rest, with empty panels. Audit's chain
status and log in cards. Figures from APIs each screen already calls; "—" before they load;
"200+" for Audit's day count when the page is full. Tests: Vitest for each tile's figure and
the at-rest layouts. Screenshots in the PR.
```

### Prompt 149 · Sparklines
```
DC-02 (G-9). Kpi trend on Mass Notification's 24h tiles, AI Agents' Proposals, Exercises ·
year, Incidents' Opened · 30 days, Playbooks' Runs · 30 days and Audit's Entries · 24 h, from
buckets() over times the screens load. None without history; none on state tiles. Tests:
Vitest for each tile's buckets. Screenshots in the PR.
```

### Prompt 150 · Acceptance
```
Playwright, real stack (§134): dc-acceptance.spec.ts as the Administrator at 1440 × 900, every
screen in the sidebar. After make reset-demo: the DC-01 screens have their tile row; no
page-filling empty state on a working screen; once loaded, no spinner outside a button or
dialog; no sentence in monospace; at most one chip per card header. In make acceptance
before twa-acceptance.spec.ts. Report the real output; make acceptance (all specs) still passes.
```

## Pilot module 29 · Site Twin: people in the camera clips (D-57)

Requirements TWN-17..TWN-19 (`docs/requirements-pilot.md` §136–139). One prompt; the change is
small enough that its plan is the prompt. Not 🔒.

### Prompt 151 · People in the camera clips
```
TWN-17..19 (D-57). infra/scripts/build-cctv-clips.sh: replace the clips for the gates, lobby,
consular hall, offices, conference room and muster point with free-licence stock clips of
people seen from behind or at a distance (SHA-256 pinned, as now); a zone kind with no suitable
clip keeps its empty one. Check every frame of each built loop; contact sheets in the PR.
CctvWall.tsx: no figures layer over a clip; generated views and NO SIGNAL unchanged; the card's
sub-line "Stock footage, looped · counts come from access control". README.md in
frontend/public/cctv and plan-pilot-twa.md ("As built") updated. Tests: Vitest for the wall;
twa-acceptance.spec.ts checks no figures layer over a clip and the counts as before. Report the
real output; make acceptance (all specs) still passes.
```
