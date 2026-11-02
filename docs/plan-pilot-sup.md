# Plan · Pilot module 14: Supply Chain & Third-Party Risk (Prompt 89)

For the product owner and the coding agent. It maps SUP-01..07 (`docs/requirements-pilot.md` §69–73) and D-44 onto the code after pilot module 13, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner; the rest follows from approved documents. Everything is simulated (D-19, D-44): NEXIRA contacts no supplier, orders nothing and uses no channel.

## 1. Requirements against existing code

| SUP | Exists today | New work | Prompt |
|---|---|---|---|
| 01 Register | 36 missions; `site` (embassy per mission) | PC-43 `supplier`, seeded through `supply.service.ensure_register()` as `nexira_api`; dependencies on read (§2) | 90, 92 |
| 02 Routes and status | — | PC-44 `logistics_route`; `SUPPLY_ROUTE` and `SUPPLY_SUPPLIER` events in the worker; shown statuses on read (§3) | 90, 91, 92 |
| 03 Disruption | `incident.location`, `impact_radius_m`, `mission_id`; `incident_event` (free-text type, as FLEET and SITE); `fleet_asset` `GEN-<mission>` with `fuel_pct` for every mission | the zone tag, "impacted", SUPPLY timeline entries, the fuel stock (§4) | 91 |
| 04 Mitigation | `approvals.user_has_role()`; Fleet's `ACTORS` (Security Officer, Duty Officer, Head of Mission for the mission) | PC-45 `supply_mitigation`; activate and stand down (§5) | 90, 91 |
| 05 Screen | Blueprint dark; `Kpi`, `Card`; realtime; `GET /api/me/permissions`; the PLAN & INSIGHT group (Document Expiry) | the screen after Document Expiry (§7) | 93 |
| 06 Who sees what | `evacuations.name_scope()` and `sees_names()` | names of the people who acted, by scope (§6) | 91 |
| 07 NBO-SUPPLY | scenario player; presenter bar; NBO-FLEET and NBO-SITE as precedents | the scenario (§8) | 92 |

New backend module: `app/modules/supply/{models,schemas,service,consumer,router,tests}`.

## 2. The register (SUP-01, §73 Q1)

- **52 suppliers**, codes `SUP-nnn`. Constraints the seed must meet (a simulator test checks each):
  - the design's ten exactly as shown (code, name, service, mission, tier);
  - at least one supplier for each of the 36 missions; Global suppliers (`mission_id` NULL) on top, among them SUP-305 Northbridge Translations;
  - 14 in Tier 1;
  - every Tier 1 and Tier 2 supplier has a backup: another supplier with the same service, at the same mission or Global (G-2).
- **Nairobi** (as the design, plus backups):

| Code | Name | Service | Tier | Backup |
|---|---|---|---|---|
| SUP-104 | Swiftline Couriers | Diplomatic pouch courier | T1 | SUP-105 Kestrel Express Couriers |
| SUP-117 | Equator Guard Services | Guard force contractor | T1 | SUP-118 Highland Guard Services |
| SUP-121 | Rift Valley Fuels | Generator fuel supply | T2 | SUP-122 Mara Energy Supplies |
| SUP-126 | Savanna IT Networks | Local ISP & IT support | T1 | SUP-127 Upesi Networks |
| SUP-130 | Kilima Catering | Catering services | T3 | — |

  The backups are Tier 2 at the same mission. Their names are fictional and illustrative.
- **Dependencies, on read:**
  - "Backup supplier identified" with the backup's name;
  - "Included in mission BCP" from the seeded `in_bcp` (true for Tier 1, as the design);
  - "Security vetting current" while `vetting_valid_until` is today or later (all seeded current, 6–18 months out);
  - the last performance review score (seeded, e.g. 92).
- **Reported status** starts NORMAL, except SUP-251 Indus Facilities (Islamabad) and SUP-262 Archipelago Movers (Jakarta), WATCH "Monitoring local disruption", as the design.
- `source` is "Illustrative supplier register (simulated)". Audit `SUPPLY.SEED` once per tenant.

## 3. Routes and status (SUP-02, §73 Q2, Q5)

- **37 routes** (`path geography(LineString,4326)`, 2..50 points):
  - **Nairobi, four, as the design:**
    - R-NBO-1 "Pouch: Embassy → JKIA via CBD" (POUCH, SUP-104);
    - R-NBO-2 "Pouch: Embassy → JKIA via Southern Bypass" (POUCH, SUP-104, alternate of R-NBO-1);
    - R-NBO-3 "Fuel: depot → Embassy" (FUEL, SUP-121);
    - R-NBO-4 "Staff shuttle: Westlands → Embassy" (STAFF_TRANSPORT, SUP-117).
  - **33 other missions:** one pouch route each, from the embassy to an illustrative point about 15 km out, run by that mission's courier or its first supplier. Geneva and New York (UN), multilateral missions, have none (G-3).
- **Statuses:** a route reports OPEN, RESTRICTED, DELAYED or BLOCKED, and a supplier reports NORMAL, WATCH, DELAYED or AT_RISK, each with a detail. All start as in §2.
- **The feeds:**
  - `SUPPLY_ROUTE {route, status, detail}` and `SUPPLY_SUPPLIER {supplier, status, detail}` (codes, not ids);
  - only events from the scenario player are taken (the lesson of Prompt 80, M1);
  - the actor is SYSTEM "logistics feed (simulated)" or "supplier notice (simulated)";
  - audit `SUPPLY.ROUTE_STATUS` and `SUPPLY.SUPPLIER_STATUS` with the before and after status.
- **Shown, on every read, never stored:**
  - a route is **ALTERNATE** when it is OPEN and the route it is an alternate of is BLOCKED;
  - a supplier is **ROUTE BLOCKED** when one of its routes is BLOCKED;
  - a supplier's shown status is the worst of its reported status and ROUTE BLOCKED, in the order ROUTE BLOCKED > AT RISK > DELAYED > WATCH > NORMAL;
  - severity tones for the screen: crit, high, medium, low, ok.

## 4. Disruption from incidents (SUP-03, §73 Q3, Q6)

- **The zone tag.** A route is tagged with each ACTIVE incident whose impact zone it passes through: `ST_DWithin(path, incident.location, impact_radius_m)`. The tag reads "Through impact zone · INC-…" and does not change the status. All four Nairobi routes start at the embassy, 2.2 km from the epicentre, so all four are tagged while INC-<year>-1042 is ACTIVE (G-4).
- **Impacted.** A supplier is impacted when its mission has an ACTIVE incident (`incident.mission_id`) and its shown status is DELAYED, AT RISK or ROUTE BLOCKED. Global suppliers are never impacted (no mission).
  - **The banner,** one per ACTIVE incident with impacted suppliers: "3 third parties impacted by INC-<year>-1042." followed by their details, joined.
  - **KPIs:** "Impacted now" counts across all missions.
- **SUPPLY timeline entries.** A reported status **change** of a route or supplier, at a mission with an ACTIVE incident, writes `incident_event` type `SUPPLY` on each such incident, with actor SYSTEM.
  - Examples: "Nairobi · Pouch: Embassy → JKIA via CBD: BLOCKED (Road closure CBD → JKIA; reroute via Southern Bypass, +55 min)." and "Nairobi · Rift Valley Fuels: DELAYED (Fuel delivery postponed 24 h)."
  - Only changes write, as Fleet's crossings; a reset to the same status writes nothing.
- **Fuel stock (§73 Q6).** For a supplier that runs a FUEL route, the card shows "N h on-site stock", where N = round(`GEN-<mission>.fuel_pct` × `FUEL_TANK_HOURS` / 100) and `FUEL_TANK_HOURS` = 100 is an illustrative constant in the service. Nairobi: 72% gives 72 h. It is read from Fleet and not stored. A mission without a generator shows nothing.

## 5. Mitigation (SUP-04, §73 Q4)

- **`POST /api/supply/suppliers/{id}/mitigation {note?}`** (note at most 500 characters).
  - **Who:** a Security Officer, Duty Officer or Head of Mission for the supplier's mission, checked through `approvals.user_has_role(session, user, ACTORS, mission_id)` with Fleet's `ACTORS`. Anyone else gets 403.
  - **Only for an impacted supplier** (409 otherwise), and only if it has no active mitigation (409; the partial UNIQUE index backs this up).
  - **It records:**
    - the incident (the mission's ACTIVE incident; the most recent if there are several);
    - the backup (`supplier.backup_supplier_id`, if any);
    - the alternate route: an OPEN route whose `alternate_of_id` is a BLOCKED route of this supplier, if any;
    - the note and the user.
  - **Effects:** audit `SUPPLY.MITIGATION_ACTIVATED`; a SUPPLY entry on the incident ("Nairobi · Swiftline Couriers: mitigation activated · backup Kestrel Express Couriers on standby · Pouch via Southern Bypass in use."); `SUPPLY_UPDATED`.
- **`POST /api/supply/mitigations/{id}/stand-down`.**
  - The same roles; once (409 after).
  - Audit `SUPPLY.MITIGATION_STOOD_DOWN`; a SUPPLY entry when the incident is still ACTIVE.
  - It is allowed whether or not the disruption has cleared.
- **No outbound action:** no campaign, delivery, channel or partner request. A test checks that the notification tables do not change.
- **Permissions:** `GET /api/me/permissions?entity_type=supplier&entity_id=<id>` returns `activate_mitigation` and `stand_down`.

## 6. Who sees what (SUP-06)

- Every role reads the register, routes, statuses, banners, mitigations and the fuel stock (an operational picture, as Fleet).
- The names of the people who activated or stood down a mitigation are shown only when `evacuations.sees_names(name_scope(user), supplier.mission_id)` holds. Otherwise the screen says "Activated" or "Stood down", with the time.
- **Realtime:** `SUPPLY_UPDATED {supplier_id | route_id, status}` is added to `FORWARDED`. It carries ids and statuses only, never names (as SITE_UPDATED, TWN G-8).

## 7. The screen (SUP-05, §73 Q8)

- **"Supply Chain Risk"**, path `/supply`, icon `box`, under PLAN & INSIGHT after Document Expiry. The subtitle is "Third parties · Vendors & logistics routes".
- **API:**
  - `GET /api/supply/summary`: KPIs and banners;
  - `GET /api/supply/suppliers?mission=<code>`;
  - `GET /api/supply/suppliers/{id}`: the card, with dependencies, routes, fuel stock and mitigation;
  - `GET /api/supply/routes?mission=<code>`.
- **Layout:**
  - the impact banner(s);
  - KPIs:
    - "Third parties monitored": 52, "Across 36 missions";
    - "Critical (Tier 1) suppliers": 14;
    - "Impacted now": N, with "All in Nairobi" when they share one mission, or "No active disruption";
    - "Routes monitored": 37, "Courier, fuel, staff transport".
  - **Left:** "Suppliers & third parties" (ID, supplier, service, mission, tier, status), with a mission filter. The default filter is the mission of an ACTIVE incident with impacted suppliers, else all. Rows flash on change.
  - **Right, the selected supplier's card:**
    - status, tier and mission chips;
    - the detail, or "No active disruption. Last performance review N/100.";
    - the dependencies;
    - the fuel stock;
    - the mitigation (active since…, by whom within scope);
    - **Activate mitigation** or **Stand down**, from permissions.

    The default selection is the first impacted supplier, else the first row.
  - **Right, below:** "Logistics routes · <mission>": each route with its status (ALTERNATE shown) and the zone tag.

## 8. Scenario `NBO-SUPPLY` (SUP-07, §73 Q9)

| Scene | Events |
|---|---|
| 0 Ready | marker only |
| 1 Pouch blocked | reset Nairobi's routes and suppliers to the seed (G-6); then R-NBO-1 BLOCKED "Road closure CBD → JKIA; reroute via Southern Bypass, +55 min" |
| 2 Fuel and guards | SUP-121 DELAYED "Fuel delivery postponed 24 h"; R-NBO-3 DELAYED "Delivery postponed 24 h"; SUP-117 AT_RISK "18:00 shift change: 6 guards must cross the impact zone"; R-NBO-4 RESTRICTED "Restricted: route crosses the impact zone" |
| 3 Recovery | R-NBO-1, R-NBO-3 and R-NBO-4 OPEN; SUP-121 and SUP-117 NORMAL |

- It is played after NBO-CIVIL-UNREST scene 2, so INC-<year>-1042 is ACTIVE.
- **Timeline entries:** 1 in scene 1, 4 in scene 2 and 5 in scene 3, so 10 SUPPLY entries for a first run.
- **"Impacted":** 1 after scene 1 (SUP-104), 3 after scene 2, 0 after scene 3.
- It activates no mitigation, approves nothing and proposes nothing. The Response Planner reads no supply tables, and the Phase 1 scenario still starts with no active incident and an empty Decision Queue.

## 9. Acceptance specs (§72)

- **`sup-acceptance.spec.ts`** sorts after `scene5-` and before `ta-` by name, and is added to the `make acceptance` list in that place. Like `twn-`, it expects INC-<year>-1042 to be ACTIVE (after the Document Expiry spec). It checks:
  - **the register:** 52 / 36 / 14 / 0 impacted / 37; Nairobi NORMAL and OPEN; SUP-251 and SUP-262 WATCH; the dependencies;
  - **NBO-SUPPLY scenes 1–3:** ROUTE BLOCKED and ALTERNATE; the banner "3 third parties impacted by INC-<year>-1042", SUP-121 "72 h on-site stock" and SUP-117 AT RISK; the SUPPLY entries; then 0 impacted;
  - **mitigation:** the Duty Officer activates it for SUP-104 after scene 1, with the backup and the Southern Bypass recorded; the Viewer and the Cairo Head of Mission get 403; a second activation gets 409; it is stood down before the spec ends;
  - **names:** the Viewer sees "Activated" and no name;
  - **the audit:** the chain verifies.
- **The spec leaves everything as it found it:** statuses NORMAL and OPEN after scene 3, and no active mitigation. So `ta-`, `twn-`, `vip-` and `wx-` see the same world. They count only their own timeline types.

## 10. Gaps and conflicts, with proposed answers

| # | Gap | Proposed answer |
|---|---|---|
| G-1 | Only ten of the 52 suppliers are in the design | The seed meets the constraints in §2 (52, 36 missions, 14 Tier 1, the design's ten exact); the other names are fictional and generic ("<City> Courier Services"), and a test checks the counts. |
| G-2 | The design ticks "Backup supplier identified" for every supplier | Every Tier 1 and Tier 2 supplier has a backup with the same service (same mission or Global); Tier 3 may have none, and the card then shows the item open. |
| G-3 | 37 routes for 36 missions | Nairobi 4, plus one pouch route at 33 other missions; Geneva and New York (UN) have none (multilateral missions). |
| G-4 | Every Nairobi route starts inside INC-1042's 5 km zone | The zone tag is information only ("Through impact zone"); status comes from the feed. A future road network is out of scope. |
| G-5 | Which incident a mitigation records when a mission has several ACTIVE incidents | The most recent by `created_at`; the timeline entry goes to that one. |
| G-6 | A replay of NBO-SUPPLY | Scene 1 resets Nairobi's routes and suppliers to the seed first, as NBO-SITE (TWN G-9); resets to the same status write no timeline entry. Mitigations are people's records and are not reset. |
| G-7 | Which supplier shows the fuel stock | A supplier that runs a FUEL route of its mission; the generator is `GEN-<mission>` from Fleet. |
| G-8 | `SUPPLY_UPDATED` in realtime | Added to `FORWARDED` with ids and statuses only. Every role may see the picture (SUP-06), so forwarding to all sockets reveals nothing more. |
| G-9 | 🔒 scope | The migration (Prompt 90) and the service's mitigation actions and name scope (Prompt 91) are 🔒 under D-29. |

None of these needs a decision beyond the approved defaults; reply "approved" to take them as proposed.

## 11. Migration 0014 (Prompt 90, 🔒)

- **The tables:** PC-43 `supplier`, PC-44 `logistics_route` and PC-45 `supply_mitigation`.
  - FORCE RLS with `tenant_isolation`; only the grants proposed; no DELETE for any role.
  - CHECKs: tier 1..3; status and kind lists; score 0..100; the path is a LineString with 2..50 points; not its own backup or alternate.
- **Pinned `search_path` guards:**
  - same-tenant references;
  - a route's supplier is a supplier of the tenant; its alternate is a route of the same mission;
  - frozen columns (all but status and detail);
  - `status_at`, `activated_at` and `stood_down_at` written by the database;
  - a mitigation's backup is the supplier's own `backup_supplier_id`, and its route an alternate of one of the supplier's routes;
  - stand down once.
  - The partial UNIQUE index (`supplier_id`) WHERE `stood_down_at IS NULL`.
- **Tests (as `nexira_api`):** isolation, every refusal, the backup role reads, and the downgrade restores 0013 exactly.

## 12. Prompts

As `docs/prompts-pilot.md` Prompts 90–94: the migration (🔒); the service (🔒); the seed, feeds and NBO-SUPPLY; the screen; the acceptance. Each ships with its tests, and `make acceptance` passes at the end.
