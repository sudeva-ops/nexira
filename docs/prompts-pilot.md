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

The prompts for the Travel & Air agent and (if the customer wants it) Assistance Partners are written after their requirements are approved (requirements-pilot.md §7).
