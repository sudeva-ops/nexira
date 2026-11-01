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
| Assistance Partners (AST-01..04) | **Written: §29 (approved, built: Prompts 43–47)** | — |
| Weather (WX), D-35 | **Written: §24 (approved, built: Prompts 38–42)** | — |
| Document Expiry (DX) | **Written: §34 (approved)** | — |

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

---

# Pilot module 5 · Assistance Partners (approved 2026-10-30, PR #49)

For the product owner, who approves this part; then for the coding agent (Prompts 43–47 in `docs/prompts-pilot.md`). Rules: D-30, and **D-36**. The pilot customer has asked for this module (D-30 row 5). Everything runs on **simulated partners**: no partner system, email or phone is contacted (AGENTS.md: no external URLs at runtime, channels simulated). A real partner integration later replaces only the simulated partner adapter.

## 29. Purpose and starting point

Know which contracted partners (medical, evacuation, secure transport, welfare, relocation) can help where, ask one for help in a few clicks, and follow the request until it is done. When someone answers a safety check-in with HELP, suggest the nearest partner that can help. Master spec §5.14, AST-01..04.

| Exists today | Where |
|---|---|
| PB-07 step 6 "Place assistance partner on standby" (PARTNER_REQUEST): writes "Kestrel Medical Assistance placed on standby (simulated)" to the run's timeline; nothing is stored or tracked | `playbooks/engine.py`, seed |
| Safety check-in answers SAFE or NEED_HELP; a NEED_HELP is escalated to the duty team | `checkin/service.py`, D-14 |
| People's current locations with a confidence; missions and their countries | Location engine, `mission` |
| No partner directory, no requests, no partner screen | — |

## 30. Requirements: Assistance Partners (AS)

| ID | Requirement | Master | Pri. | Acceptance |
|---|---|---|---|---|
| AS-01 | **Partner directory.** Contracted partners with their services (MEDICAL, EVACUATION, SECURE_TRANSPORT, WELFARE, RELOCATION), coverage (countries), response time (SLA, minutes) and hours. Fictional partners, labelled simulated (D-19). Every role reads it. | AST-01 | M | The screen lists the five seeded partners with services, coverage and SLA. |
| AS-02 | **Request support.** A Duty Officer or Security Officer (or a Head of Mission for their own mission) asks a partner for one service, for a mission, optionally about an incident and a person, with a short note. Refused if the partner does not offer that service or does not cover the mission's country. | AST-02 | M | A request is created and shows as REQUESTED. |
| AS-03 | **Track it.** Status REQUESTED → ACCEPTED (with an ETA) → EN_ROUTE → COMPLETED; or DECLINED by the partner, or CANCELLED by us before completion. Forward only. Every change is timestamped, audited and pushed to browsers. | AST-02 | M | The request moves to ACCEPTED with an ETA, then EN_ROUTE, without a reload. |
| AS-04 | **Simulated partners.** A simulated partner adapter in the worker answers like a partner would: it accepts within its SLA (scaled down for the demo), sets an ETA and goes en route; a person marks the request COMPLETED. A real integration later replaces only the adapter. | — | M | — |
| AS-05 | **Playbooks use it.** A PARTNER_REQUEST step creates a real request (PB-07 step 6: Kestrel Medical, MEDICAL, standby for the incident's mission), tracked like any other. | AST-02 | M | After PB-07 runs, the Nairobi standby request is on the screen. |
| AS-06 | **Suggest a partner for an SOS.** When a person answers a check-in with NEED_HELP, the platform suggests the nearest capable partner: covering the person's location's country, for the service the duty team picks (default SECURE_TRANSPORT for staff in the zone), shortest SLA first. A person decides; nothing is requested automatically. | AST-03 | S | Peter Mwangi's HELP shows "Suggested: Sentinel Secure Transport"; one click creates the request. |
| AS-07 | **Coverage gaps.** Per mission and service, whether an active partner covers the mission's country; missions without a service are flagged. | AST-04 | S | The screen shows "34 / 36 missions covered" and names the gaps. |
| AS-08 | **Share the minimum.** A request carries the person's name and role, the place label and approximate location, the service and the note; no health details, no other personal data. Restricted (VIP) trips' travellers cannot be the subject of a request in the pilot. | — | M | — |

### Not in this module
Contracts, invoices and costs; partner portals or logins; real partner APIs, email or phone; automatic requests by an agent; medical records.

## 31. Data changes (proposed in `docs/schema/proposed-changes.md`)

- **PC-21 · `partner`**: tenant, code, name, services, coverage (country codes), SLA minutes, hours, active; FORCE RLS; seeded through the service layer; read by every role.
- **PC-22 · `partner_request`**: tenant, reference (REQ-…), partner, service, mission, optional incident and person, place label and location, note, status, ETA, who asked (user or playbook run), timestamps; FORCE RLS; no DELETE; a guard trigger for forward-only status, same-tenant references, and a partner that offers the service and covers the mission's country.

## 32. Acceptance for the module

Playwright on the real stack: the Assistance Partners screen lists the five partners and the coverage (labelled simulated); in NBO-CIVIL-UNREST, approving PB-07 creates the Kestrel standby request, which the simulated partner accepts; Peter Mwangi's NEED_HELP shows a suggested partner, a Duty Officer requests secure transport, it goes ACCEPTED then EN_ROUTE live, and the Duty Officer marks it COMPLETED; a Viewer cannot request; the audit chain verifies; `make acceptance` (all existing specs) still passes.

## 33. Questions answered by the product owner (2026-10-30: "use the defaults")

1. **Partners:** the design's five fictional partners: Kestrel Medical Assistance (MEDICAL), Atlas Air Evacuation (EVACUATION), Sentinel Secure Transport (SECURE_TRANSPORT), Harbor Crisis Support (WELFARE), Meridian Relocation (RELOCATION, SECURE_TRANSPORT), with coverage chosen so that 34 of 36 missions are fully covered and two show gaps.
2. **Who can request:** DUTY_OFFICER and SECURITY_OFFICER for any mission; HEAD_OF_MISSION for their own mission (D-05). Viewers and others read only.
3. **Second person:** none. A request is operational, not a public message; it is sent by the person who raises it and audited. Agents never request (they may only suggest in a later module).
4. **Simulated partner timing:** accepts 5–15 seconds after the request, sets the ETA from its SLA, goes en route 10 seconds later; a person marks it completed. About 1 in 10 ad-hoc requests is declined, never in the demo scenario.
5. **PB-07 step 6:** creates a tracked MEDICAL standby request to Kestrel for the incident's mission. The Phase 1 figures (D-23) do not change.
6. **SOS suggestion:** shown on Safety Check-in next to each NEED_HELP and on the partner screen; nearest capable partner by coverage, then SLA; a person clicks to request. No agent in the pilot.
7. **What a partner sees:** as AS-08; restricted travellers excluded.
8. **Demo:** in NBO-CIVIL-UNREST scene 4, Peter Mwangi's HELP leads to a Sentinel secure-transport request (as in the design); no new scenario.

---

# Pilot module 7 · Document Expiry (approved 2026-10-30, PR #57)

For the product owner, who approves this part; then for the coding agent (Prompts 48–52 in `docs/prompts-pilot.md`). Rules: D-30, and **D-37**. Everything runs on **simulated documents** from the simulator seed: no HR, passport or visa system is contacted, and no real document data is stored.

## 34. Purpose and starting point

Know whose passports, visas, accreditations and clearances are about to expire, start renewals in time, and see whether a mission's people could leave at short notice. When a mission's risk rises and someone's travel document would block an evacuation, an agent proposes urgent renewal and reminders; a person decides. This is the design's Document Expiry screen ("Compliance · Passports, visas & clearances") and its proactive proposal.

| Exists today | Where |
|---|---|
| People with a type (DIPLOMAT, LOCAL_STAFF, DEPENDANT, CONTRACTOR, DELEGATE, CITIZEN), a mission, a phone and an email | `person` |
| Staff campaigns through the notification service, with simulated channels; an `audience_filter` that can name people (the "trip travellers" audience, TA-05) | Mass Notification, D-31 |
| Mission risk (display risk) and active incidents | intel, D-08 |
| Trips with travellers, approval and a pre-travel checklist | Journey Management, PC-15 |
| The agent framework: proposals, policies, levels, approvals, executors | D-12 to D-17 |
| No documents, no expiry, no renewal, no Document Expiry screen | — |

## 35. Requirements: Document Expiry (DX)

| ID | Requirement | Pri. | Acceptance |
|---|---|---|---|
| DX-01 | **Document register.** For each staff member and dependant (DIPLOMAT, LOCAL_STAFF, DEPENDANT, CONTRACTOR), their travel and status documents: type (PASSPORT, DIPLOMATIC_PASSPORT, VISA, RESIDENCE_PERMIT, ACCREDITATION, SECURITY_CLEARANCE), issuing country and valid-until date. **No document numbers, scans or photos** are stored. Simulated, labelled so (D-19). | M | The screen lists the seeded documents with type, holder, mission and days left. |
| DX-02 | **Urgency.** From days left (UTC date): EXPIRED (< 0), CRITICAL (< 30), HIGH (< 90), MODERATE (a passport with < 180 days, the six-month rule), OK otherwise. Sorted most urgent first. | M | Hana Takeda's diplomatic passport (21 days) shows CRITICAL. |
| DX-03 | **Evacuation readiness.** A person is travel-ready when they hold a passport or diplomatic passport valid for at least 180 more days. Per mission and overall: the share of people who are travel-ready. A document is flagged **"Could block evacuation"** when its holder is not travel-ready and their mission's risk is HIGH or CRITICAL, or the mission has an active incident. | M | In NBO-CIVIL-UNREST, the two Nairobi passports are flagged; the KPI shows the share travel-ready. |
| DX-04 | **Renewal tracking.** A document's renewal goes NONE → REQUESTED → IN_PROGRESS → RENEWED (a new valid-until date, later than the old one, is entered). Forward only; each step names who did it and when; audited; pushed to browsers. | M | A Consular Officer starts a renewal; the row shows "Renewal in progress". |
| DX-05 | **Renewal reminders.** Select expiring documents and send a reminder to their holders as a staff campaign through the notification service (a new "document holders" audience in `audience_filter`, as TA-05). Never to citizens. A dependant's reminder goes to the dependant's own contact in the seed. | M | "Send renewal reminders" queues one staff campaign; the funnel shows deliveries (simulated). |
| DX-06 | **Trips warn.** When a trip's traveller has no passport valid for 180 days after the trip ends, the trip shows a warning, and the pre-travel checklist names it. It does not block approval. | S | A Paris trip with such a traveller shows the warning. |
| DX-07 | **Compliance agent (proactive).** When a mission's risk is HIGH or CRITICAL, or it has an active incident, and documents there would block evacuation, the agent proposes "Start urgent renewal and send reminders" for those documents, with evidence (days left, the six-month rule, the mission's risk) and an alternative ("Issue emergency travel documents only if needed", advice only). Level **Approve**; a Consular Officer or Duty Officer decides. Executing starts the renewals and sends the reminders through the same services people use. One open proposal per mission. | S | In NBO-CIVIL-UNREST, the proposal appears in the Decision Queue; approving it starts two renewals and sends reminders. |
| DX-08 | **Document Expiry screen.** KPIs from data: documents tracked, expiring in < 30 days, expiring in < 90 days (and how many are in renewal), evacuation-ready %. A table of expiring documents (holder, mission, document, days left, urgency, impact, renewal), filters by mission, type and urgency, and actions shown from `GET /api/me/permissions`. Blueprint dark, as the design. | M | — |
| DX-09 | **Who sees what.** DUTY_OFFICER, SECURITY_OFFICER, CONSULAR_OFFICER, HQ_CRISIS_DIRECTOR, TRAVEL_DESK and ADMIN see all; HEAD_OF_MISSION sees their own mission (D-05). VIEWER sees the KPIs only, no names. Renewals and reminders: CONSULAR_OFFICER and DUTY_OFFICER for any mission, HEAD_OF_MISSION for their own. | M | A Viewer gets KPIs and no list; a Head of Mission sees only their mission. |

### Not in this module
Document numbers, scans or photos; real HR, passport-office or visa systems; visa requirements by destination; issuing emergency travel documents; citizens' documents (consular work, a later module); costs.

## 36. Data changes (proposed in `docs/schema/proposed-changes.md`)

- **PC-23 · `travel_document`**: tenant, person, type, issuing country, valid-until date, renewal status, who and when for each renewal step, timestamps. FORCE RLS; SELECT and INSERT for `nexira_app`, and UPDATE only of the renewal columns and `valid_until`; no DELETE. A guard trigger: forward-only renewal; `valid_until` changes only on RENEWED and only to a later date; same-tenant person; the holder is not a CITIZEN or DELEGATE; step timestamps written by the database.
- The Compliance agent, its action policy (START_DOCUMENT_RENEWAL at level 2, approvers CONSULAR_OFFICER or DUTY_OFFICER) and the "document holders" audience are data (seed and `audience_filter`), not schema.

## 37. Acceptance for the module

Playwright on the real stack: the Document Expiry screen shows the seeded documents and KPIs, labelled simulated; Hana Takeda's diplomatic passport is CRITICAL. In NBO-CIVIL-UNREST, the two Nairobi documents are flagged "Could block evacuation" and the Compliance agent's proposal appears; a Consular Officer approves it; the two renewals show "in progress" and the reminders campaign is delivered (simulated); a Viewer sees KPIs and no names; the Head of Mission for another mission sees none of Nairobi's documents; the audit chain verifies; `make acceptance` (all existing specs) still passes.

## 38. Questions answered by the product owner (2026-10-30: "use the defaults")

1. **Seed:** about 1 to 3 documents for each staff member and dependant across the 36 missions (passport or diplomatic passport for everyone, plus visas, residence permits and accreditations where they apply), with expiry dates spread so that about 6 expire within 30 days and about 30 within 90 days, as the design shows. In Nairobi: **Hana Takeda's diplomatic passport (21 days)** and **her dependant child's passport (12 days)**, both fictional.
2. **Who renews and reminds:** CONSULAR_OFFICER and DUTY_OFFICER for any mission; HEAD_OF_MISSION for their own (D-05). No second person: reminders are staff-only (MN-05).
3. **The six-month rule:** a passport needs at least 180 days left to count as travel-ready, for every destination (no per-country visa rules in the pilot).
4. **The agent:** a new **Compliance agent** (rule-based, no model), proposing at level Approve. It cannot be set to Auto (the policy floor is 2). Agents never renew or remind without a person's approval.
5. **No document numbers** are stored, not even in part.
6. **Trips:** warn, do not block (DX-06).
7. **Demo:** in NBO-CIVIL-UNREST, after scene 3 the Compliance agent's proposal appears; no new scenario.
8. **🔒 prompts:** the migration (RLS and grants) and the agent policy (D-29) need your named sign-off, as before.

---

# Pilot module 8 · Natural Hazards & Climate (approved 2026-10-31, PR #63)

For the product owner, who approves this part; then for the coding agent (Prompts 53–58 in `docs/prompts-pilot.md`). Rules: D-30, and **D-38**. Everything runs on **simulated hazard feeds** and **illustrative climate scores**: no seismic, weather, air-quality or climate provider is called (AGENTS.md: no external URLs at runtime). A real provider later replaces only the simulated feed.

## 39. Purpose and starting point

The rest of the master spec's Natural Hazards & Climate module (HAZ-01..03), on top of Weather (D-35): **live hazard events** near our missions (earthquakes, tropical cyclones, floods, extreme heat, air quality, wildfire), **arming a playbook ahead of a forecast landfall**, and **long-term climate exposure** per mission for site and continuity planning. This is the design's Natural Hazards & Climate screen ("Hazards · Live events & long-term site exposure") and its proactive Dhaka cyclone proposal.

| Exists today | Where |
|---|---|
| Severe-weather warnings (STORM, FLOOD, DUST_STORM, EXTREME_HEAT) from the simulated xWeather feed become incidents, sized by category | Weather, WX-03, WX-04 |
| Signals → fused incidents → exposure → agents and playbooks → notifications and check-in | Phase 1 |
| PB-06 Severe weather (staff alert, check-in, citizen advisory with a second person), proposed by the Response Planner | WX-05 |
| Playbook runs start when someone starts them or approves a proposal; there is no way to start one **later**, at a set time | playbooks |
| No earthquakes, cyclone forecasts, air quality or wildfire; no climate exposure; no hazards screen | — |

## 40. Requirements: Natural Hazards (HZ)

| ID | Requirement | Master | Pri. | Acceptance |
|---|---|---|---|---|
| HZ-01 | **More hazard types as intelligence.** Simulated feeds send EARTHQUAKE (magnitude, depth), TROPICAL_CYCLONE (category, expected landfall time), WILDFIRE and AIR_QUALITY (AQI) signals, alongside Weather's FLOOD and EXTREME_HEAT. They become incidents through the existing pipeline, with exposure, agents and playbooks as for any incident. Each is labelled with its simulated source. | HAZ-01 | M | An M5.2 earthquake 210 km from Ankara gives one EARTHQUAKE incident, LOW. |
| HZ-02 | **Severity and size by hazard** (§43 Q3): severity from magnitude, cyclone category, AQI or temperature; impact radius and fusion distance per type (an earthquake's from its magnitude). | HAZ-01 | M | A Category 2 cyclone forecast for Dhaka is HIGH and exposes the Dhaka mission. |
| HZ-03 | **Within range of a mission.** For each event: the nearest mission and its distance, whether it is exposed (inside the impact radius), and what is exposed (staff, homes, sites) from the existing exposure. Events more than 300 km from every mission are shown as "No mission within 300 km". | HAZ-01 | M | The Jakarta flood shows "Jakarta mission · 2 staff homes". |
| HZ-04 | **Forecasts count down.** A cyclone forecast shows its expected landfall time and "landfall in N h"; a newer forecast updates it. | HAZ-02 | M | Dhaka shows "landfall in 60 h". |
| HZ-05 | **Arm a playbook ahead of landfall.** A person, or an approved proposal, can **arm** a playbook for an incident: it starts automatically at a set time (e.g. 36 h before landfall), and until then it can be started now or disarmed. Arming, starting and disarming are audited; the run then works as any playbook run (gates, second person for citizens). | HAZ-02 | M | PB-06 armed for Dhaka starts by itself at the set time. |
| HZ-06 | **The Response Planner proposes arming.** For a HIGH or CRITICAL cyclone forecast whose landfall is more than 36 h away and whose radius covers a mission, it proposes "Arm PB-06 for <city>, start 36 h before landfall", with evidence (track distance, people and homes exposed) and the alternative "Monitor only; reassess in 12 h" (advice only). Level **Approve**; a Security Officer or Duty Officer decides. One open proposal per incident. | HAZ-02 | M | In DAC-CYCLONE the proposal appears; approving it arms PB-06. |
| HZ-07 | **Earthquake playbook (PB-01).** The Response Planner proposes PB-01 for a HIGH or CRITICAL earthquake whose radius covers a mission: safety check-in first, then a staff alert, then a citizen advisory from the mission template (D-31: a second person approves it). | PB-01 | S | — |
| HZ-08 | **Long-term climate exposure.** Per mission: its main hazards and an illustrative risk score (0–100) today and in 2050, labelled "Illustrative climate model (simulated)". Read-only reference data, sorted by the 2050 score. | HAZ-03 | S | Jakarta has the highest 2050 score. |
| HZ-09 | **Natural Hazards & Climate screen.** KPIs from data: active hazard events, missions exposed now (by level), the mission with the highest 2050 score, and the number of sources. Live hazard events with tabs per type (type, event, area, mission exposure, level, updated); a banner for a forecast that can still be armed, with "Arm playbook" shown from `GET /api/me/permissions`; the climate table. Hazard events on the Global Operations map with their own icon. Blueprint dark, as the design. | HAZ-01..03 | M | — |
| HZ-10 | **Who sees what.** Every role, Viewer included, sees hazard events, exposure counts and climate scores (no names; names stay on People & Sites). Arming, starting an armed run and disarming: SECURITY_OFFICER and DUTY_OFFICER, unscoped or for the incident's mission, exactly as starting a playbook (plan-pilot-hz G-1, approved 2026-10-31). | — | M | A Viewer sees the screen with no "Arm playbook" button. |
| HZ-11 | **A demo scenario** `DAC-CYCLONE`: scene 1 brings the background events (Ankara earthquake, Jakarta flood, Riyadh heat, New Delhi air quality, a wildfire with no mission in range) and a Category 1 forecast for Dhaka; scene 2 upgrades it to Category 2, landfall in 60 h; later scenes bring it to 36 h (the armed playbook starts), landfall, and weakening. | PLT-06 | M | Played from the presenter bar. |

### Not in this module
Real hazard, weather, seismic, air-quality or climate providers; tsunami and volcano warnings; pre-positioning supplies, fuel or vehicles (Supply Chain and Fleet, later modules); business-continuity plans (BCP); climate scenarios other than one illustrative 2050 score; using climate scores in decisions (they are shown, not acted on).

## 41. Data changes (proposed in `docs/schema/proposed-changes.md`)

- **PC-24 · Armed playbook runs**: `playbook_run` gains `scheduled_for timestamptz` (nullable) and the statuses `SCHEDULED` and `DISARMED`. A guard: a SCHEDULED run has `scheduled_for` in the future when created; it may only move to RUNNING or DISARMED; a DISARMED run is final. Grants unchanged.
- **PC-25 · `mission_climate_risk`**: tenant, mission (one row each), main hazards (`text[]`), score today and 2050 (0–100), scenario label, source. FORCE RLS with `tenant_isolation`; SELECT and INSERT for `nexira_app` (seeded through the service layer); no UPDATE or DELETE in the pilot.
- Hazard events need no table: they are signals and incidents. Their details (magnitude, category, AQI, landfall time) come from the incident's latest signal payload.

## 42. Acceptance for the module

Playwright on the real stack: the Natural Hazards screen shows the hazard events and climate exposure, labelled simulated. In `DAC-CYCLONE`, the background events appear, with the Ankara earthquake LOW and outside its range; the Dhaka forecast becomes a HIGH TROPICAL_CYCLONE incident (CRITICAL with the D-11 raise, as the chancery is in its zone; plan-pilot-hz G-13) showing "landfall in 60 h" and exposing the Dhaka mission; the Response Planner proposes arming PB-06; a Security Officer approves it; the playbook shows as armed and starts by itself when the scenario reaches 36 h; a Viewer sees events and scores with no names and no "Arm playbook"; the audit chain verifies; `make acceptance` (all existing specs) still passes.

## 43. Questions answered by the product owner (2026-10-31: "use the defaults")

1. **Hazard types:** EARTHQUAKE, TROPICAL_CYCLONE, WILDFIRE and AIR_QUALITY are new; FLOOD and EXTREME_HEAT stay as Weather made them. Four simulated sources, as the design: xWeather (cyclone, flood, heat, wildfire), a seismic network, an air-quality network, and the illustrative climate model.
2. **Range:** an event is listed with its nearest mission; it "exposes" a mission only inside its impact radius. Beyond 300 km of every mission: "No mission within 300 km".
3. **Severity and size:**
   - EARTHQUAKE: M < 5.5 LOW, 5.5–6.4 MODERATE, 6.5–7.4 HIGH, ≥ 7.5 CRITICAL. Radius 50 km below M5, 100 km for M5–5.9, 200 km for M6–6.9, 400 km from M7.
   - TROPICAL_CYCLONE: Category 1 MODERATE, 2 HIGH, 3 or more CRITICAL. Radius 150 km around the forecast landfall point.
   - AIR_QUALITY: AQI 201–300 MODERATE, 301–400 HIGH, over 400 CRITICAL. Radius 30 km.
   - WILDFIRE: MODERATE, or HIGH within 20 km of a mission. Radius 20 km.
4. **Arming:** the default start time is 36 h before landfall. A person can start the run now or disarm it until then. A newer forecast does not move the time by itself; the incident shows "forecast changed" instead.
5. **Who arms:** SECURITY_OFFICER and DUTY_OFFICER, as starting a playbook (`START_ROLES`; plan-pilot-hz G-1, approved 2026-10-31: a Head of Mission does not arm, since they cannot start a playbook). The Response Planner's arming proposal needs SECURITY_OFFICER or DUTY_OFFICER, with a policy floor of 2, so it can never be set to Auto.
6. **PB-01 Earthquake:** a new seeded playbook: safety check-in, staff alert, citizen advisory (second person). Proposed for HIGH or CRITICAL earthquakes.
7. **Climate scores:** illustrative and fictional, for all 36 missions. The design's figures for Jakarta, Dhaka, New Delhi, Riyadh, Manila, Nairobi and London; plausible ones for the rest.
8. **Demo:** a new scenario `DAC-CYCLONE`. The background events come with its scene 1 rather than with `make reset-demo`, so the Phase 1 scenario still starts with no active incidents. Dhaka keeps its 15 seeded staff. Three of their homes are placed in flood-prone wards, as the design. No new people are added, so the seeded totals stay as they are.
9. **Screen:** "Natural Hazards & Climate" under MONITOR, as the design.
10. **🔒 prompts:** the migration (PC-24 changes playbook-run rules; PC-25 adds RLS and grants), the arming action's executor and its policy (D-29) need your named sign-off, as before.

---

# Pilot module 9 · Health Intelligence (approved 2026-10-31, PR #70)

For the product owner, who approves this part; then for the coding agent (Prompts 59–64 in `docs/prompts-pilot.md`). Rules: D-30, and **D-39**. Everything runs on **simulated health advisories, sample medical facilities and illustrative entry requirements**: no WHO, ministry or health-intelligence provider is called (AGENTS.md: no external URLs at runtime). A real feed later replaces only the simulated feed, after its terms of use are checked (master HLT-05).

## 44. Purpose and starting point

Know which disease outbreaks and health advisories affect the countries where we have missions and travellers, which vetted hospitals are near each mission (and which to avoid because they are inside an incident's impact zone), what each destination requires for entry, and how ready each mission's staff are. Then send a health advisory in a few clicks. Master spec §5.22, HLT-01..05; the design's Health Intelligence screen ("Health · WHO advisories, outbreaks & medical facilities") and its proactive cholera proposal.

| Exists today | Where |
|---|---|
| Missions and their countries; people and their locations; trips with a destination country | `mission`, location engine, Journey Management |
| Active incidents with an impact radius (PostGIS) | intel, exposure |
| Mass Notification campaigns from per-mission templates; a second person for citizens (D-31) | notifications |
| The Communications agent proposes citizen advisories (SEND_EXTERNAL_MESSAGE), approved by a person | agents |
| Kestrel Medical Assistance, a simulated MEDICAL partner | Assistance Partners (D-36) |
| No health advisories, medical facilities, entry requirements or health readiness; no health screen | — |

## 45. Requirements: Health Intelligence (HL)

| ID | Requirement | Master | Pri. | Acceptance |
|---|---|---|---|---|
| HL-01 | **Outbreak and health advisories.** A simulated feed publishes advisories ("WHO Disease Outbreak News (simulated)", a ministry bulletin, the medical partner): disease or topic, countries and a region label, level (LOW, MODERATE, HIGH, CRITICAL), published and updated times, and guidance for staff. A newer bulletin for the same advisory updates it; an advisory can be closed. Advisories are **country-level reference intelligence, not incidents** (§48 Q1). | HLT-01 | M | The screen lists the six seeded advisories, labelled simulated. |
| HL-02 | **Which missions are affected.** An advisory affects every mission in its countries. Each mission shows its highest open advisory level. | HLT-01 | M | Cholera in Kenya shows "Affects Nairobi mission". |
| HL-03 | **Entry and vaccination requirements by country.** Per country: mandatory requirements and recommended vaccinations (illustrative, labelled simulated). Shown for every mission country and, on the trip, for its destination. | HLT-02 | M | Kenya shows "Yellow fever certificate if arriving from risk country". |
| HL-04 | **Medical facilities near each mission.** Sample facilities (fictional names, "(sample)") with location, capabilities (emergency, trauma level, ICU, surgery, helipad, pharmacy), 24/7 or not, and vetted by a partner. Listed by distance from the mission. A facility inside the impact radius of an ACTIVE incident is flagged **Avoid · inside impact zone**, computed by PostGIS, never stored. | HLT-03 | M | In NBO-CIVIL-UNREST, Nairobi Central Medical Centre shows "Avoid" while INC-…-1042 is ACTIVE. |
| HL-05 | **Staff health readiness, counts only.** Per mission: staff count; blood type on file; medical insurance active; vaccines offered for the open advisories; trauma kits at the mission. **Counts only, no person-level health data** is stored or shown (§48 Q4). | HLT-04 | M | Nairobi shows "Cholera vaccine offered 9 / 14" (its 14 staff; plan-pilot-hl G-4). |
| HL-06 | **Send a health advisory.** From an advisory and a mission, anyone who may compose a Mass Notification campaign (DUTY_OFFICER, SECURITY_OFFICER, CONSULAR_OFFICER) creates a Mass Notification campaign from the mission's HEALTH_ADVISORY template. It then follows D-31: DRAFT, then sent, with a second person when citizens are in the audience. | HLT-04 | M | "Send health advisory to Nairobi" opens a draft for staff and citizens. |
| HL-07 | **The Communications agent proposes it.** When an advisory becomes HIGH or CRITICAL for a mission's country, the agent proposes "Health advisory recommended for <city> staff and citizens", with evidence (advisory, level, vaccines offered) and the template text. Level **Approve**; a Duty Officer or Consular Officer decides; approving creates the campaign, which still needs its second person. One open proposal per advisory and mission. | — | M | In NBO-CHOLERA the proposal appears; approving it creates the draft campaign. |
| HL-08 | **Health Intelligence screen.** KPIs from data: open advisories (and how many affect mission countries), missions with an advisory (by level), staff vaccinations due (offered, not yet given, counts), and vetted facilities. The advisories table (event, location, level, published, guidance, affected missions), entry requirements, facilities and readiness for a chosen mission (default: the most affected), and the send button from `GET /api/me/permissions`. Blueprint dark, as the design, under MONITOR. | — | M | — |
| HL-09 | **Who sees what.** Every role, Viewer included, reads advisories, requirements, facilities and readiness counts. Sending as in HL-06. | — | M | A Viewer sees the screen with no send button. |
| HL-10 | **A demo scenario** `NBO-CHOLERA`: scene 1 raises the seeded Kenya cholera advisory from MODERATE to HIGH (a newer simulated WHO bulletin); the Communications agent proposes the Nairobi advisory; scene 2 closes the dengue advisory. | — | M | Played from the presenter bar. |

### Not in this module
Real WHO, ministry or provider feeds; person-level health data of any kind (medical records, blood type, vaccination records per person); outbreak maps or case counts; health advisories raising country travel risk (they show on the trip, they do not change its risk); booking hospital appointments; any use of health data by an agent other than the counts above.

## 46. Data changes (proposed in `docs/schema/proposed-changes.md`)

- **PC-26 · `health_advisory`**: tenant, reference (`HA-<n>`), topic, topic code (plan-pilot-hl G-1), countries (`char(2)[]`), region label, level, guidance, source, status (OPEN, CLOSED), published_at, updated_at, external id (for updates from the feed). FORCE RLS; SELECT, INSERT and UPDATE of level, guidance, status and updated_at for `nexira_app`; no DELETE; a closed advisory is final.
- **PC-27 · `medical_facility`**: tenant, mission, name, location `geography(Point,4326)`, capabilities (`text[]`), trauma level, open 24/7, vetted by (partner), source. FORCE RLS; SELECT and INSERT (seeded through the service layer); no UPDATE or DELETE in the pilot.
- **PC-28 · `country_health_requirement`**: tenant, country, mandatory, recommended, source. Primary key (tenant, country). FORCE RLS; SELECT and INSERT; no UPDATE or DELETE in the pilot.
- **PC-29 · `mission_health_readiness`**: tenant, mission (primary key with the tenant), staff, blood_type_on_file, insurance_active, trauma_kits, vaccines offered (`jsonb`, `{"Cholera": 9}`), as_of. Counts only (CHECKs: 0 ≤ count ≤ staff). FORCE RLS; SELECT and INSERT; no UPDATE or DELETE in the pilot.
- The health advisory templates (kind ADVISORY, one code per topic; plan-pilot-hl G-1) and a policy row for the agent's proposal are data, not schema.

## 47. Acceptance for the module

Playwright on the real stack: the Health Intelligence screen shows the six seeded advisories, the entry requirements, Nairobi's facilities and readiness counts, labelled simulated. In NBO-CIVIL-UNREST, Nairobi Central Medical Centre is flagged "Avoid" while the incident is ACTIVE. In `NBO-CHOLERA`, the cholera advisory becomes HIGH and the Communications agent's proposal appears; a Duty Officer approves it; a draft campaign from the Nairobi health template exists, and a second person (Consular Officer) approves and sends it; deliveries are simulated. A Viewer sees the screen with no send button and no names. The audit chain verifies; `make acceptance` (all existing specs) still passes.

## 48. Questions answered by the product owner (2026-10-31: "use the defaults")

1. **Advisories are not incidents.** Outbreaks cover countries and last days or weeks; they are a reference list, not signals fused into incidents with a radius. So they start no playbooks and do not count as active incidents. *Default: yes, a separate `health_advisory` list.*
2. **Seeded advisories:** the design's six (cholera in Kenya MODERATE, dengue in Bangladesh, mpox in central Africa, avian influenza in Southeast Asia, measles in Pakistan, a heat-health warning in Delhi), fictional and simulated, present after `make reset-demo`. They are not incidents, so the Phase 1 scenario still starts with no active incident and an empty Decision Queue.
3. **Entry requirements:** illustrative, for the 36 mission countries, labelled simulated, not to be used for real travel.
4. **Health readiness:** counts per mission only, seeded (illustrative), read-only in the pilot. No person-level health data, because it is special-category personal data. Recording it would need a privacy review and a lawful basis first.
5. **Facilities:** about three sample facilities per mission city (fictional, "(sample)"); Nairobi's four as the design. "Avoid" is computed from ACTIVE incidents only.
6. **Who sends:** the Mass Notification composers (DUTY_OFFICER, SECURITY_OFFICER, CONSULAR_OFFICER), as today; a Head of Mission cannot compose campaigns, so cannot send one either. The second person for citizens as D-31. The agent's proposal: policy floor 2 (never Auto), approvers DUTY_OFFICER or CONSULAR_OFFICER.
7. **Template:** a HEALTH_ADVISORY template per mission with a generic fallback. English is reviewed; the other languages keep `REVIEW REQUIRED` (D-15, D-31).
8. **Demo:** a new scenario `NBO-CHOLERA` (§45 HL-10). No new people are added; the readiness counts are illustrative figures for each mission's seeded staff.
9. **Screen:** "Health Intelligence" under MONITOR, before Natural Hazards & Climate, as the design.
10. **🔒 prompts:** the migration (PC-26..29 add RLS and grants), the agent's proposal and its policy (D-29) need your named sign-off, as before.

---

# Pilot module 10 · Evacuation Management (approved 2026-11-01, PR #77)

For the product owner, who approves this part; then for the coding agent (Prompts 65–70 in `docs/prompts-pilot.md`). Rules: D-30, and **D-40**. Everything runs on **simulated plans, a simulated muster-point scanner and the simulated partners** (D-36): no charter operator, airline, convoy provider or scanner is contacted (AGENTS.md: no external URLs at runtime), and no real movement order is sent.

## 49. Purpose and starting point

Turn the decision to evacuate a mission into a locked manifest, a check-in at the muster point, a sequence everyone can follow (assembly, convoy, flight, arrival), and the right partners and messages, with the two-person rule kept. Master spec §5.9 (Evacuation Management, EVC-01..05); the design's Evacuation Management screen ("Response · Manifests, seats & routes") and its evacuation proposal.

| Exists today | Where |
|---|---|
| `START_EVACUATION`: level 3, Head of Mission **and** HQ Crisis Director (two-person rule, AGT-04). Its executor is a **Phase 1 stub** that only writes an incident note. Phase 1 scene 5 approves one injected by a test fixture | agents, decisions.md §7 |
| PB-07 step 7: the Head of Mission approves the evacuation route | playbooks |
| People by mission and type (diplomat, local staff, delegate, dependant, citizen); the incident's check-in (safe, need help, no reply) | people, check-in |
| Atlas Air Evacuation (EVACUATION) and Sentinel Secure Transport (SECURE_TRANSPORT), simulated partners whose requests move ACCEPTED → IN_PROGRESS → COMPLETED | Assistance Partners (D-36) |
| "Could block evacuation": a traveller whose passport is not valid long enough | Document Expiry (DX-03) |
| Mass Notification campaigns; a second person for citizens (D-31) | notifications |
| No evacuation plans, manifests, muster check-in or evacuation screen | — |

## 50. Requirements: Evacuation Management (EV)

| ID | Requirement | Master | Pri. | Acceptance |
|---|---|---|---|---|
| EV-01 | **An evacuation plan per mission.** `EVP-<mission code>`: the muster point (name and location), the approved route label, the destination (safe haven), and up to three transport options, each with a role (PRIMARY, BACKUP, CONTINGENCY), a kind (CHARTER, COMMERCIAL, ROAD), a label, seats where known, and a partner. Seeded for every mission, illustrative and labelled simulated; read-only in the pilot (§53 Q1). | EVC-01 | M | EVP-NBO: muster at the embassy courtyard; charter Wilson Airport → Dubai, 72 seats, Atlas Air Evacuation (primary); 30 held commercial seats at JKIA (backup); road via Namanga to Arusha (contingency). |
| EV-02 | **Activation keeps the two-person rule.** An evacuation is activated only when a Head of Mission (for that mission, or unscoped) **and** an HQ Crisis Director, two different people, have both approved it, through `app/core/approvals.py`. Two ways: (a) a `START_EVACUATION` proposal reaches its second approval; its executor now activates the mission's plan instead of the Phase 1 stub (it still writes the incident note); (b) on the screen, one of them presses **Activate evacuation** (the request, counted as their approval) and the other confirms. One live evacuation per mission. | EVC-02, AGT-04 | M | One approval activates nothing; the same person cannot give both; the second approval activates EVP-NBO. Phase 1 scene 5 still passes. |
| EV-03 | **The manifest is built and locked at activation.** From the mission's people: diplomats, delegates and dependants, and the citizens who have **not confirmed safe** in the incident's check-in (need help or no reply). Local staff are not added (§53 Q3). Each entry: name, category, travel-document flag (DX-03 "could block evacuation"), seat, status. Nobody is added or removed by hand in the pilot. | EVC-03 | M | After NBO-CIVIL-UNREST scenes 1–4: 16 mission (12 diplomats, 3 delegates, 1 dependant) + 44 citizens = **60**; Hana Takeda and her child Aiko flagged "Could block evacuation" (DX-03). |
| EV-04 | **Check-in at the muster point.** Each person is checked in once, by the simulated muster-point scanner or by hand (Security Officer, Consular Officer, Duty Officer, or the mission's Head of Mission), and gets the next free seat of the primary option. Status: ON STANDBY (before activation), EXPECTED, CHECKED IN. Checked-in counts update live. | EVC-03 | M | The scanner checks in all 60; seats 1A… are assigned in order; 60 of 72 seats used. |
| EV-05 | **The sequence.** Six steps, each with a time: decision to evacuate; manifest confirmed (both at activation); assembly at the muster point (when everyone on the manifest is checked in, or a person closes it); convoy departed; flight departed; arrival and reception. The last three are marked by a person with a responder role, or by the scenario's simulated progress events (plan-pilot-ev G-2); the partners' request status is shown beside them. Arrival completes the evacuation and its partner requests. | EVC-04 | M | In NBO-EVACUATION, each step turns green in order with its time. |
| EV-06 | **Partners and messages at activation.** Activation, being two people's decision, (a) requests Atlas Air Evacuation (EVACUATION) and Sentinel Secure Transport (SECURE_TRANSPORT) through the Assistance Partners service, sharing only what they need (AS-08: headcount, muster point, route, times; no names); (b) drafts the movement message to everyone on the manifest as a Mass Notification campaign from the mission's EVACUATION template, PENDING_APPROVAL. It is sent under D-31: a second person who did not activate the evacuation (plan-pilot-hl G-2, as the health advisory). | EVC-05 | M | Two partner requests exist with no names; the campaign waits for a Duty Officer or Consular Officer, and neither activator can send it. |
| EV-07 | **Stand down.** Before the flight departs, an HQ Crisis Director can stand the evacuation down, with a reason. Standing down is final; the manifest is kept for the record; the partner requests are cancelled. | — | M | Stood down: no more check-ins; the reason is in the audit log. |
| EV-08 | **Evacuation Management screen.** As the design, Blueprint dark, under RESPOND (§53 Q9): the banner (no active evacuation · plan ready, with Activate when allowed · in progress · complete); KPIs from data (evacuees on manifest by category, checked in, seats available on the primary option, documents flagged); the manifest; the sequence with times; the plan's options. A mission picker (default: the mission with a live evacuation, else one with an ACTIVE incident). Every button from `GET /api/me/permissions`. | — | M | — |
| EV-09 | **Who sees what.** Names on the manifest only for those who may read the mission's people (as People & Sites; a mission-scoped role sees only its own mission). Everyone else, Viewer included, sees counts, the sequence and the plan, and no names. | — | M | A Viewer sees "60 on manifest · 42 checked in" and no names; the Cairo Head of Mission sees none of Nairobi's names. |
| EV-10 | **A demo scenario** `NBO-EVACUATION`, after NBO-CIVIL-UNREST scene 5 (which activates EVP-NBO): scene 1 the scanner checks people in over about 30 seconds; scene 2 the convoy departs; scene 3 the charter departs; scene 4 arrival. | — | M | Played from the presenter bar. |

### Not in this module
Editing plans in the app; adding or removing people from a manifest by hand; real charter, airline or convoy bookings; tracking the charter on Air Travel; vehicles and drivers (the Fleet module); an agent proposing an evacuation by itself (§53 Q7); evacuating several missions in one operation; real movement orders or any channel other than the simulated ones.

## 51. Data changes (proposed in `docs/schema/proposed-changes.md`)

- **PC-30 · `evacuation_plan`**: tenant, mission (one plan per mission), reference (`EVP-<code>`), muster point name and location `geography(Point,4326)`, route label, destination, options (`jsonb`, at most 3, each role, kind, label, seats, partner), source. FORCE RLS; SELECT and INSERT (seeded through the service layer); no UPDATE or DELETE in the pilot.
- **PC-31 · `evacuation`**: tenant, plan, mission, incident (nullable), the proposal (nullable), status (`PENDING_ACTIVATION`, `ACTIVE`, `COMPLETED`, `STOOD_DOWN`), requested by and at, activated by and at (a different person; checked by the database too), the step (1..6) with each step's time, stand-down reason. FORCE RLS; SELECT, INSERT and UPDATE of status, activation, step and stand-down columns; no DELETE. Guard: forward-only status and step; `COMPLETED` and `STOOD_DOWN` final; activator ≠ requester; one live evacuation per mission.
- **PC-32 · `evacuation_manifest`**: tenant, evacuation, person (same tenant, same mission), category (`STAFF`, `DELEGATE`, `DEPENDANT`, `CITIZEN`), seat, status (`EXPECTED`, `CHECKED_IN`), checked in at and by (user or scanner). Unique (evacuation, person) and (evacuation, seat). FORCE RLS; SELECT, INSERT (at activation only) and UPDATE of status, seat and check-in columns; no DELETE. Guard: CHECKED_IN is final; nothing changes once the evacuation is final; no insert after activation.
- The EVACUATION message templates and the plans are data, not schema. `START_EVACUATION`'s policy row is unchanged.

## 52. Acceptance for the module

Playwright on the real stack: after NBO-CIVIL-UNREST scenes 1–4, the screen shows EVP-NBO ready, not activated, labelled simulated. The scene 5 proposal: the Nairobi Head of Mission's approval activates nothing; the HQ Crisis Director's activates EVP-NBO with a manifest of 60 (16 mission, 44 citizens) and Hana and Aiko Takeda's documents flagged; two partner requests with no names; the movement message waits for a second person, refused to both activators and sent by the Consular Officer (deliveries simulated). `NBO-EVACUATION`: all 60 checked in with seats; the sequence completes in order; the evacuation is COMPLETED. A Viewer sees counts and no names; the Cairo Head of Mission sees no Nairobi names. Every step is audited and the chain verifies; `make acceptance` (all existing specs) still passes.

## 53. Questions answered by the product owner (2026-11-01: "use the defaults")

1. **Plans:** seeded for every mission, illustrative, read-only in the pilot; EVP-NBO as the design. Editing plans (and approving a new route) comes later. *Default: yes.*
2. **Activation:** only with the two-person rule (Head of Mission + HQ Crisis Director, two different people), either from a `START_EVACUATION` proposal or the screen's Activate button. The Phase 1 stub executor is replaced by the real activation (🔒, D-29); Phase 1 scene 5 then activates EVP-NBO. *Default: yes.*
3. **Who is evacuated:** diplomats, delegates and dependants always; citizens who have not confirmed safe in the incident's check-in. Local staff are nationals and stay, as is usual (they keep their check-in and welfare follow-up). *Default: yes; Nairobi 60 = 16 + 44.*
4. **Manifest changes:** locked at activation; no adding or removing by hand in the pilot. *Default: yes.*
5. **Muster check-in:** a simulated scanner in the scenario, plus a "Check in" button for Security Officer, Consular Officer, Duty Officer and the mission's Head of Mission. Seats are the primary option's, in check-in order. *Default: yes.*
6. **Partners and the movement message:** requested and drafted at activation, because two people decided; the message still needs its D-31 second person, who is neither activator. Partners get headcount, muster point, route and times only. *Default: yes.*
7. **Agent proposal:** none in this module. The design's evacuation proposal relies on Predictive Risk and Fleet, which come later; until then the scene 5 fixture and the Activate button are the two ways. *Default: not now.*
8. **Names:** only for those who may read the mission's people; others see counts. *Default: yes.*
9. **Screen:** "Evacuation Management" under RESPOND, after Response Playbooks, as the design. *Default: yes.*
10. **Demo:** `NBO-EVACUATION` continues from NBO-CIVIL-UNREST scene 5, where two people activate EVP-NBO; the scenario itself approves nothing. If no evacuation is live, the presenter bar says to play NBO-CIVIL-UNREST to scene 5 first. *Default: yes.*
11. **🔒 prompts:** the migration (PC-30..32: RLS, grants, guards), the `START_EVACUATION` executor, the activation approvals and the partner requests (D-29) need your named sign-off, as before.

## 54. Purpose and starting point

Know which vehicles and critical equipment each mission has, where they are, whether they can be used now, and whether they can move the mission's people if it must leave. Master spec §5.20 (Fleet & Assets, FLT-01..04); the design's Fleet & Assets screen ("Assets · Vehicles, fuel & availability"), under RESPOND.

| Exists today | Where |
|---|---|
| Peter Mwangi, Nairobi driver (local staff), last seen "In transit · Haile Selassie Ave", inside INC-1042's impact zone; he answers NEED HELP in the scene 4 check-in | seed, NBO-CIVIL-UNREST |
| Incidents with a location and impact radius; "inside impact zone" tests (Health Intelligence's Avoid, HL-04) | intel, health_intel |
| Evacuation plans and live evacuations per mission; the mission part of the manifest (Nairobi: 16) | Evacuation Management (D-40) |
| Sentinel Secure Transport (SECURE_TRANSPORT), a simulated partner | Assistance Partners (D-36) |
| No vehicles, equipment, telematics, maintenance or Fleet screen | — |

## 55. Requirements: Fleet & Assets (FLT)

| ID | Requirement | Master | Pri. | Acceptance |
|---|---|---|---|---|
| FLT-01 | **An asset register per mission.** Each asset: code (`VH-nn` for vehicles, `<KIND>-<mission code>` for equipment), kind (VEHICLE or EQUIPMENT), type label (e.g. "Armoured SUV (B6)", "Minibus 14-seat", "Generator 250 kVA", "Satellite terminal"), armoured or not, passenger seats (vehicles), location (`geography(Point,4326)` and a label), fuel or charge %, the time of the last position, a stored status (AVAILABLE, IN USE, MAINTENANCE) and, for vehicles, the assigned driver. Seeded for every mission, illustrative and labelled simulated; positions and fuel come from simulated telematics (§58 Q2). | FLT-01 | M | Nairobi as the design: VH-01 armoured SUV (embassy garage, 82%), VH-02 armoured SUV (Haile Selassie Ave, 46%, driver Peter Mwangi), VH-03 minibus (garage, 90%), VH-04 pickup 4×4 (residence, 64%), VH-05 sedan (workshop, 30%, MAINTENANCE), GEN-NBO generator (72%), SAT-NBO satellite terminal (100%). |
| FLT-02 | **What a vehicle can do now** is shown from data, not stored: **MAINTENANCE** (stored); **BLOCKED · DRIVER SOS** when its driver's latest check-in answer in an ACTIVE incident is NEED HELP; **IN IMPACT ZONE** when its last position is inside an ACTIVE incident's impact zone; **ASSIGNED · EVAC** when the mission has an ACTIVE evacuation and the vehicle is otherwise available; else AVAILABLE or IN USE. A vehicle counts as available unless it is in maintenance, blocked or in an impact zone. | FLT-01, FLT-04 | M | Nairobi before scene 1: 4 of 5 available. After scene 4: VH-02 BLOCKED · DRIVER SOS and IN IMPACT ZONE; 3 of 5 available. After scene 5: VH-01, VH-03, VH-04 ASSIGNED · EVAC. |
| FLT-03 | **Evacuation capacity by road.** Per mission: passenger seats in available vehicles against the seats needed, which is the mission part of a live evacuation's manifest (staff, delegates and dependants) or, with none, the mission's diplomats, delegates and dependants. A shortfall names the nearest Assistance Partner with SECURE_TRANSPORT for the mission's country as a suggestion; nothing is requested automatically. | FLT-02, EVC-06 | M | Nairobi: 24 seats available before scene 1 and 20 after scene 4, against 16 needed: "Capacity sufficient". A mission with fewer seats shows the shortfall and Sentinel Secure Transport where it covers the country. |
| FLT-04 | **Maintenance.** Each asset has maintenance items (task, due date). Items overdue or due within 14 days are maintenance alerts. A Security Officer, a Duty Officer or the mission's Head of Mission can mark an item done (once, audited) and set a vehicle's stored status between AVAILABLE, IN USE and MAINTENANCE (audited, with a reason for MAINTENANCE). | FLT-03 | M | VH-05 "Brake service overdue"; VH-21 "Tyre replacement (run-flat)"; GEN-ISB "Load test due"; VH-11 "Armour inspection" due in 30 days is not yet an alert. Marking VH-05's brake service done removes the alert; the status change is in the audit log. |
| FLT-05 | **Geofence alert.** When a vehicle's position (from telematics) enters an ACTIVE incident's impact zone, the Fleet screen raises a live alert and the incident timeline gets a FLEET entry ("VH-04 entered the impact zone of INC-…"); leaving the zone is noted too. No agent proposes anything (§58 Q7). | FLT-04 | S | In NBO-FLEET, VH-04 enters the zone: alert and timeline entry within 5 s; it leaves: a second entry. |
| FLT-06 | **Fleet & Assets screen.** As the design, Blueprint dark, under RESPOND after Evacuation Management (§58 Q9): KPIs from data (vehicles and how many armoured, available now at the selected mission, average fuel or charge, maintenance due within 14 days); the vehicles and critical assets table (code, asset, mission, location, fuel bar, status); the evacuation capacity card for the selected mission; the maintenance alerts. A mission filter (default: a mission with an ACTIVE incident, else all). Every button from `GET /api/me/permissions`. Rows flash on change. | — | M | — |
| FLT-07 | **Who sees what.** Every role sees assets, statuses, fuel, positions as labels, capacity and maintenance. A driver's name only for those who may read the mission's people (as EV-09); others see "Driver assigned". | — | M | A Viewer sees VH-02 BLOCKED · DRIVER SOS with no driver name; the Cairo Head of Mission sees no Nairobi driver names. |
| FLT-08 | **A demo scenario** `NBO-FLEET`, played while INC-1042 is ACTIVE (after NBO-CIVIL-UNREST scene 2): scene 1 VH-04's simulated telematics drive it from the residence into the impact zone; scene 2 it turns back out of the zone; scene 3 VH-05's brake service is reported done by the workshop (simulated) and it becomes available. | — | M | Played from the presenter bar. |

### Not in this module
Real telematics or fuel-card feeds; fuel stock and supplier delays (Supply Chain); assigning a vehicle to a trip (Journey Management) or to a VIP motorcade; route planning or turn-by-turn tracking; booking or requesting partner vehicles automatically; a Fleet/Logistics Officer role (§58 Q4); an agent proposing vehicle moves (§58 Q7); adding or editing assets in the app.

## 56. Data changes (proposed in `docs/schema/proposed-changes.md`)

- **PC-33 · `fleet_asset`**: tenant, mission, code (unique per tenant), kind (`VEHICLE`, `EQUIPMENT`), type label, armoured, seats (vehicles), driver (nullable person, same tenant and mission), location `geography(Point,4326)` and label, fuel or charge %, position time, status (`AVAILABLE`, `IN_USE`, `MAINTENANCE`), status reason, source. FORCE RLS; SELECT, INSERT (seeded through the service layer) and UPDATE of location, label, fuel, status and reason only; no DELETE. The derived states (blocked, in zone, assigned) are not stored.
- **PC-34 · `fleet_maintenance`**: tenant, asset, task, due date, done at and by (user or the simulated workshop). FORCE RLS; SELECT, INSERT and UPDATE of the done columns only, once; no DELETE. Guard: done is final; the time is written by the database.
- The FLEET timeline entry uses the existing incident timeline; no new event table.

## 57. Acceptance for the module

Playwright on the real stack: before NBO-CIVIL-UNREST, the Nairobi register is as FLT-01, 4 of 5 vehicles available, VH-05 in maintenance, labelled simulated. After scene 4, VH-02 is BLOCKED · DRIVER SOS and IN IMPACT ZONE, 3 of 5 available, capacity 20 against 16. After scene 5, the available vehicles show ASSIGNED · EVAC. `NBO-FLEET`: VH-04's entry into the zone raises the alert and a FLEET timeline entry, its exit a second; VH-05's service done removes its alert and makes it available. A Security Officer sets a vehicle to MAINTENANCE with a reason; a Viewer cannot, and sees no driver names; the Cairo Head of Mission sees no Nairobi driver names. Every change is audited and the chain verifies; `make acceptance` (all existing specs) still passes.

## 58. Questions for the product owner (proposed defaults)

1. **Register:** seeded for every mission (about 48 vehicles, 19 armoured, as the design's KPI, plus generators and satellite terminals), illustrative and read-only apart from status and maintenance; adding or editing assets comes later. *Default: yes.*
2. **Telematics:** simulated only: seeded positions and fuel, moved by scenario events (`VEHICLE_POSITION`) through the worker. No real provider. *Default: yes.*
3. **Blocked, in zone, assigned:** worked out from the check-in, incidents and evacuations each time, not stored, so they clear by themselves (as HL-04's Avoid). *Default: yes.*
4. **Who changes status and maintenance:** Security Officer, Duty Officer and the mission's Head of Mission, through `app/core/approvals.py`. No new Fleet/Logistics Officer role in the pilot (it would change roles and grants). *Default: yes.*
5. **Capacity:** passenger seats in available vehicles against the mission part of the evacuation (16 in Nairobi). A shortfall suggests Sentinel Secure Transport where it covers the country; it requests nothing. *Default: yes.*
6. **Maintenance alerts:** overdue or due within 14 days. *Default: yes.*
7. **Agent proposal:** none in this module (moving or reassigning vehicles stays with people). *Default: not now.*
8. **Driver names:** only for those who may read the mission's people; others see "Driver assigned". *Default: yes.*
9. **Screen:** "Fleet & Assets" under RESPOND, after Evacuation Management. *Default: yes.*
10. **Demo:** `NBO-FLEET` during NBO-CIVIL-UNREST (from scene 2): VH-04 into and out of the impact zone, then VH-05 back from the workshop. Phase 1 scenes are unchanged; the Fleet screen just reflects them. *Default: yes.*
11. **🔒 prompts:** the migration (PC-33..34: RLS, grants, guards) and the status and maintenance actions (approvals) need your named sign-off, as before (D-29).
