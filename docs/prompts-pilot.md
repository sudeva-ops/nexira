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
