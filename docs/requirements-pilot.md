# NEXIRA · Pilot modules: requirements · v0.1

For the product owner, who approves this document; then for the coding agent, which builds from `docs/prompts-pilot.md`. It adds to `docs/requirements.md` (the Phase 1 PRD) and follows `docs/decisions.md`, in particular D-30 (pilot scope) and D-31 (Mass Notification rules).

**Status:** Mass Notification was **approved by the product owner on 2026-10-25** (PR #16), with the defaults for the questions in §8. The other pilot modules are only outlined (§7). Each will be written and approved before it is built.

---

## 1. Purpose

Phase 1 (Prompts 0–16) is complete: the core loop on simulated data, with the Nairobi acceptance scenario passing. The pilot adds the modules in D-30 that can be shown on simulated data, starting with Mass Notification:
- It is the smallest of them, because the campaign and delivery engine already exists.
- It completes the "Essentials" packaging tier (master spec §2.4, and decisions.md §9 item 7).
- Its per-mission templates fix a known demo limitation: today the PB-07 citizen advisory text names Nairobi, even for an incident in Paris.

## 2. What already exists (no work needed)

| Capability | Where |
|---|---|
| Campaigns and deliveries, with NTF references | `notification_campaign`, `notification_delivery`, `backend/app/modules/notifications/service.py` |
| Statuses `DRAFT`, `SENDING`, `SENT`, `CANCELLED`; `created_by_type` `USER`; `incident_id` optional; type `TEST` | schema v0.2 (the API does not use them yet) |
| Five channels (APP, SMS, WHATSAPP, VOICE, EMAIL) through the simulated adapter only | `notifications/channels.py` (CHK-04, D-29) |
| Delivery states QUEUED → SENT → DELIVERED → READ / FAILED, the outbox dispatcher and idempotency | `notifications/consumer.py` |
| Approvals with roles, mission scope and one person per step | `app/core/approvals.py` (D-05, D-16) |
| Read-only campaign list and detail API | `GET /api/campaigns`, `GET /api/campaigns/{id}` |

## 3. Requirements: Mass Notification (MN)

Priority: M = Must, S = Should. The "Master" column gives the master spec ID each requirement implements.

| ID | Requirement | Master | Pri. | Acceptance |
|---|---|---|---|---|
| MN-01 | **Compose** a campaign: kind (ALERT, ADVISORY, CHECKIN), message, channels, audience, optional incident. It is saved as a DRAFT and can be edited until it is sent. | NTF-01 | M | A Duty Officer creates a draft. Its NTF reference is allocated at creation (D-18). Editing it changes nothing in `notification_delivery`. |
| MN-02 | **Audiences:** by mission (one or more), by person type (staff, delegates, dependants, contractors, citizens), and "exposed to incident X". The recipient count and the split by person type are shown before sending. | NTF-01 | M | The preview for "NBO, citizens" shows 212. The preview for "exposed to INC-…-1042" shows 229 (D-23). |
| MN-03 | **Templates** per mission and kind, with a generic fallback. A template holds EN and pre-written translations, each marked reviewed or not (D-15). A template fills the message, and the user may edit the result. | NTF-01, NTF-03 | M | Choosing "Civil unrest: shelter in place" for a Paris campaign gives Paris text, not Nairobi text. With no Paris template, it gives the generic text with the mission's city. |
| MN-04 | **PB-07 and the Communications agent use the templates.** The advisory comes from the incident mission's template, so no advisory text is fixed in the playbook seed. | — | M | In the France scenario, the advisory proposed for Paris contains no "Nairobi", "CBD" or "Upper Hill". The Nairobi acceptance scenario is unchanged. |
| MN-05 | **Second person for citizens** (D-31). If the audience includes citizens, the campaign goes to *pending approval*. It is sent only when a different user with `DUTY_OFFICER\|CONSULAR_OFFICER` approves it, through `approvals.decide`. A staff-only campaign can be sent by its author, if the author holds `DUTY_OFFICER\|SECURITY_OFFICER`. | NTF-01, AGR-04 | M | The author's own approval is refused (403). A Viewer cannot approve. A second Duty Officer approves, and the deliveries are queued. |
| MN-06 | **Unreviewed translations block sending in a pilot.** With `APP_ENV=pilot`, a campaign with an unreviewed translation cannot be sent; the user removes that language or uses a reviewed text. Local and demo keep today's behaviour, with the marker shown. | NTF-03, D-15 | M | Pilot mode: 409 with the language named. Demo mode: it is sent with `[REVIEW REQUIRED]`. |
| MN-07 | **Cancel** a draft or a campaign pending approval. A sent campaign cannot be cancelled. | NTF-05 | M | Cancel → CANCELLED, audited; no deliveries. |
| MN-08 | **Test send to self.** It renders the message as each chosen channel would show it, in the phone preview panel. It creates no deliveries, and it writes an audit row. | NTF-05 | M | The audit row shows `CAMPAIGN.TEST_SEND`; the delivery count is unchanged. |
| MN-09 | **Delivery funnel** for each campaign and channel: queued, sent, delivered, read, failed. It updates live over the WebSocket. | NTF-04 | M | During the simulated sending, the counts move without a page reload. |
| MN-10 | **Campaign history:** a list of all campaigns (from playbooks, agents and users) with filters for kind, status, mission and incident, and who created and approved each one. | NTF-05 | M | The list shows the PB-07 check-in and the advisory from the Nairobi scenario next to composed campaigns. |
| MN-11 | **Deferred** (product owner, 2026-10-25, PR #17): not in this module. Campaigns keep sending on every chosen channel at once. Original text: **Channel fallback (simulated):** when a delivery FAILS on a channel, the next channel in the campaign's order is tried for that person, once. The simulated adapter can fail a configurable share of deliveries, in demo only. | NTF-02 | S | With a 10 % SMS failure rate, the failed people receive an EMAIL delivery, and the funnel shows both. |
| MN-12 | **Everything audited:** create, edit, submit, approve, reject, cancel, test send and send. Each audit row records the user, and the audit chain still verifies. | PLT, D-20 | M | `GET /api/audit/verify` is intact after the e2e test. |

### Not in this module
- Real SMS, email, WhatsApp or voice delivery: channels stay simulated (D-30).
- Machine translation: D-15 still applies; this waits for the local model.
- Scheduled sends, recurring campaigns, and replies from recipients other than check-in answers.

## 4. Roles

| Action | Roles |
|---|---|
| Read campaigns | All Phase 1 roles (as today) |
| Compose, edit, cancel, test send | `DUTY_OFFICER`, `SECURITY_OFFICER`, `CONSULAR_OFFICER`, `ADMIN` |
| Send to staff and delegates only | the author, holding `DUTY_OFFICER\|SECURITY_OFFICER` |
| Approve a campaign that reaches citizens | a different user, holding `DUTY_OFFICER\|CONSULAR_OFFICER` |
| Manage templates and mark translations reviewed | `ADMIN`, `CONSULAR_OFFICER` |

Mission scope works as in D-05. A Head of Mission sees and approves only within their mission's campaigns, but is not an approver by default.

## 5. Data changes

These are proposed in `docs/schema/proposed-changes.md` and need approval before the migration is written:
- **PC-07 · `message_template`:** a new tenant table for templates per mission and kind, with RLS and grants. It is a 🔒 change (D-29).
- **PC-08 · `notification_campaign` columns for approval:**
  - a `PENDING_APPROVAL` status;
  - `submitted_by`, `approved_by`, `approved_at`, `template_id`;
  - a trigger that refuses `approved_by = created_by`, as a database backstop for MN-05.

## 6. Acceptance for the module

An end-to-end test (Playwright, real stack):
1. A Duty Officer composes an advisory for the Paris mission's citizens from a template, test-sends it to themselves, and submits it.
2. The same user cannot approve it.
3. A second Duty Officer approves it. The deliveries are queued, and the funnel reaches *read* for every person.
4. The audit chain verifies at the end.

The Nairobi acceptance scenario and the France scenario still pass. The France scenario's advisory now names Paris.

## 7. Next modules (outline only; to be written before they are built)

| Module | Starting point | Needs to be decided |
|---|---|---|
| Journey Management (JRN-01..05) | **Written: §9 (approved, built: Prompts 23–27)** | — |
| Air Travel Tracking (AIR-01..07) | **Written: §14 (approved, built: Prompts 28–32)** | — |
| Travel & Air agent | **Written: §19 (approved, built: Prompts 33–37)** | — |
| Assistance Partners (AST-01..04) | nothing | only if the pilot customer wants it |
| Weather (WX), D-35 | **Written: §24 (approved)** | — |

## 8. Questions answered by the product owner (2026-10-25)

1. **Second person:** for campaigns that reach citizens only (MN-05 as written). Size alone does not trigger it.
2. **Templates:** maintained by `ADMIN` and `CONSULAR_OFFICER` (§4 as written).
3. **Channel fallback (MN-11):** first answered "wanted". It was then **deferred** on 2026-10-25 (PR #17, plan G-1), because it needs a delivery-mode column (PC-09) that is not worth adding before real gateways exist.

---

# Pilot module 2 · Journey Management (approved 2026-10-26, PR #24)

For the product owner, who approves this part; then for the coding agent (Prompts 23–27 in `docs/prompts-pilot.md`). Rules: D-30, and **D-32** (proposed with this draft).

## 9. Purpose and starting point

Travel risk and approvals (master spec §5.10, JRN-01..05): know who is travelling where, approve risky trips before they start, prepare the traveller, and see at once which trips an incident hits.

| Exists today | Where |
|---|---|
| `trip` (reference, purpose, origin, destination, `destination_country`, dates, `risk_level`, `approval_status` PENDING/APPROVED/REJECTED) and `trip_traveller` | schema v0.2 |
| Trips in incident exposure: active today and a traveller exposed (D-22); the Nairobi scenario's TRP-8812 | `intel/exposure.py`, seed |
| `TRAVEL_DESK` role and the `travel.desk` demo user | roles seed, Keycloak realm |
| Nothing else: no trip API, no screen, no itinerary, no checklist, no approver columns | — |

## 10. Requirements: Journey Management (JR)

| ID | Requirement | Master | Pri. | Acceptance |
|---|---|---|---|---|
| JR-01 | **Create and edit a trip** as a draft: purpose, travellers (people from People & Sites), origin, destination city and country, dates. Created by TRAVEL_DESK or DUTY_OFFICER on the traveller's behalf (no self-service in the pilot). | JRN-01 | M | A Travel Desk user creates TRP-…; a Viewer gets 403. |
| JR-02 | **Itinerary** of ordered segments: flight, stay, meeting, ground transport; each with a place, start and end time. Shown as a timeline. | JRN-01 | M | Segments outside the trip's dates are refused. |
| JR-03 | **Destination risk** at submission: the country's base level (simulated, PC-16) raised to the worst ACTIVE incident severity in that country. Stored on the trip at submission; shown with a four-part breakdown (security, civil unrest, health, transport). | JRN-04 | M | A trip to France during the France scenario rates HIGH or above. |
| JR-04 | **Approval by risk** (D-32): LOW is approved on submission; MODERATE needs TRAVEL_DESK or SECURITY_OFFICER; HIGH and CRITICAL need SECURITY_OFFICER. Never the requester; through `approvals.decide()`. Reject needs a reason. | JRN-02 | M | The requester's approval → 403; a Travel Desk approval of a HIGH trip → 403; a Security Officer → APPROVED. |
| JR-05 | **Pre-travel checklist**: security briefing, insurance and medical cover, emergency contacts, check-in schedule (each ticked by a user, audited) and security approval (set by the approval). A HIGH or CRITICAL trip cannot be approved until the first four are ticked. | JRN-03 | M | Approving a HIGH trip with an open item → 409 naming it. |
| JR-06 | **Impacted trips**: a trip active today with a traveller in an incident's exposure shows "Impacted by INC-…" in the list and detail, and the incident lists the trip (exists, D-22). | JRN-05 | M | In the Nairobi scenario, TRP-8812 shows "Impacted by INC-…-1042". |
| JR-07 | **Risk changed since approval**: if the destination risk rises above the approved level, the trip is flagged (not revoked); the Travel & Air agent will propose actions later. | JRN-04 | S | After the France scenario starts, an approved LOW Paris trip shows "risk now HIGH". |
| JR-08 | **Trips screen**: list with filters (status, risk, mission, impacted), detail with itinerary, checklist, risk breakdown, travellers, and actions shown from `GET /api/me/permissions`. KPIs from data (D-27). | JRN-01 | M | — |
| JR-09 | **Everything audited**: create, edit, submit, approve, reject, cancel, checklist ticks. | PLT | M | `GET /api/audit/verify` intact after the e2e. |

### Not in this module
Live flights (Air Travel Tracking, next), booking integration (GDS), traveller self-service or a mobile app, and automatic actions on risk changes (the Travel & Air agent).

## 11. Data changes (proposed in `docs/schema/proposed-changes.md`)

- **PC-14 · `trip_segment`**: the itinerary.
- **PC-15 · trip approval and checklist**: `DRAFT` and `CANCELLED` statuses, `requested_by`, `submitted_at`, `approved_by`, `approved_at`, `rejection_reason`, `approved_risk_level`, `mission_id` (scope), a `checklist` jsonb, and a guard trigger in the style of PC-10/11/12 (no self-approval, approval frozen, content frozen once submitted, forward-only status).
- **PC-16 · `country_risk`**: simulated base levels and the four-part breakdown per country (D-19 label "simulated").

## 12. Acceptance for the module

Playwright on the real stack: a Travel Desk user plans a Paris trip for two staff during the France scenario; it rates HIGH; the Travel Desk cannot approve it and the requester cannot either; the checklist blocks approval until ticked; the Security Officer approves; the Nairobi scenario shows TRP-8812 as impacted; the audit chain verifies; `make acceptance` (Nairobi and Mass Notification) still passes.

## 13. Questions answered by the product owner (2026-10-26: "use the defaults")

1. **Approval thresholds:** LOW automatic; MODERATE Travel Desk or Security Officer; HIGH and CRITICAL Security Officer only. CRITICAL does **not** also need the HQ Crisis Director.
2. **Who creates trips:** Travel Desk and Duty Officers; no traveller self-service in the pilot.
3. **Checklist:** security briefing, insurance and medical cover, emergency contacts, check-in schedule (plus security approval, set by the approval). All four must be ticked before a HIGH or CRITICAL trip is approved.
4. **Risk rises after approval:** flagged, not paused; the Travel & Air agent proposes actions later.


---

# Pilot module 3 · Air Travel Tracking (approved 2026-10-27, PR #30)

For the product owner, who approves this part; then for the coding agent (Prompts 28–32 in `docs/prompts-pilot.md`). Rules: D-30, and **D-33**. Everything here runs on **simulated flights**: no flight-data provider is called (AGENTS.md: no external URLs at runtime).

## 14. Purpose and starting point

Officials in the air (master spec §5.11, AIR-01..07): see which of our travellers are flying, where they are, and when a flight is delayed, holding, diverted or cancelled, and know where the travellers are once they land.

| Exists today | Where |
|---|---|
| Trips with FLIGHT segments (title, place, times) and approval | Journey Management (PC-14, PC-15) |
| `location_observation.source` already allows `FLIGHT`; location recompute and exposure | schema v0.2, `people/location.py`, `intel/exposure.py` |
| Self-hosted map (MapLibre, PMTiles), realtime events, the scenario player | D-24, PLT-05, Prompt 6 |
| Nothing else: no airports, flights, flight events, flight number on a segment, or a way to mark a trip as VIP | — |

## 15. Requirements: Air Travel Tracking (AT)

| ID | Requirement | Master | Pri. | Acceptance |
|---|---|---|---|---|
| AT-01 | **Only our travellers' flights.** A flight is tracked only when it comes from a FLIGHT segment of an **approved** trip, with a flight number and departure and arrival airports. Nothing else is queried or shown; there is no "all flights" view. | AIR-01 | M | A flight segment of a DRAFT, PENDING or CANCELLED trip is not tracked. |
| AT-02 | **Air picture and tracked-flight table**: map with each tracked flight's simulated position and route; table with flight, travellers, route, progress, altitude, ETA and status; detail with the flight's events. Positions labelled simulated (D-19). | AIR-02 | M | — |
| AT-03 | **Disruptions detected**: DELAYED (departure or arrival estimate 30 min or more late), HOLDING, DIVERTED (with the new airport), CANCELLED. Each is a flight event, shown at once (realtime) in the table, a banner and the trip's detail. Proposals for what to do come with the Travel & Air agent (module 4), not here. | AIR-03 | M | In the Nairobi scenario, XW 451 shows HOLDING, then DIVERTED · Mombasa. |
| AT-04 | **Landing updates where travellers are.** When a flight lands (at its destination or a diversion airport), each traveller gets a location observation with source `FLIGHT` at that airport, through the existing location service; current location and exposure follow. | AIR-04 | M | After XW 451 lands in Mombasa, its 3 travellers' current location is Mombasa (source FLIGHT). |
| AT-05 | **Never show VIP or ministerial movements.** A trip can be marked **restricted** when planned (frozen once submitted). A restricted trip's flights are never tracked: no flight row, no position, nothing in any API, screen, event or export. | AIR-06 | M | A restricted trip's flight is absent from `GET /api/flights`, the map and the audit details. |
| AT-06 | **Simulated feed with the same seams as a real one.** A flight tracker in the worker ensures flights for approved trips (from 24 h before departure), moves them along their route on the clock, and applies scenario events (delay, hold, divert, cancel). It is the only writer of flights; a real provider later replaces only this tracker. | AIR-01, 02 | M | — |
| AT-07 | **Trip and flight together.** The Journey screen shows each flight segment's live status; the Air screen links each flight to its trip. Cancelling a trip stops tracking its flights. | AIR-01 | S | — |
| AT-08 | **Audited.** Each flight's creation and every status change is written through `audit.write` (actor `SYSTEM`, the tracker). Positions are not audited. | PLT | M | `GET /api/audit/verify` intact after the e2e. |

### Not in this module
Evacuation charter flights (AIR-05: there is no Evacuation module in the pilot); rebooking, hotel booking and "notify travellers" actions (AIR-07: the Travel & Air agent, module 4); diversion or rebooking proposals in the Decision Queue (module 4); any real flight-data provider.

## 16. Data changes (proposed in `docs/schema/proposed-changes.md`)

- **PC-17 · flight details on a segment, and restricted trips**: `trip_segment.flight_number`, `from_airport`, `to_airport` (IATA codes, for FLIGHT segments); `trip.restricted boolean`, frozen once the trip leaves DRAFT (the PC-15 guard).
- **PC-18 · `airport`**: a simulated reference list (IATA code, name, city, country, location) for the seeded missions' cities and the scenario airports.
- **PC-19 · `flight` and `flight_event`**: one flight per tracked segment (status, schedule and estimates, current simulated position, altitude, speed, diversion airport) and an append-only event log. Written only by the tracker; read-only for the API role.

## 17. Acceptance for the module

Playwright on the real stack: the Nairobi scenario's inbound XW 451 (Abu Dhabi → Nairobi, 3 HQ staff, an approved seeded trip) appears on the air picture; when the incident affects the airport roads it shows HOLDING, then DIVERTED · Mombasa, then LANDED; the banner and the trip's detail update live; the 3 travellers' current location becomes Mombasa (source FLIGHT); a seeded restricted trip's flight never appears; the audit chain verifies; `make acceptance` (Nairobi, Mass Notification, Journey) still passes.

## 18. Questions answered by the product owner (2026-10-27: "use the defaults")

1. **Which trips are tracked:** APPROVED only.
2. **Restricted (VIP/ministerial) trips:** a `restricted` flag set by the planner; their flights are never tracked or shown to anyone.
3. **Delay threshold:** 30 minutes late against schedule.
4. **Disruptions without the agent:** banner, table and trip detail, live; no Decision Queue proposal until the Travel & Air agent (module 4).
5. **Location on landing:** yes, one `FLIGHT` observation per traveller at the landing airport.
6. **Flight time in the demo:** scenario flights run compressed (minutes), other seeded flights in real time.
7. **Flight numbers:** fictional (e.g. "XW 451"), as the demo; no real airline schedules.

---

# Pilot module 4 · Travel & Air agent (approved 2026-10-27, PR #36)

For the product owner, who approves this part; then for the coding agent (Prompts 33–37 in `docs/prompts-pilot.md`). Rules: D-12 to D-17 (agents), D-29, D-30, D-31 to D-33, and **D-34**.

## 19. Purpose and starting point

The master spec's fifth agent (§ agents, "Travel & Air": watches bookings and flight status; proposes diversions, rebooking and trip conditions; approved by the Travel Desk or Security; level 2). In the pilot there is no booking system and channels are simulated (D-19), so the agent proposes what the platform can actually do, through the same service functions a user calls, and only **advises** on what it cannot (rebooking, hotels).

| Exists today | Where |
|---|---|
| The agent framework: proposals, policies, levels, approvals, alternatives, expiry, kill switch, executors | D-12 to D-17, `app/modules/agents` |
| Flights with disruptions (`FLIGHT_UPDATED`), trips with "risk now X" (JR-07) and "impacted by" (JR-06) | Prompts 25, 30 |
| Staff campaigns through the notification service, simulated channels | D-31, `notifications/service.py` |
| Nothing yet: a travel agent, travel action types, a "trip travellers" audience, an agent path to cancel a trip | — |

## 20. Requirements: Travel & Air agent (TA)

| ID | Requirement | Master | Pri. | Acceptance |
|---|---|---|---|---|
| TA-01 | **Disrupted flight.** When a tracked flight goes HOLDING, DIVERTED or CANCELLED, or is 60 minutes or more late, the agent proposes **NOTIFY_TRAVELLERS**: a message to that trip's travellers saying what happened and that the Travel Desk will follow up. | AGT (Travel & Air), AIR-03 | M | In NBO-AIR-DIVERSION, XW 451 holding gives one pending proposal to notify its 3 travellers. |
| TA-02 | **Onward travel advice.** For a DIVERTED or CANCELLED flight it also proposes **ADVISE_REBOOKING** (advice only, level 4): arrange onward travel and a hotel through the travel management company. Nothing is booked by the platform. | AIR-07 | M | XW 451 diverted to Mombasa gives an advice card naming Mombasa. |
| TA-03 | **Trip in an incident.** When a trip is impacted by an ACTIVE incident (JR-06), the agent proposes NOTIFY_TRAVELLERS with safety instructions, linked to the incident. | JRN-05 | M | In the Nairobi scenario, TRP-8812 impacted by INC-…-1042 gives one proposal. |
| TA-04 | **Risk rose since approval.** When an approved trip that has **not started** is flagged "risk now X" (JR-07) with X HIGH or CRITICAL, the agent proposes **CANCEL_TRIP**, with "notify the travellers instead" as an alternative (D-14). A trip in progress gets NOTIFY_TRAVELLERS only. Never automatic (D-32: flag, don't revoke). | JRN-04 | M | During the France scenario, an approved Paris trip next week gives a CANCEL_TRIP proposal. |
| TA-05 | **Through the same services.** NOTIFY_TRAVELLERS creates a staff campaign to the trip's travellers through the notification service (new audience: the travellers of one trip; refused if any is a citizen, D-31). CANCEL_TRIP cancels through the trips service, audited with the agent as actor and the approver recorded. ADVISE_REBOOKING is never executed. | AGT-05 | M | Executing writes the same rows and audit as a user doing it. |
| TA-06 | **Policies (D-12, D-16).** NOTIFY_TRAVELLERS: level 2, `TRAVEL_DESK|SECURITY_OFFICER`. CANCEL_TRIP: level 2, `SECURITY_OFFICER`. ADVISE_REBOOKING: no policy (level 4). None is undoable. Decisions expire after 60 minutes. | AGT-03 | M | The requester of a trip can approve a notification but the database and approvals still apply as for every proposal. |
| TA-07 | **Never about restricted trips.** The agent makes no proposal about a restricted (VIP or ministerial) trip (D-33): its travellers are handled outside the platform. | AIR-06 | M | A restricted trip impacted by an incident gives no proposal. |
| TA-08 | **One proposal per change.** Proposals are idempotent per trip or flight and cause (same status, same incident, same level → one proposal); evidence names the flight events, the incident or the risk breakdown. | AGT-02 | M | Replaying an event creates nothing new. |
| TA-09 | **Shown where people look.** The Decision Queue card links to the trip (Journey) and the flight (Air); the AI Agents screen lists the agent and its policies; the kill switch stops it like the others (D-17). | AGT-07, AGT-09 | M | — |

### Not in this module
Booking, rebooking or hotel reservations by the platform (no booking integration); messages to people outside the trip's travellers; any action at level 0 or 1; proposals for restricted trips.

## 21. Data changes

**None expected.** The agent, its action policies and the "trip travellers" audience are data (seed and `audience_filter` JSON), not schema. If the plan (Prompt 33) finds one is needed, it is proposed in `docs/schema/proposed-changes.md` first.

## 22. Acceptance for the module

Playwright on the real stack: in NBO-AIR-DIVERSION, XW 451 holding gives a NOTIFY_TRAVELLERS proposal; the Travel Desk approves it and a campaign to the 3 travellers is sent (simulated); the diversion adds an ADVISE_REBOOKING card; during the France scenario a seeded approved Paris trip gets a CANCEL_TRIP proposal that the Security Officer approves and the trip is CANCELLED; nothing is proposed about the restricted trip; the kill switch stops new proposals; the audit chain verifies; `make acceptance` (all four existing specs) still passes.

## 23. Questions answered by the product owner (2026-10-27: "use the defaults")

1. **Agent level:** 2, so every action needs a person; nothing runs on its own.
2. **Who approves notifying travellers:** `TRAVEL_DESK|SECURITY_OFFICER`.
3. **Who approves cancelling a trip:** `SECURITY_OFFICER`, one step.
4. **Delay that triggers a proposal:** 60 minutes (30 minutes is only flagged, AT-03).
5. **Restricted trips:** the agent never proposes anything about them.
6. **Rebooking and hotels:** advice only (level 4), since the pilot has no booking integration.
7. **Decision deadline:** 60 minutes, then the proposal expires (AGT-06).

---

# Pilot module 6 · Weather (approved 2026-10-30, PR #43)

For the product owner, who approves this part; then for the coding agent (Prompts 38–42 in `docs/prompts-pilot.md`). Rules: D-30 as amended by **D-35**. Everything runs on **simulated weather**: no weather provider is called (AGENTS.md: no external URLs at runtime). A real provider later replaces only the simulated feed.

## 24. Purpose and starting point

Two things: an **overview of current conditions** where our people are, and **severe-weather warnings** that the platform acts on like any other threat. This brings forward a slice of the master spec's Natural Hazards & Climate module (HAZ, Phase 3: HAZ-02 "arm severe-weather playbooks ahead of landfall") and the PB-06 "severe weather" playbook (PB-06 initial library).

| Exists today | Where |
|---|---|
| An **xWeather** intel source (simulated), mapping provider categories `Flood` → `FLOOD` and `Storm` → `STORM` | seed, D-09 |
| Signals → fused incidents → exposure → agents and playbooks → notifications and check-in | Phase 1 |
| Incidents count for their mission's country risk; the Travel & Air agent reacts to incidents | JR-03 (G-1), D-34 |
| Fusion within 3 km and a 5 km default impact radius: right for a protest, too small for a storm | `intel/fusion.py`, `incident.impact_radius_m` |
| Nothing for current conditions, no weather playbook, no weather scenario | — |

## 25. Requirements: Weather (WX)

| ID | Requirement | Master | Pri. | Acceptance |
|---|---|---|---|---|
| WX-01 | **Current conditions per mission city**: temperature, condition (clear, cloud, rain, storm, dust, fog, snow), wind and gusts, rainfall, and when observed. Labelled "xWeather (simulated)" (D-19). | HAZ-01 | M | Every mission shows conditions no older than 30 minutes. |
| WX-02 | **Shown where people look**: a weather panel on Global Operations (worst conditions first), a weather layer on the map (an icon per mission), and the conditions in the mission popup. | HAZ-01, OPS-01 | M | — |
| WX-03 | **Severe-weather warnings are intelligence.** The simulated xWeather feed sends warnings (storm, flood, dust storm, extreme heat) as signals; they become incidents through the existing pipeline, with exposure, agents and playbooks as for any incident. | HAZ-01, INT | M | A storm warning near Manila gives one STORM incident with people and sites exposed. |
| WX-04 | **The right size for weather.** A weather incident's impact radius and fusion distance follow its category (§28 Q4), not the 3 km / 5 km used for unrest. | HAZ-01 | M | A storm 40 km from Manila exposes the Manila mission. |
| WX-05 | **Severe-weather playbook (PB-06).** The Response Planner proposes PB-06 for a HIGH or CRITICAL storm or flood near a mission: staff alert, safety check-in, and a citizen advisory from a per-mission template (D-31: a second person approves citizen messages). | HAZ-02, PB-06 | M | The Manila storm gives a pending PB-06 proposal. |
| WX-06 | **Weather and travel.** A weather incident raises its country's destination risk and makes trips "impacted" like any incident; the Travel & Air agent reacts as it does today (D-34). | JRN-04, JRN-05 | S | A trip to Manila during the storm shows "Impacted". |
| WX-07 | **A demo scenario** `MNL-TROPICAL-STORM`: conditions in Manila worsen over the scenes (wind, rain), then xWeather warnings arrive and the platform responds. | PLT-06 | M | Played from the presenter bar. |
| WX-08 | **Simulated feed with the seams of a real one.** A simulated weather feed in the worker updates conditions for every mission on a slow, plausible daily cycle; scenarios override a city's conditions. A real provider later replaces only the feed. | HAZ-01 | M | — |

### Not in this module
Forecasts and long-term climate exposure (HAZ-03..), earthquakes and other seismic events, air quality, any real weather provider, and weather on flight routes (Air Travel uses its own simulated feed).

## 26. Data changes (proposed in `docs/schema/proposed-changes.md`)

- **PC-20 · `weather_current`**: one row per mission (tenant, mission, observed time, temperature, condition, wind, gusts, rainfall, source), FORCE RLS; written by the simulated feed as `nexira_api`, read by every role. Warnings need no schema change: they are signals and incidents.

## 27. Acceptance for the module

Playwright on the real stack: Global Operations shows current conditions for the missions, labelled simulated; in `MNL-TROPICAL-STORM`, Manila's conditions turn stormy, an xWeather storm warning becomes a STORM incident that exposes the Manila mission (larger radius, WX-04), the Response Planner proposes PB-06, and a Duty Officer approves it; a seeded trip to Manila shows as impacted; the audit chain verifies; `make acceptance` (all existing specs) still passes.

## 28. Questions answered by the product owner (2026-10-30: "use the defaults")

1. **Which places:** every mission city (36).
2. **How fresh:** conditions updated every 15 minutes by the simulated feed; anything older than 30 minutes is shown as stale.
3. **Warning categories:** STORM, FLOOD, DUST_STORM and EXTREME_HEAT (the two existing xWeather categories plus two).
4. **Size of a weather incident:** impact radius STORM 60 km, FLOOD 25 km, DUST_STORM 40 km, EXTREME_HEAT 30 km; signals fuse within the same distance. Unrest keeps 3 km / 5 km.
5. **Weather and travel risk:** yes, a weather incident raises its country's risk and triggers the Travel & Air agent, like any incident.
6. **PB-06:** proposed for HIGH or CRITICAL STORM or FLOOD within the radius of a mission; steps: staff alert, safety check-in, citizen advisory (second person).
7. **Demo scenario:** a tropical storm approaching Manila (MNL), with one seeded staff trip to Manila.
