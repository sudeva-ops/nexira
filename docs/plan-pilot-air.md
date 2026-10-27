# Plan · Pilot module 3: Air Travel Tracking (Prompt 28)

For the product owner and the coding agent. It maps AT-01..08 (`docs/requirements-pilot.md` §14–18) and D-33 onto the code after pilot module 2, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner; the rest follows from approved documents. Flights are simulated (D-19, D-33); nothing external is called.

## 1. Requirements against existing code

| AT | Exists today | New work | Prompt |
|---|---|---|---|
| 01 Only our travellers' flights | FLIGHT segments on trips (PC-14), trip approval (PC-15) | Segment flight fields (PC-17); `flight` created only for APPROVED, not restricted trips (tracker query + PC-19 guard) | 29, 30 |
| 02 Air picture and table | MapLibre with self-hosted tiles (D-24), realtime | `GET /api/flights`, `/api/flights/{id}`; Air screen | 30, 31 |
| 03 Disruptions | nothing | Flight events from the feed; `FLIGHT_UPDATED` forwarded to browsers; banners | 30, 31 |
| 04 Landing moves travellers | `people.service.add_observations`, `location.recompute`; `FLIGHT` source (quality 90, decay 6/h) | Tracker adds one `FLIGHT` observation per traveller at the landing airport, then `recompute` for those people | 30 |
| 05 Restricted trips | nothing | `trip.restricted` (PC-17), frozen once submitted; enforced at every layer (§4) | 29–31 |
| 06 Simulated feed | the scenario player publishes events to the stream; the worker's tick loop | `travel/tracker.py`: a tick loop (create, move, land) and a `FLIGHT_FEED` stream consumer (scenario events) | 30 |
| 07 Trip and flight together | trip detail with segments | Each flight segment's live status in the trip API and the Journey detail; trip cancelled → flight CANCELLED | 30, 31 |
| 08 Audited | `audit.write` | `FLIGHT.TRACK`, `FLIGHT.<STATUS>` with actor `SYSTEM` (the tracker); positions not audited | 30 |

## 2. The tracker (Prompt 30)

`app/modules/travel/tracker.py`, run by the worker (`app/workers/__main__.py`) for the tenants in `WORKER_TENANT_IDS`, as `nexira_api` (D-01).

**Tick (every 5 s), per tenant, in one transaction:**
1. **Ensure:** for each FLIGHT segment with a flight number and both airports, of an APPROVED trip that is not restricted, departing within 24 h or not yet landed, insert a `flight` (status SCHEDULED, `FLIGHT.TRACK` audited) if none exists. The PC-19 guard refuses anything else.
2. **Stop:** a flight whose trip is now CANCELLED becomes CANCELLED (event details `{"reason": "trip cancelled"}`).
3. **Move:** for SIMULATED flights, the clock drives the state: AIRBORNE from the estimated departure, position on the great circle between the airports by progress, altitude and speed from a simple climb–cruise–descent profile, LANDED at the estimated arrival. HOLDING flights circle a point 30 km short of the destination. SCENARIO flights (G-3) move by the same geometry but change status only through feed events.
4. **Land:** on LANDED, at the destination or the diversion airport, add one `FLIGHT` observation per traveller at that airport and recompute their current location.
5. Publish `FLIGHT_UPDATED` (flight id, status, trip id) for each status change after commit. Positions alone are published at most every 15 s per flight, so the map moves without flooding the stream.

**Feed events (`FLIGHT_FEED` on the stream, consumer group `flights`):** the payload names a flight number and date and one change: `{"delay_min"}`, `{"status": "AIRBORNE", "departed_min_ago", "arrives_in_min"}`, `{"status": "HOLDING", "reason"}`, `{"status": "DIVERTED", "to", "arrives_in_min"}`, `{"status": "LANDED"}`, `{"status": "CANCELLED"}`. Times are relative to the event's arrival, so a scenario can compress a flight into minutes (D-33 default 6). The scenario player already publishes any event type; this is how a real provider would push updates, so only this consumer and the tick's "move" step change when a real feed arrives.

**Status rules (PC-19 guard and the tracker):**

| From | To |
|---|---|
| SCHEDULED | DELAYED, AIRBORNE, CANCELLED |
| DELAYED | AIRBORNE, CANCELLED (another delay updates the estimate, same status) |
| AIRBORNE | HOLDING, DIVERTED, LANDED |
| HOLDING | AIRBORNE, DIVERTED, LANDED |
| DIVERTED | HOLDING, LANDED |
| LANDED, CANCELLED | final |

A delay is recorded when an estimate is 30 min or more after the schedule (D-33): DELAYED before departure, and a `DELAYED` event with the minutes when airborne (status stays AIRBORNE; the API adds `delay_min`).

## 3. API (Prompt 30)

| Method and path | Who | What |
|---|---|---|
| `GET /api/flights` | all roles | Filters `status`, `disrupted` (DELAYED, HOLDING, DIVERTED, CANCELLED, or `delay_min` ≥ 30). Each row: flight number, airports and names, schedule and estimates, `delay_min`, status, `diverted_to`, position, altitude, speed, progress, travellers (names), trip id and reference, `simulated: true` |
| `GET /api/flights/{id}` | all roles | Plus the event timeline |
| Trip API | as today | Each FLIGHT segment gains `flight_number`, airports and, when tracked, `flight_id` and `flight_status` |
| `GET /api/airports` | all roles | For the planner's airport fields |

No write endpoints: flights are written only by the tracker.

## 4. AT-05 (restricted trips) at every layer

| Layer | Rule |
|---|---|
| Database | `trip.restricted` frozen once the trip leaves DRAFT (PC-15 guard); `flight` INSERT refused for a restricted or not-APPROVED trip (PC-19 guard) |
| Tracker | the ensure query excludes restricted trips; no observation, event, audit row or `FLIGHT_UPDATED` can exist without a flight |
| API | flights come only from `flight`, so there is nothing to filter; the trip API returns no `flight_id`/`flight_status` for a restricted trip |
| Screen | the Air screen lists flights only; the "Safeguards" card states the rule |
| Tests | a seeded restricted trip with a flight segment departing now: no row, no event, no audit entry, absent from every endpoint and from the e2e |

## 5. Gaps and conflicts, with proposed answers

**G-1 · Phase 1 figures must not change.** XW 451's travellers are three **existing** staff from a mission far from any incident (London), not new people, so the D-23 and D-27 counts stay the same; Mombasa is far outside the Nairobi radius, so landing there changes no exposure. **Proposal:** as stated; the seeded trip TRP-8818 "HQ consultations · Nairobi" (London → Abu Dhabi → Nairobi), APPROVED, with segment XW 451 AUH → NBO.

**G-2 · A separate scenario, not new events in NBO-CIVIL-UNREST.** Adding flight events to the Phase 1 scenario would change its scenes, and the Phase 1 acceptance clicks "Next scene" without waiting, so later events in a scene would be skipped there anyway. **Proposal:** a scenario `NBO-AIR-DIVERSION` ("Inbound flight diverted from Nairobi"), scene 1: XW 451 airborne, arriving in 10 min; scene 2: HOLDING ("arrivals restricted: airport access roads affected"); scene 3: DIVERTED to Mombasa, arriving in 2 min, then LANDED. It can be played during or after the Nairobi scenario from the presenter bar.

**G-3 · Demo flights must not land on their own.** A seeded schedule is fixed at reset time, but a demo may run hours later; by the clock the flight would already have landed in Nairobi. **Proposal:** `flight.source` (already in PC-19) is `SCENARIO` for flights the seed marks as scenario-driven (it inserts XW 451's flight row itself, SCHEDULED; the seed already writes as `nexira_api`); the tracker never changes a SCENARIO flight's status by the clock, only through `FLIGHT_FEED`. Other seeded flights are `SIMULATED` and follow the clock in real time (D-33 default 6).

**G-4 · Background flights for the KPIs.** **Proposal:** two more approved, non-restricted seeded trips with long flights scheduled around reset time (e.g. Jakarta → Amsterdam, São Paulo → Lisbon), so "Officials airborne" shows real-time flights during a working day. Their travellers are existing staff away from any incident (G-1).

**G-5 · Exposure does not follow a landing.** Exposure is computed on incident events only; a traveller who lands near an active incident is not added until the incident next changes. **Proposal:** after a landing, publish `INCIDENT_UPDATED` for each ACTIVE incident within 100 km of the landing airport, so the existing exposure handler recomputes. Nothing changes for the demo (Mombasa is far from Nairobi).

**G-6 · Airport codes in the planner.** **Proposal:** a FLIGHT segment's airports must exist in `airport` (422 otherwise); the planner offers them as a list. The seeded list covers every mission city, the scenario airports and the background flights. A flight segment without a flight number or airports is allowed (not tracked), as today.

**G-7 · A restricted trip's itinerary on the Journey screen. Needs a decision.** D-33 says nothing is shown about a restricted trip's flights, but today the Journey detail shows every segment, including a flight's title, to every role. **Proposal:** for a restricted trip, the trip API returns FLIGHT segments without `title`, `flight_number`, airports or times to anyone except the requester, TRAVEL_DESK, SECURITY_OFFICER and ADMIN; others see "Flight (restricted)". The trip itself (destination, dates, approval) stays visible, as JR-08 requires.

**G-8 · Status transitions.** PC-19 says "forward only"; HOLDING → AIRBORNE (holding ends) is needed. **Proposal:** the transition table in §2, enforced by the PC-19 guard; LANDED and CANCELLED are final.

**G-9 · Who reads flights.** **Proposal:** every role, like trips (JR-08). Restricted trips have no flights (§4), so nothing sensitive is readable.

## 6. Migration 0004 (Prompt 29, 🔒)

- PC-17: `trip_segment.flight_number`, `from_airport`, `to_airport` with a CHECK that they are NULL unless `kind = 'FLIGHT'`; `trip.restricted` added to the `trip_guard` content freeze.
- PC-18: `airport` with FORCE RLS, `tenant_isolation`, SELECT and INSERT for `nexira_app`.
- PC-19: `flight` and `flight_event` with FORCE RLS and `tenant_isolation`; grants as PC-19; guards: INSERT refused for a restricted or not-APPROVED trip, the status table in §2, `flight_event` append-only (no UPDATE or DELETE grant), `trip_segment_id` and flight number frozen.
- `nexira_backup` reads the new tables through the default privileges; the downgrade restores 0003 exactly.
- Seed (simulator): airports; TRP-8818 with XW 451 (SCENARIO, G-1, G-3); the background trips (G-4); one restricted approved trip with a flight departing now (the AT-05 test); the `NBO-AIR-DIVERSION` scenario (G-2).

## 7. Decisions needed from the product owner

1. **G-7:** hide a restricted trip's flight segments from roles other than the requester, Travel Desk, Security Officer and Admin? (Proposed: yes.)

The other gaps follow from D-33, the approved PCs and the defaults in requirements-pilot.md §18.
