# Plan · Pilot module 5: Assistance Partners (Prompt 43)

For the product owner and the coding agent. It maps AS-01..08 (`docs/requirements-pilot.md` §29–33) and D-36 onto the code after the Weather module, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner; the rest follows from approved documents. Partners are simulated (D-19, D-36); nothing external is contacted.

## 1. Requirements against existing code

| AS | Exists today | New work | Prompt |
|---|---|---|---|
| 01 Directory | nothing | `partner` (PC-21); `app/modules/partners` model, `GET /api/partners`; seed of five partners (§33 Q1) | 44, 45 |
| 02 Request | PB-07 step 6 writes text only | `partner_request` (PC-22); `POST /api/partner-requests`, role checks through `approvals.user_has_role` (§4) | 44, 45 |
| 03 Track | nothing | status table enforced by the guard trigger (§7); cancel and complete endpoints; `PARTNER_REQUEST_UPDATED` to browsers | 44, 45 |
| 04 Simulated partner | the simulated channel adapter (the pattern) | `partners/adapter.py`: `PartnerAdapter` protocol, `SimulatedPartnerAdapter`, `adapter_for()` refusing anything else; a worker tick (§3) | 45 🔒 |
| 05 Playbooks | `PARTNER_REQUEST` in `playbooks/engine.py` | the step creates a request (§5) | 45 |
| 06 SOS suggestion | NEED_HELP answers, the incident timeline | `GET /api/partners/suggest?person_id=&service=` (§6); shown on Safety Check-in and the partner screen | 45, 46 |
| 07 Coverage | missions and their countries | `GET /api/partners/coverage`: mission × service (§8) | 45, 46 |
| 08 Minimum sharing | restricted trips (D-33) | the request stores only the AS-08 fields; the guard refuses restricted travellers (G-5) | 44, 45 |

## 2. Data (Prompt 44, 🔒)

As PC-21 and PC-22, with these details:
- `partner.services` and `partner.coverage` are arrays with CHECKs (non-empty; every service one of the five; every code two capital letters). `UNIQUE (tenant_id, code)`.
- `partner_request.reference` from `next_reference('REQ', false)`, seeded at 550 so the first is REQ-551 (the design). `UNIQUE (tenant_id, reference)`.
- `requested_at` defaults to `now()`. `accepted_at` and `completed_at` are written **by the trigger** on the transition, never by the app (the lesson of Prompt 24: database-written timestamps).
- `eta` may be set only on the transition to ACCEPTED or while ACCEPTED or EN_ROUTE.
- The guard trigger runs as the caller with `SET search_path = pg_catalog, public, pg_temp` (the lesson of Prompt 39).

## 3. The simulated partner (Prompt 45, 🔒)

`app/modules/partners/adapter.py`, modelled on `notifications/channels.py`:
- `PartnerAdapter.respond(request, now) -> Response | None`: what the partner does next, if anything.
- `SimulatedPartnerAdapter`, deterministic from the request id (the same request always behaves the same):
  - accepts 5–15 s after `requested_at`, with `eta = accepted time + sla_minutes`;
  - goes EN_ROUTE 10 s after accepting;
  - never completes: a person marks COMPLETED (§33 Q4);
  - declines about 1 in 10 **ad-hoc** requests (G-2).
- `adapter_for(configured)` returns the simulated adapter and refuses any other setting, so a real integration cannot be switched on by configuration (D-29).
- A worker loop every 2 s per tenant in `WORKER_TENANT_IDS`, as `nexira_api` (D-01). It applies each response, audits it (actor SYSTEM `partners.simulated`) and publishes `PARTNER_REQUEST_UPDATED` after commit.

## 4. Who may do what

| Action | Roles (through `app/core/approvals.py`) |
|---|---|
| Read partners, coverage, requests | every role (G-10) |
| Request, cancel, complete | `DUTY_OFFICER|SECURITY_OFFICER|HEAD_OF_MISSION`, checked with `user_has_role` scoped to the request's mission. HQ roles are unscoped, so they match any mission; a Head of Mission matches only their own (D-05, §33 Q2) |
| Accept, decline, en route | the simulated partner only (the API offers no endpoint for them) |

No second person (§33 Q3). Agents never request (D-36).

## 5. PB-07 step 6 (Prompt 45)

The step's config stays as it is (`partner: "Kestrel Medical Assistance"`). PB-07 gets **no new version**, and its seed and D-23 figures do not move.
- The engine finds the active partner whose **name** matches `config.partner` and which offers `config.service_code` (default MEDICAL). It creates a request for the incident's mission, with `created_by_type PLAYBOOK` and the run id, and the note "Standby · <incident reference>".
- G-1: if no such partner covers the mission's country, or the tenant has no partners (older tenants, tests), the step completes as today. Its timeline says "no partner covers <country> for MEDICAL (simulated)". A missing partner never fails a run.
- The step's result adds `request_reference`, shown in the run timeline.

## 6. SOS suggestion (Prompt 45)

`suggest(person_id, service)` (§33 Q6, default service SECURE_TRANSPORT):
1. Find the person's country: the country of the mission **nearest to their current location** (G-4), or their own mission's if they have no location.
2. Return the active partners offering the service and covering that country, with the shortest SLA first. The screen shows the first.

Peter Mwangi (Nairobi, KE) gets Sentinel Secure Transport (30 min) ahead of Meridian Relocation (60 min).

## 7. Status table (the guard trigger)

| From | To |
|---|---|
| REQUESTED | ACCEPTED, DECLINED, CANCELLED |
| ACCEPTED | EN_ROUTE, CANCELLED |
| EN_ROUTE | COMPLETED, CANCELLED |
| COMPLETED, DECLINED, CANCELLED | (final) |

Every transition is audited: `PARTNER_REQUEST.CREATE`, `.ACCEPT`, `.DECLINE`, `.EN_ROUTE`, `.COMPLETE` and `.CANCEL`.

## 8. Seed partners and coverage (§33 Q1)

| Code | Partner | Services | SLA | Coverage |
|---|---|---|---|---|
| KES | Kestrel Medical Assistance | MEDICAL | 15 min · 24/7 | every mission country |
| ATL | Atlas Air Evacuation | EVACUATION | 4 h | every mission country except AU and AR |
| SEN | Sentinel Secure Transport | SECURE_TRANSPORT | 30 min | Africa, the Middle East, Europe |
| HAR | Harbor Crisis Support | WELFARE | 2 h · remote | every mission country |
| MER | Meridian Relocation | RELOCATION, SECURE_TRANSPORT | 1 h | every mission country |

Coverage is 34 of 36 missions with all five services. Canberra and Buenos Aires lack EVACUATION and are the two gaps shown.

## 9. Gaps and conflicts, with proposed answers

**G-1 · PB-07 without a new version.** Answer: §5. The partner is found by name; a missing partner degrades to today's text, and the Phase 1 acceptance does not change.

**G-2 · Declines and the demo.** The design never shows a decline, but Q4 asks for about 1 in 10. **Proposal:** only requests **without an incident** can be declined (deterministic from the id). Every demo request carries its incident, so none is declined.

**G-3 · "Nearest" partner.** PC-21 has no partner locations. **Proposal:** "nearest capable" means covering the person's country with the shortest SLA (§6). Partner locations can come with a real integration.

**G-4 · The country of a location.** There is no reverse geocoding offline (D-24). **Proposal:** use the nearest mission's country. This is exact for every seeded person; a person in transit between countries gets the nearer mission's.

**G-5 · Restricted travellers.** **Proposal:** the guard refuses a person who travels on a restricted trip that is PENDING or APPROVED and has not ended (`ends_on >= current_date`).

**G-6 · Completing and cancelling.** Done by a person with the request roles (§4); a completed request cannot be reopened.

**G-7 · ETA.** It comes from the SLA in real time, so Atlas's 4 h shows as a time four hours later. Only acceptance is sped up for the demo (5–15 s).

**G-8 · Where the loop runs.** A new `partners_loop` in the worker, beside the flight and weather loops.

**G-9 · Location of a request.** The person's current location when a person is named, otherwise the mission's. `place_label` comes from the location or the mission's city.

**G-10 · Who reads requests.** **Proposal:** every role, like incidents and check-in. A request names a person and a place label only (AS-08).

**G-11 · Events.** `PARTNER_REQUEST_UPDATED` (request id, incident id), forwarded to browsers, for every create and change.

**G-12 · Older tenants.** The seed adds the partners and the REQ counter through `ensure_*` (new rows only), so a tenant seeded earlier gets them on the next seed. Until then the screen is empty and PB-07 falls back (G-1).

## 10. Migration 0006 (Prompt 44, 🔒)

- PC-21 `partner` and PC-22 `partner_request` as §2, with FORCE RLS, `tenant_isolation` and the grants in PC-21/22. There is no DELETE on either table, and no UPDATE on `partner`.
- The guard trigger `partner_request_guard`:
  - the status table (§7);
  - content frozen after insert (partner, service, mission, incident, person, place, location, note, creator, `requested_at`);
  - the trigger writes the timestamps;
  - same-tenant partner, mission, incident and person;
  - the partner active, offering the service and covering the mission's country;
  - the restricted-traveller rule (G-5);
  - `eta` only as §2.
- `nexira_backup` reads both tables through the default privileges. The downgrade restores 0005 exactly.

## 11. Decisions needed from the product owner

None. G-1..G-12 follow from D-36 and the defaults in §33. Worth a look: G-2 (declines only without an incident) and G-4 (country from the nearest mission).
