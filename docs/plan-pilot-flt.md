# Plan · Pilot module 11: Fleet & Assets (Prompt 71)

For the product owner and the coding agent. It maps FLT-01..08 (`docs/requirements-pilot.md` §54–58) and D-41 onto the code after pilot module 10, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner; the rest follows from approved documents. Everything is simulated (D-19, D-41); nothing external is called.

## 1. Requirements against existing code

| FLT | Exists today | New work | Prompt |
|---|---|---|---|
| 01 Register | `mission`, `site` (embassy, residence, Nairobi hotel); Peter Mwangi (LOCAL_STAFF, "Driver") at `data.PETER` | PC-33 `fleet_asset`, seeded for every mission through `fleet.service.ensure_assets()` as `nexira_api` (§2) | 72, 74 |
| 02 States | `v_checkin_latest`; incidents with `location` and `impact_radius_m`; HL-04's `ST_DWithin` test; live evacuations | `fleet.service` works out blocked, in zone and assigned on every read, with the at-site rule (§3, **G-1**) | 73 |
| 03 Capacity | `evacuation.counts`; partner coverage | `capacity()`: seats against the mission part of the evacuation, with a SECURE_TRANSPORT suggestion (§4) | 73 |
| 04 Maintenance | `approvals.user_has_role()` | PC-34 `fleet_maintenance`; alerts; status and "done" actions through `approvals.py` (§5) | 72, 73 |
| 05 Geofence | Redis Streams to worker consumers; `incident_event` (free-text `event_type`) | a `fleet` consumer for `VEHICLE_POSITION` and `WORKSHOP_DONE`; FLEET timeline entries on crossings (§6) | 73, 74 |
| 06 Screen | Blueprint dark; `Kpi`, `Card`, `FlashRow`; `GET /api/me/permissions` | the screen under RESPOND, after Evacuation Management (§8) | 75 |
| 07 Who sees what | `evacuations.service.name_scope()` (NAME_READERS, plan-pilot-ev G-8) | driver names only within that scope (§7) | 73 |
| 08 NBO-FLEET | the scenario player and presenter bar | the scenario (§9) | 74 |

## 2. The register and the seed (FLT-01, §58 Q1)

`ensure_assets()` seeds from `seed/data.py`, idempotently, as the plans are. Codes are unique per tenant.

- **Nairobi, as the design.**
  - VH-01 armoured SUV (B6), 4 seats, embassy garage, 82%.
  - VH-02 armoured SUV (B6), 4 seats, at `data.PETER` "Haile Selassie Ave", 46%, IN USE, driver Peter Mwangi.
  - VH-03 minibus 14-seat, 13 passenger seats, embassy garage, 90%.
  - VH-04 pickup 4×4, 3 seats, at the residence, 64%.
  - VH-05 sedan (official), 3 seats, "Workshop", 30%, MAINTENANCE "Brake service overdue".
  - GEN-NBO generator 250 kVA, 72%; SAT-NBO satellite terminal, 100%.
- **Other missions.** Addis Ababa VH-11 and Baghdad VH-21 as the design (armoured SUVs), and a generator and satellite terminal at every mission (GEN-, SAT-<code>). 48 vehicles in all, 19 armoured, as the design's KPI: one vehicle at every other mission, a second at eight higher-risk missions (ADD, BGW, ABV, ISB, CAI, AMM, PRY, JKT); codes from VH-31 in mission order. Garage vehicles stand within 50 m of the mission's embassy site.
- **Drivers.** VH-02 has Peter Mwangi; the other vehicles get no driver ("No driver assigned"). A person changes no driver in the pilot (PC-33 freezes it).
- **Maintenance items (PC-34).** VH-05 "Brake service" due 3 days ago; VH-21 "Tyre replacement (run-flat)" due in 5 days; GEN-ISB "Load test" due in 10 days; VH-11 "Armour inspection" due in 30 days (not yet an alert); routine items 30–90 days out elsewhere. Dates are relative to the seed date, as Document Expiry's.

## 3. What a vehicle can do now (FLT-02, §58 Q3)

Worked out in one SQL query per read, in this order, first match wins:

1. **MAINTENANCE**: the stored status.
2. **BLOCKED · DRIVER SOS**: the driver's latest `v_checkin_latest` answer, in a CHECKIN campaign whose incident is ACTIVE, is NEED_HELP. A later SAFE, or the incident leaving ACTIVE, clears it.
3. **IN IMPACT ZONE · INC-…**: the last position is inside an ACTIVE incident's impact zone (`ST_DWithin(a.location, i.location, i.impact_radius_m)`, as HL-04) **and not at a mission site** (G-1).
4. **ASSIGNED · EVAC · EVN-…**: the mission has an ACTIVE evacuation.
5. Else the stored AVAILABLE or IN USE.

A vehicle is **available** in states 4 and 5. Nairobi:
- before NBO-CIVIL-UNREST: 4 of 5 available (VH-05 in maintenance);
- after scene 4: VH-02 is BLOCKED (Peter answered NEED HELP) and also in the zone (shown as a second tag), so 3 of 5 are available;
- after scene 5: VH-01, VH-03 and VH-04 are ASSIGNED · EVAC;
- after EVN-1001 completes, the assignment clears by itself.

## 4. Capacity (FLT-03, §58 Q5)

- **Seats available:** passenger seats of available vehicles at the mission.
- **Seats needed:** a live (PENDING_ACTIVATION or ACTIVE) evacuation's STAFF + DELEGATE + DEPENDANT counts; otherwise the mission's active DIPLOMAT, DELEGATE and DEPENDANT people.
- **Nairobi:** 24 seats available before scene 1 and 20 after scene 4, against 16 needed, so "Capacity sufficient".
- **A shortfall** names the active partner with SECURE_TRANSPORT covering the mission's country with the shortest SLA (Sentinel in EMEA), as a suggestion with a link to Assistance Partners. Where none covers the country (Islamabad, for example), it says "No secure-transport partner covers <country>". Nothing is requested.

## 5. Maintenance and status (FLT-04, §58 Q4, Q6)

- **Alerts:** items not done with `due_on ≤ today + 14`, overdue first.
- **Who acts:** `SECURITY_OFFICER|DUTY_OFFICER|HEAD_OF_MISSION` for the asset's mission (unscoped grants count), checked with `approvals.user_has_role()` (🔒, D-29).
- **Actions:**
  - `PATCH /api/fleet/assets/{id}/status` `{status, reason}`: AVAILABLE, IN USE or MAINTENANCE. The reason is required for MAINTENANCE (the database checks it too). Audit `FLEET.STATUS`.
  - `POST /api/fleet/maintenance/{id}/done`: once; audit `FLEET.MAINTENANCE_DONE`. A second call gets 409. Marking an item done does not change the vehicle's status; a person or the workshop event does that (G-7).
- Every refusal is 403 with the roles named, as the other modules.

## 6. Telematics and the geofence alert (FLT-05, §58 Q2)

- **Events (simulated):**
  - `VEHICLE_POSITION` `{asset_code, lat, lon, label, fuel_pct}`;
  - `WORKSHOP_DONE` `{asset_code, task}`.
- **The worker.** A new `fleet` consumer group calls `fleet.service.position()` and `workshop_done()` as the SYSTEM actors "telematics (simulated)" and "workshop (simulated)".
- **`position()`:**
  - locks the asset row;
  - works out the ACTIVE incidents whose zone holds it (with the at-site rule) before and after the move;
  - updates location, label, fuel and `position_at`;
  - audits `FLEET.POSITION` (G-5);
  - for each incident entered or left, writes an `incident_event` FLEET row ("VH-04 entered the impact zone of INC-2026-1042" / "VH-04 left the impact zone of INC-2026-1042 · Ambassador's Residence Nairobi");
  - after commit, publishes `FLEET_UPDATED` and `INCIDENT_UPDATED`.
- **`workshop_done()`:** marks the open item with that task done (`done_by_type` WORKSHOP), sets the vehicle AVAILABLE if it was in MAINTENANCE, and audits both.
- **Only crossings are entries (G-4).** A vehicle already in a zone when an incident opens gets no timeline entry; the screen shows its state.
- **Live updates.** `FLEET_UPDATED` is forwarded to browsers. The screen also refreshes on `CHECKIN_UPDATED`, `INCIDENT_UPDATED` and `EVACUATION_UPDATED`, because the derived states depend on them.

## 7. API and who sees what (FLT-07, §58 Q8)

- `GET /api/fleet/assets?mission_id=`: every role. Rows give code, kind, type, armoured, seats, mission, location label, `lat`/`lon`, fuel, `position_at`, stored status and reason, derived state(s) with the incident or evacuation reference, `driver_assigned`, and `driver_name`. The driver's name is null outside `evacuations.service.name_scope()` for the asset's mission.
- `GET /api/fleet/missions/{id}`: the KPIs and capacity.
- `GET /api/fleet/maintenance?mission_id=`: the items and the alerts.
- `PATCH …/status` and `POST …/done`, as in §5.
- `GET /api/me/permissions?entity_type=fleet&entity_id=<mission>` returns `set_asset_status` and `complete_maintenance`.
- The tenant-wide KPIs (vehicles, armoured, average fuel, due within 14 days) are counts every role may see.

## 8. The screen (FLT-06, §58 Q9)

- **Placement:** "Fleet & Assets" (icon `truck`), under RESPOND after Evacuation Management.
- **Layout, as the design:**
  - four KPIs: vehicles · armoured; available now at the selected mission, "of N vehicles"; average fuel or charge, with the generator's figure; due for service within 14 days;
  - the "Vehicles & critical assets" table with the "GPS + telematics (simulated)" subtitle: code, asset, mission, location, fuel bar (amber below 50%), state tags;
  - on the right, the "Evacuation capacity · <city>" card (seats available against needed, with the suggestion line) and "Maintenance alerts", each with "Mark done" when allowed.
- **Geofence alert:** a red banner lists vehicles currently in an impact zone. A new FLEET crossing flashes the row and shows a toast.
- **Actions and filters:**
  - a status menu per row, when allowed (a reason dialog for MAINTENANCE);
  - the mission filter (default: a mission with an ACTIVE incident, else all), driven by `?mission=`.
- **Elsewhere:** the Incidents timeline labels FLEET entries.

## 9. Scenario `NBO-FLEET` (FLT-08, §58 Q10)

Played while INC-1042 is ACTIVE; without an ACTIVE incident the positions still move and no alert is raised.

| Scene | Events |
|---|---|
| 0 Ready | VH-04 position at the residence (so a replay starts from the same place) |
| 1 Into the zone | five VH-04 positions 2 s apart, from the residence along Waiyaki Way to Uhuru Highway near the CBD, fuel falling 64 → 61%. The second one leaves the residence site: "entered the impact zone" |
| 2 Back out | four positions back to the residence: "left the impact zone" on arrival |
| 3 Workshop | `WORKSHOP_DONE` VH-05 "Brake service": the alert clears; VH-05 AVAILABLE, so Nairobi has one more vehicle and 3 more seats |

Scene 3 is final, as a real repair: replaying it from the presenter bar changes nothing (G-9); `make reset-demo` restores the seed.

## 10. Acceptance specs (§57)

- **The Phase 1 spec** (the only place in `make acceptance` where these states exist, as for EV):
  - scene 0: Nairobi 4 of 5 available, VH-05 MAINTENANCE, labelled simulated;
  - after scene 4: VH-02 BLOCKED · DRIVER SOS and in the zone, 3 of 5 available, capacity 20 against 16;
  - after scene 5: ASSIGNED · EVAC on VH-01, VH-03 and VH-04.
- **`flt-acceptance.spec.ts`** (after `ev-`, before `hl-`, by name; added to `make acceptance`). INC-1042 is ACTIVE again by then (the Document Expiry spec), and EVN-1001 is complete, so nothing is assigned. It covers:
  - NBO-FLEET from the presenter bar: the alert and two FLEET timeline entries;
  - VH-05 available after the workshop;
  - a Security Officer sets VH-03 to MAINTENANCE with a reason and back; a Viewer is refused (403);
  - no driver names for the Viewer or the Cairo Head of Mission;
  - the audit trail, and the chain verifies.

## 11. Gaps and conflicts, with proposed answers

| # | Gap | Proposed answer |
|---|---|---|
| G-1 | **Needs a decision.** Every Nairobi site is inside INC-1042's 5 km impact zone (embassy about 2.2 km from the epicentre, residence about 3.6 km). Read literally, FLT-02 would mark every garage vehicle IN IMPACT ZONE, leaving Nairobi 0 of 5 available, no capacity, and nothing like the design (which shows garage vehicles AVAILABLE). | A vehicle **at a mission site** is not "in the zone": its last position is within 150 m of one of its mission's sites (embassy, residence, or the Nairobi delegation hotel). The zone and the geofence apply to vehicles on the road. Nairobi then gives FLT-02's 4 → 3 of 5 as approved, and VH-04 driving off the residence site is the "entry" in NBO-FLEET. Amends FLT-02's wording; nothing else changes. |
| G-2 | Which signal blocks a vehicle | Only the driver's check-in answer (NEED HELP in an ACTIVE incident's CHECKIN campaign). An open Assistance Partners SOS request does not, so the two modules stay independent. |
| G-3 | Does IN USE count for capacity? | Yes: an IN USE vehicle can be recalled; only maintenance, blocked and in zone remove it (FLT-02 as written). |
| G-4 | A vehicle already in a zone when an incident opens | No timeline entry; only telematics crossings make entries. The screen shows the current state. |
| G-5 | Auditing telematics | Each `VEHICLE_POSITION` is audited `FLEET.POSITION` by the SYSTEM actor, as the muster scanner's check-ins; NBO-FLEET sends ten. |
| G-6 | Seed numbers | 48 vehicles, 19 armoured, as §2; a generator and a satellite terminal at each of the 36 missions. Seats: armoured SUV 4, minibus 13, pickup 3, sedan 3. |
| G-7 | Does "done" change the status? | Not for a person: they set the status separately, so finishing one item never hides another. The simulated workshop does both, as a real workshop returning the car. |
| G-8 | Name scope | Reuse `evacuations.service.name_scope()` (NAME_READERS), so drivers and evacuees follow the same rule. |
| G-9 | Replaying NBO-FLEET | Scene 0 puts VH-04 back at the residence; scene 3 is final (the item is done); `make reset-demo` restores everything. |
| G-10 | FLEET on the incident timeline | `incident_event.event_type` is free text, so this needs no schema change; the Incidents screen gets a label. |
| G-11 | 🔒 scope | The migration (Prompt 72) and the service's approvals checks (Prompt 73) are 🔒 under D-29. The seed, the scenario, the screen and the specs are not. |

## 12. Migration 0011 (Prompt 72, 🔒)

- **`fleet_asset` (PC-33):**
  - CHECKs on kind, status, fuel 0..100, seats ≥ 1 for vehicles only, a driver for vehicles only, and a reason required for MAINTENANCE;
  - UNIQUE (tenant, code);
  - FORCE RLS with `tenant_isolation`;
  - `GRANT SELECT, INSERT` and `GRANT UPDATE (location, location_label, fuel_pct, position_at, status, status_reason)` to `nexira_app`; no DELETE;
  - a guard trigger (pinned `search_path`): mission, code, kind and driver frozen; the driver is a person of the same tenant and mission; `updated_at` written by the database.
- **`fleet_maintenance` (PC-34):**
  - the asset in the same tenant;
  - FORCE RLS;
  - `GRANT SELECT, INSERT` and `GRANT UPDATE (done_by_type, done_by)`; no DELETE;
  - a guard: done once and final; `done_at` written by the database; task, asset and due date frozen; inserted not yet done.
- **Indexes:** a GiST index on `fleet_asset.location`.
- **Tests (as `nexira_api`):**
  - isolation, and every refusal;
  - no DELETE;
  - the backup role reads both tables;
  - `test_downgrading_0011_restores_0010_exactly`; the table count goes up by 2;
  - `test_tenant_isolation` rows.

## 13. Prompts

As `docs/prompts-pilot.md` Prompts 72–76: the migration (🔒); the service (🔒); the seed, telematics and NBO-FLEET; the screen; the acceptance. Each ships with its tests, and `make acceptance` passes at the end.

## 14. Decisions by the product owner (2026-11-01, PR #85: "approved")

- G-1: a vehicle within 150 m of one of its mission's sites is at site, not in an impact zone; the zone and the geofence apply to vehicles on the road. FLT-02 reads accordingly.
- G-2..G-11: as proposed.
