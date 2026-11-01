# NEXIRA · Phase 1 decisions

**Status:** v0.2 · October 2026 · for review
**Applies to:** `docs/requirements.md` (Phase 1 PRD v0.1), `docs/schema/nexira_schema.sql` (v0.2), `AGENTS.md`, `docs/prompts.md`

This file settles conflicts and gaps between the Phase 1 PRD, the master specification, the schema and the demo. **Where this file disagrees with another document, this file wins** until that document is updated. Coding agents must cite the decision ID (D-xx) when they rely on one.

---

## 1. Security and data access

**D-01 · Database roles.** Three roles:

| Role | Login | Purpose |
|---|---|---|
| `nexira_owner` | yes | Owns all objects, runs Alembic migrations. Not a superuser. |
| `nexira_app` | no | Group role holding runtime grants. |
| `nexira_api` | yes | Member of `nexira_app`. The **only** user the backend connects as. |

PostGIS and pgcrypto are installed by the superuser in `infra/postgres/init.sql`, which also creates the three roles. Superusers and table owners bypass row-level security, so the API never connects as `postgres` or `nexira_owner`. Every tenant table also has `FORCE ROW LEVEL SECURITY`.

**D-02 · Setting the tenant.** At the start of every transaction the backend runs `SELECT set_config('app.tenant_id', :tenant_id, true)`. Do not use `SET LOCAL app.tenant_id = :param`, because `SET` cannot take bind parameters. With no tenant set, every tenant table returns zero rows rather than an error (`current_tenant_id()` returns NULL).

**D-03 · Tenant on every table.** All child tables also carry `tenant_id` and the same RLS policy: `user_role`, `trip_traveller`, `incident_signal`, `playbook_step`, `playbook_run_step`, `notification_delivery`, `proposal_approval`, `scenario_event`, `reference_counter`.

**D-04 · Identity and roles.**
- Keycloak (or the customer IdP) handles **authentication only**.
- The tenant is identified by the token **issuer**, with one Keycloak realm per tenant. The backend calls `resolve_tenant_by_issuer(iss)`, sets the tenant, then finds `app_user` by `sub`. That lookup function is the only cross-tenant read the API may do.
- **Roles and mission scope come from the `user_role` table.** Role claims in the token are ignored for authorisation. This replaces "roles come from the token" in the v0.1 rules file.
- MFA (OTP) is required in the pilot realm and optional in the local demo realm.

**D-05 · Mission-scoped roles.** `user_role.mission_id` NULL means "all missions" (HQ roles). To approve something tied to an incident, a user must hold the required role with `mission_id = incident.mission_id` or `mission_id IS NULL`. Example: the Nairobi Head of Mission can approve PB-07 step 7 for a Nairobi incident; the Cairo Head of Mission cannot.

**D-06 · Incident mission.** `incident.mission_id` is set by the exposure service to the mission whose nearest site is exposed. It is required before any mission-scoped approval can be decided. If no mission site is exposed, only unscoped (HQ) role holders can approve.

**D-20 · Audit chain lives in the database.**
- A `BEFORE INSERT` trigger assigns a gap-free `chain_seq` per tenant and computes `row_hash = sha256(prev_hash || canonical row)`, under a per-tenant advisory lock.
- `app/core/audit.py` only inserts rows; it never computes hashes. This changes v0.1 Prompt 3.
- `audit_verify_chain()` returns the first broken `chain_seq`, or NULL if the chain is intact.
- UPDATE, DELETE and TRUNCATE are blocked by triggers and by grants.
- The backend runs in READ COMMITTED isolation (the default).

**D-21 · Demo reset.** `make reset-demo` drops and recreates the **local/demo database** (Docker volume), then migrates and seeds. It never deletes audit rows inside a running database, and it does not exist in pilot or production configurations. The scenario API's `reset` resets the scenario run state only.

## 2. Intelligence, fusion and exposure

**D-08 · One severity scale.** `LOW`, `MODERATE`, `HIGH` and `CRITICAL` are used for signals, incidents, trips and missions. UI labels for **missions only**: LOW → "Normal", MODERATE → "Elevated". `severity_rank()` gives the order.

**D-09 · No OSINT in Phase 1.** The OSINT source is seeded with `is_enabled = false` and `takes_part_in_fusion = false`. Swahili posts belong to Phase 2. The Phase 1 fusion test uses exactly three provider signals.

**D-10 · Fusion rule and confidence formula.**
- A normalised signal joins an ACTIVE incident when all of these hold:
  - same `norm_category`
  - within **3 km** of `incident.location`
  - `occurred_at` within **60 min** of `incident.last_signal_at`
  - the source has `takes_part_in_fusion = true`
- Otherwise it opens a new incident. If several incidents match, it joins the nearest.
- `incident.location` is the location of the first signal and does not move.
- **Confidence formula:** `confidence = round(100 × (1 − Π(1 − rᵢ)))`, capped at 99.
  - `rᵢ` is `intel_source.reliability`, counted **once per distinct source** (the highest value if a source sent several signals).
  - Seed reliabilities: Dataminr 0.60, MAX 0.55, Riskline 0.55, all others 0.50.
  - Nairobi: 1 − (0.40 × 0.45 × 0.45) = **92**.

**D-11 · How severity is decided.** This replaces the v0.1 PRD acceptance criterion for INC-02.
1. Each signal is normalised **on its own** through its source's `severity_map`: Dataminr "High" → HIGH, MAX "Level 4" → HIGH, Riskline "Moderate" → **MODERATE**. A per-source map must never turn "Moderate" into HIGH.
2. `incident.signal_severity` = the highest of its linked signals. For Nairobi that is HIGH.
3. `incident.severity` = `signal_severity`, raised **one level** (to at most CRITICAL) when exposure includes a protected mission site (EMBASSY, CONSULATE or RESIDENCE) and `signal_severity` ≥ HIGH. An `ESCALATED` event goes on the incident timeline. Nairobi: HIGH → **CRITICAL**, which matches the demo's "CRITICAL · INC-2026-1042".
4. In the source-normalisation table on the incident screen, the last column is labelled **"Normalised (signal)"** and shows HIGH, HIGH, MODERATE. The incident header shows the incident severity.

**D-22 · Exposure rules.**

| Subject | Exposed when |
|---|---|
| PERSON | Active, with `person_location_current` within `impact_radius_m` (default 5,000 m) |
| SITE | Any site type within the radius |
| TRIP | Trip active today (`starts_on ≤ today ≤ ends_on`) and at least one traveller exposed |

**D-23 · Nairobi expected exposure.** This replaces "14 staff + 3 delegates + 2 sites".

| Subject | Expected |
|---|---|
| Staff (DIPLOMAT + LOCAL_STAFF) | 14 |
| Delegates | 3 |
| Registered citizens | 212 |
| **People total** | **229** (matches the demo's "229 recipients") |
| Sites | 3 rows: Embassy, Residence, Hotel |
| Trips | 1 (TRP-8812) |

The UI "Sites" count shows mission property only (site types other than HOTEL), which is **2**, matching the demo. The hotel appears with the delegates. To keep these counts exact, the seeder places **no other people** inside the Nairobi zone; there are no Nairobi dependants in Phase 1.

## 3. Agents and decisions

**D-12 · Fail closed.** An action type with no `action_policy` row is level 4 (advise only). The effective level is computed by a database trigger when the proposal is inserted (`max(agent level, policy floor)`), and is frozen after that. The app never writes `effective_level`.

**D-13 · Undo.** Level 1 (auto with notice) is allowed only for actions where `action_policy.is_undoable = true`; for anything else the trigger raises level 1 to level 2. Phase 1 undoable actions:

| Action | Undo means |
|---|---|
| `POST_INTERNAL_NOTE` | Note is marked retracted |
| `LOG_INFO` | Entry is marked retracted |

Messages to people outside the platform are never undoable.

**D-14 · Alternatives.**
- Each alternative is structured: `{"label", "action_type", "action_payload", "rationale"}`.
- "Use alternative" marks the original proposal SUPERSEDED and creates a **new proposal** from the same agent with the alternative's action.
- The new proposal goes through the policy engine on its own, so an alternative can never skip a higher approval level.

**D-15 · Translations.** In Phase 1 the citizen advisory uses **pre-written templates** in EN, AR, FR and SW, stored in seed data. Native speakers must review the AR, FR and SW text before any external demo; until then these files keep a `REVIEW REQUIRED` marker. LLM translation is Phase 2.

**D-16 · Approvals.**
- Each entry in `action_policy.approver_roles` is one approval step. An entry may list alternative roles separated by `|`, for example `DUTY_OFFICER|SECURITY_OFFICER`.
- Level 2 uses step 1 only. Level 3 uses steps 1 and 2; if the policy lists one step, step 2 is HQ_CRISIS_DIRECTOR.
- Approval rows are created by a database trigger. Steps are decided in order and only once.
- **The same person can never fill two steps of one proposal**, even if they hold both roles. A unique index enforces this.
- Mission scope follows D-05.
- Playbook approval gates (`playbook_run_step`) use the **same approval service** in `app/core/approvals.py`, so role and mission checks exist in one place only.

**D-17 · Kill switch.**
- `tenant.agents_paused = true` makes the database reject new proposals.
- Pending proposals stay visible and can still be decided by humans.
- Playbooks remain available for people to start manually.
- Pausing and resuming are audited.

**Phase 1 agent and policy seed.**

| Agent | Default level | Action type | Policy floor | Approver roles | Undoable |
|---|---|---|---|---|---|
| Watch Officer | 0 | `LOG_INFO` | 0 | — | yes |
| Exposure | 0 | `POST_INTERNAL_NOTE` | 0 | — | yes |
| Response Planner | 2 | `START_PLAYBOOK` | 2 | `DUTY_OFFICER\|SECURITY_OFFICER` | no |
| Communications | 2 | `SEND_EXTERNAL_MESSAGE` | 2 | `DUTY_OFFICER\|CONSULAR_OFFICER` | no |
| (test only) | — | `START_EVACUATION` | 3 | `HEAD_OF_MISSION`, `HQ_CRISIS_DIRECTOR` | no |
| Travel & Air (pilot, D-34) | 2 | `NOTIFY_TRAVELLERS` | 2 | `TRAVEL_DESK\|SECURITY_OFFICER` | no |
| Travel & Air (pilot, D-34) | 2 | `CANCEL_TRIP` | 2 | `SECURITY_OFFICER` | no |
| Travel & Air (pilot, D-34) | 2 | `ADVISE_REBOOKING` | 4 (no policy, D-12) | — | — |

## 4. Other data rules

**D-07 · Check-in history.** `checkin_response` keeps every answer, and the latest one counts (`v_checkin_latest`). Non-responders are escalated after `notification_campaign.escalate_after_s` (default 600 s; the scenario uses 20 s). In Phase 1, escalation writes an `ESCALATION` incident event and an audit row; no external call is made.

**D-18 · Reference numbers.** References come from `next_reference(prefix, with_year)`, which uses a counter table that is safe under concurrent writes. The seed sets the INC counter for the current year to 1041 and the NTF counter to 3100, so the first incident is `INC-<year>-1042` and the first campaign is `NTF-3101`. Tests check the pattern, not a hard-coded year.

**D-27 · KPIs are computed from data.** OPS-03 requires real values, so numbers such as "18,406 registered citizens" or "1,338 personnel" will differ from the static demo. That is expected. Seed scale: 36 missions, about 1,300 staff and delegates, 212 Nairobi citizens, and about 1,000 citizens spread across other missions.

**D-28 · Mobile check-in.** Phase 1 accepts responses through the API, the simulator, and a **phone preview panel** on the Check-in screen (as in the demo). A real mobile app or SMS reply is Phase 2. The master spec's CHK-04 is met in Phase 1 by the preview panel only.

## 5. UI, map and naming

**D-25 · UI reference and scope.** (Amended by D-30 for the pilot.) The UI reference is **`NEXIRA_Demo_Full 3.html`** (the version with the Decision Queue), stored as `docs/design/NEXIRA_Demo_Full.html`. Treat it as a **visual reference only**: do not port its code, state handling or patching pattern.

| Build in Phase 1 | Do not build in Phase 1 |
|---|---|
| Decision Queue (home), AI Agents, Global Operations, Incidents, People & Sites, Response Playbooks, Safety Check-in, Audit view (admin), Presenter bar (demo mode only) | Every other screen in the demo: Journey, Air Travel, OSINT, Cyber-Physical, Health, Hazards, Mass Notification composer, Evacuation, Consular, VIP, Fleet, Assistance, Site Twin, Copilot chat, Wellbeing, Continuity, Predictive, Supply Chain, Documents, Exercise, After-Action Review, Executive, Integrations, Deployment |

**D-24 · Map tiles.** Tiles are self-hosted **PMTiles**: a world basemap for zoom 0–6 plus a Nairobi extract for zoom 0–15. They are built by `make tiles` and served by the frontend container. No external tile, font or sprite URLs are allowed; the map must work with no internet connection. OpenStreetMap data requires "© OpenStreetMap contributors" to be shown on the map.

**D-19 · Vendor names and wording.**
- Simulated sources are shown as "<Name> (simulated)" and are never labelled "Connected".
- Remove Palantir product terms from the UI ("AIP", "Object explorer"). Blueprint styling is fine.

## 6. Delivery

**D-26 · Build order.** Prompts follow PRD milestones M1–M6, and screens are built in the same milestone as their backend (vertical slices). See `docs/prompts.md`.

**D-29 · Human review gates.** A named human reviewer (not the coding agent) signs off before merging any change to:
- database roles, RLS policies or grants
- `app/core/security.py`, `app/core/approvals.py`, `app/core/audit.py`
- the policy engine and executor in `app/modules/agents`
- channel adapters

Record each sign-off in the PR.

## 6a. Pilot scope (after Phase 1)

**D-30 · Pilot modules.** This amends D-25. Agreed with the product owner on 2026-10-25, after Phase 1 was complete (Prompts 0–16). The pilot adds modules from the master specification's Phase 2 that can be built and demonstrated on simulated data. The modules that need a real feed or a local model wait.

| Build for the pilot, in this order | Wait for real feeds or a local model |
|---|---|
| 1. **Mass Notification** (NTF), including per-mission message templates (D-31) | AI Risk Copilot (COP), Briefing agent: need a local model server (AGR-08) |
| 2. **Journey Management** (JRN) | Local-Language OSINT (OSN): needs a real feed, licensing and a privacy review |
| 3. **Air Travel Tracking** (AIR), on simulated flights | Integrations console (INT): needs real connectors |
| 4. **Travel & Air agent** | Real SMS, email or WhatsApp delivery: channels stay simulated (D-19, AGENTS.md) |
| 5. **Assistance Partners** (AST): asked for by the pilot customer (D-36) | |
| 6. **Weather** (WX), simulated: current conditions and severe-weather warnings (D-35) | |
| 7. **Document Expiry** (DX), simulated (D-37) | |
| 8. **Natural Hazards & Climate** (HZ), simulated (D-38) | |
| 9. **Health Intelligence** (HL), simulated (D-39) | |
| 10. **Evacuation Management** (EV), simulated (D-40) | |
| 11. **Fleet & Assets** (FLT), simulated (D-41) | |
| 12. **VIP & Delegation Protection** (VIP), simulated (D-42, proposed) | |

Rules:
- **Requirements before code.** Each module gets requirements in `docs/requirements-pilot.md` and prompts in `docs/prompts-pilot.md`, approved by the product owner before any code is written. Only Mass Notification is written so far.
- **Same process as Phase 1.** One branch and PR per prompt. 🔒 prompts follow D-29. Schema changes go through `docs/schema/proposed-changes.md` first. Simulated data only.
- **The Phase 1 acceptance scenario (§7) must keep passing** after every pilot prompt.

**D-31 · Mass Notification rules.** Requirements MN-01 to MN-12 in `docs/requirements-pilot.md`.
- **Draft, then send.** A user composes a campaign as a DRAFT. Nothing is queued until it is sent. Sending uses the same campaign and delivery tables and the same simulated adapter as playbooks and agents.
- **Second person for citizens.** A campaign whose audience includes **citizens** needs a **second person** to approve it before it is sent. The approver is a different user from the author and holds `DUTY_OFFICER|CONSULAR_OFFICER`, checked through `app/core/approvals.py` (D-05, D-16). A campaign to staff and delegates only can be sent by its author, if the author holds `DUTY_OFFICER|SECURITY_OFFICER`. Every step is audited.
- **Templates per mission, with a fallback.** Message templates are stored per mission and campaign kind, with a generic template as the fallback. PB-07 and the Communications agent take the advisory from the incident's mission template. This replaces the advisory text that is fixed to Nairobi in the PB-07 seed.
- **Translations.** D-15 still applies: pre-written translations only, no machine translation. A translation not yet reviewed keeps its `REVIEW REQUIRED` marker. With `APP_ENV=pilot`, a campaign cannot be sent with an unreviewed translation.
- **Test send.** "Send to self" renders the message for each channel in the preview panel and writes an audit row. It creates no deliveries.

**D-32 · Journey Management rules.** Approved by the product owner on 2026-10-26 (PR #24), with the defaults in `docs/requirements-pilot.md` §13. Requirements JR-01 to JR-09.
- **Created on the traveller's behalf** by TRAVEL_DESK or DUTY_OFFICER, as a DRAFT. No traveller self-service in the pilot.
- **Risk decides the approver.** At submission the trip takes the destination risk (D-08 scale): the country's simulated base level (PC-16) raised to the worst ACTIVE incident in that country.
  - LOW: approved on submission (audited).
  - MODERATE: TRAVEL_DESK or SECURITY_OFFICER.
  - HIGH and CRITICAL: SECURITY_OFFICER.
  - Never the requester (submitting is the first step, as in D-31 plan G-2), always through `app/core/approvals.py`. Mission scope: the mission in the destination country, else HQ only (D-06).
- **Checklist before risky travel.** Four items are ticked by users (security briefing, insurance and medical cover, emergency contacts, check-in schedule); a HIGH or CRITICAL trip cannot be approved while any is open. The fifth, security approval, is set by the approval.
- **Flag, don't revoke.** An approved trip whose destination risk rises is flagged with the new level; it is not paused or cancelled automatically. The Travel & Air agent (pilot module 4) will propose what to do.
- **What is approved is what travels.** Travellers, destination, dates and itinerary are frozen once submitted; changes mean cancel and re-plan. The database backs this, as PC-10..12 do for campaigns.

**D-33 · Air Travel Tracking rules.** Approved by the product owner on 2026-10-27 (PR #30), with the defaults in `docs/requirements-pilot.md` §18. Requirements AT-01 to AT-08.
- **Simulated flights only.** A flight tracker in the worker plays the part of a flight-data provider; no external service is called (AGENTS.md). Positions and statuses are labelled simulated (D-19). A real provider later replaces only the tracker.
- **Only our travellers' flights.** A flight is tracked only for a FLIGHT segment of an APPROVED trip that has a flight number and airports. There is no view of other flights.
- **Never VIP or ministerial movements.** A trip marked *restricted* at planning has no tracked flights at all: nothing is stored, shown, published or audited about its flights. The database refuses such a flight (PC-19).
- **Disruptions are shown, not acted on.** Delays (30 minutes or more), holding, diversions and cancellations are flight events, shown live. Proposals to rebook, book hotels or notify travellers come with the Travel & Air agent (pilot module 4).
- **Landing moves the travellers.** On landing, each traveller gets a `FLIGHT` location observation at the landing airport, through the existing location service.

**D-34 · Travel & Air agent rules.** Approved by the product owner on 2026-10-27 (PR #36), with the defaults in `docs/requirements-pilot.md` §23. Requirements TA-01 to TA-09.
- **Level 2, always a person.** The agent proposes; a Travel Desk or Security Officer approves (D-16, through `app/core/approvals.py`). Nothing it proposes runs on its own.
- **Only what the platform can do.** Notify a trip's travellers (a staff campaign, simulated channels) or cancel a trip that has not started. Rebooking and hotels are advice only: the pilot books nothing.
- **Flag, then a person decides.** D-32 still holds: a risen risk never cancels a trip by itself; the agent's CANCEL_TRIP proposal is a suggestion with "notify instead" as the alternative.
- **Never about restricted trips** (D-33).
- Changes to its action types, policies and executors need a named human sign-off (D-29).

**D-35 · Weather (simulated).** Approved by the product owner on 2026-10-30 (PR #43), with the defaults in `docs/requirements-pilot.md` §28. Requirements WX-01 to WX-08. Amends D-30 by adding Weather to the pilot.
- **Simulated only.** Current conditions and warnings come from a simulated xWeather feed in the worker, labelled simulated (D-19); no weather provider is called at runtime. A real provider later replaces only the feed.
- **Warnings are intelligence.** Severe-weather warnings are signals of the existing xWeather source and go through fusion, exposure, agents and playbooks unchanged. Weather incidents use category-sized radii (WX-04).
- **People decide.** PB-06 is proposed by the Response Planner and approved by a person (D-16); citizen advisories still need a second person (D-31).

**D-36 · Assistance Partners (simulated).** Approved by the product owner on 2026-10-30 (PR #49), with the defaults in `docs/requirements-pilot.md` §33. Requirements AS-01 to AS-08.
- **Simulated partners.** Partners are fictional and answer through a simulated partner adapter in the worker, labelled simulated (D-19). No partner system, email or phone is contacted. A real integration later replaces only the adapter, which is reviewed like a channel adapter (D-29).
- **People request.** Only a person with the right role requests support, or a playbook step a person approved (D-16). Agents never request; the platform only suggests a partner for an SOS.
- **Share the minimum.** A request carries what the partner needs to help (AS-08) and never a restricted traveller (D-33).

**D-37 · Document Expiry (simulated).** Approved by the product owner on 2026-10-30 (PR #57), with the defaults in `docs/requirements-pilot.md` §38. Requirements DX-01 to DX-09 in `docs/requirements-pilot.md`, with the defaults in §38. Amends D-30 by adding Document Expiry to the pilot.
- **No document numbers.** The platform stores the type, issuing country and valid-until date of a document, never its number, a scan or a photo (DX-01).
- **People decide.** The Compliance agent only proposes, at level Approve or higher; renewals and reminders are started by a person or by a proposal a person approved (D-12, D-16).
- **Further modules.** On 2026-10-30 the product owner asked for these modules after the UI work, in this order: Document Expiry, Natural Hazards, Health Intelligence, Evacuation Management, Fleet, VIP Protection, Site Twin, Supply Chain, Wellbeing, Exercises, After-Action Review, Predictive Risk, Executive Overview, AI Risk Copilot chat. Each still needs its own requirements approved before code (D-30). The AI Risk Copilot needs the local model server (D-30, AGR-08).

**D-38 · Natural Hazards & Climate (simulated).** Approved by the product owner on 2026-10-31 (PR #63), with the defaults in `docs/requirements-pilot.md` §43. Requirements HZ-01 to HZ-11 in `docs/requirements-pilot.md` §39–43, with the defaults in §43. Amends D-30 by adding Natural Hazards & Climate to the pilot.
- **Hazards are intelligence.** Earthquakes, cyclone forecasts, wildfire and air quality are signals and incidents through the existing pipeline, as Weather's warnings are (D-35). There is no separate hazard store.
- **Arming is a scheduled playbook run.** An armed playbook starts by itself at the time a person or an approved proposal chose, and stays a normal run (gates, second person for citizens). Agents only propose arming, at level Approve or higher (D-12, D-16).
- **Climate scores are illustrative.** They are labelled simulated, shown for planning, and used by no rule or agent.

**D-39 · Health Intelligence (simulated).** Approved by the product owner on 2026-10-31 (PR #70). Requirements HL-01 to HL-10 in `docs/requirements-pilot.md` §44–48, with the defaults in §48. Amends D-30 by adding Health Intelligence to the pilot.
- **Advisories are reference intelligence, not incidents.** Outbreaks and health advisories are a country-level list with their own updates; they are not fused into incidents and start no playbook.
- **No person-level health data.** Staff health readiness is counts per mission only. Medical records, blood types and per-person vaccination records are out of the pilot; recording them needs a privacy review and a lawful basis first.
- **People decide.** A health advisory is a Mass Notification campaign under D-31 (a second person for citizens). The Communications agent only proposes it, at level Approve or higher (D-12, D-16).

**D-40 · Evacuation Management (simulated).** Approved by the product owner on 2026-11-01 (PR #77). Requirements EV-01 to EV-10 in `docs/requirements-pilot.md` §49–53, with the defaults in §53. Amends D-30 by adding Evacuation Management to the pilot, and amends §7 scene 5: the `START_EVACUATION` executor activates the mission's plan instead of the Phase 1 stub.
- **Two people activate.** An evacuation is activated only by a Head of Mission and an HQ Crisis Director, two different people, through `app/core/approvals.py` (AGT-04, D-05). The database refuses an activator who is also the requester.
- **The manifest is locked at activation** from who is there and who has not confirmed safe; nobody is added or removed by hand in the pilot.
- **Simulated movement.** Plans, the muster-point scanner, the charter and the convoy are simulated (D-19); partners are requested through the Assistance Partners service and get no names (D-36). The movement message is a Mass Notification campaign with its own second person (D-31).

**D-41 · Fleet & Assets (simulated).** Approved by the product owner on 2026-11-01 (PR #84). Requirements FLT-01 to FLT-08 in `docs/requirements-pilot.md` §54–58, with the defaults in §58. Amends D-30 by adding Fleet & Assets to the pilot.
- **Simulated telematics.** Assets, positions, fuel and the workshop are simulated (D-19); no real provider is called.
- **Derived states are not stored.** Blocked (driver SOS), in an impact zone and assigned to an evacuation are worked out from the check-in, incidents and evacuations, so they clear by themselves.
- **People decide.** Status and maintenance are changed by people with a responder role, through `app/core/approvals.py`; a capacity shortfall only suggests a partner. No agent acts on vehicles.

**D-42 · VIP & Delegation Protection (simulated). Proposed, not yet approved.** Requirements VIP-01 to VIP-08 in `docs/requirements-pilot.md` §59–63, with the proposed defaults in §63. Amends D-30 by adding VIP & Delegation Protection to the pilot.
- **Restricted by default.** A visit exists only for the protection roles and the host mission's Head of Mission; for everyone else it does not exist (D-33's principle for restricted trips).
- **Never a position.** No live location of a principal, protection team or motorcade is stored or shown (AIR-06); "live" means programme status only.
- **People decide.** Segment risk is worked out from data; a programme change needs two people through `app/core/approvals.py` (D-05). No agent acts on visits.

---

## 7. Phase 1 acceptance scenario: NBO-CIVIL-UNREST

The master spec's scenario covers all four phases. This is the **Phase 1 subset**, and it is what M6 acceptance tests.

**Seed coordinates (WGS84 latitude, longitude)**

| Item | Location | Distance from epicentre |
|---|---|---|
| Epicentre / incident location (first signal, Dataminr) | −1.2838, 36.8245 | 0 |
| Embassy | −1.2950, 36.8080 | 2.2 km |
| Ambassador's Residence | −1.2745, 36.7935 | 3.6 km |
| Hotel (trade delegation) | −1.2975, 36.8240 | 1.5 km |
| Signal 2 (MAX, Upper Hill) | −1.2990, 36.8150 | 2.0 km |
| Signal 3 (Riskline, city centroid) | −1.2864, 36.8172 | 0.9 km |
| Hana Takeda (Westlands, CALENDAR_HR, 72%) | −1.2676, 36.8108 | 2.4 km |
| Peter Mwangi (Haile Selassie Ave, MOBILE_GPS, 91%) | −1.2985, 36.8195 | 1.7 km |
| Other 11 staff | within 0.8 km of the Embassy | < 3.1 km |
| Paris control signal (TRANSPORT_STRIKE) | 48.86, 2.35 | 6,484 km |

**Scenes**

| Scene | What happens | Expected result (automated check) |
|---|---|---|
| 0 Calm | Seeded state | No ACTIVE incidents; Decision Queue empty; KPIs computed; NBO mission LOW |
| 1 Signals fused | 3 Nairobi signals arrive within 2 min; Paris signal arrives too | One incident `INC-<year>-1042`, CIVIL_UNREST, confidence **92**, signal severity HIGH; Paris signal is a separate incident; Watch Officer `LOG_INFO` proposal AUTO_EXECUTED |
| 2 Impact | Exposure is computed | 229 people (14 / 3 / 212), 3 sites, 1 trip; incident severity **CRITICAL** (D-11); `incident.mission_id` = NBO; Exposure agent note AUTO_EXECUTED; Response Planner `START_PLAYBOOK` PB-07 proposal PENDING |
| 3 Playbook | Duty Officer approves the proposal; PB-07 runs | Steps 1–6 DONE in order with timestamps; step 5 creates the CHECKIN campaign (229 recipients); step 7 AWAITING_APPROVAL; Duty Officer approving step 7 → **403**; Nairobi Head of Mission approves → step 7 DONE; step 8 (BRIEFING) writes an incident event only |
| 3b Advisory | Step 4 (shelter-in-place) finishes, so Communications proposes `SEND_EXTERNAL_MESSAGE` to citizens | Proposal PENDING with EN/AR/FR/SW templates; Duty Officer approves → ADVISORY campaign through the simulated adapter; nothing leaves the system |
| 4 Check-in | Simulator sends responses | Personnel: **15 safe, 1 need help (Peter Mwangi), 1 pending (Hana Takeda) → escalated after 20 s**. Citizens: 168 safe, 4 need help, 40 pending |
| 5 Decisions (test fixture) | A `START_EVACUATION` proposal is injected by the test, not by an agent | Nairobi Head of Mission approves → not executed; the same person trying step 2 → rejected; HQ Crisis Director approves → executed through the service layer: it activates EVP-NBO (D-40; in Phase 1 a stub, kept for a mission with no plan) |
| 6 Review | Incident set to MONITORING by a user | Timeline shows every step; `audit_verify_chain()` returns NULL; every decision has a logged-in user with the right role |

---

## 8. Schema changes from v0.1

| # | Change | Decision |
|---|---|---|
| 1 | `FORCE ROW LEVEL SECURITY`; NULL-safe `current_tenant_id()`; `WITH CHECK` on policies | D-01, D-02 |
| 2 | `tenant_id` and RLS added to 9 child tables | D-03 |
| 3 | `tenant.oidc_issuer` and `resolve_tenant_by_issuer()` (security definer) | D-04 |
| 4 | `tenant.agents_paused*` columns (kill switch) | D-17 |
| 5 | `user_role`: surrogate key, `UNIQUE NULLS NOT DISTINCT (user_id, role_id, mission_id)` | D-05 |
| 6 | `app_user.external_id` required and unique per tenant | D-04 |
| 7 | `mission.risk_level` uses the single severity scale | D-08 |
| 8 | `site.last_drill_on` (PPL-04: last drill) | PRD PPL-04 |
| 9 | `intel_source.reliability`, `takes_part_in_fusion`; `raw_signal.external_id` required | D-09, D-10 |
| 10 | `incident.mission_id`, `signal_severity`, `last_signal_at` | D-06, D-10, D-11 |
| 11 | `playbook_run.started_by_type`, `proposal_id`; one live run per playbook and incident | D-16 |
| 12 | `checkin_response` keeps history (unique constraint removed), plus `v_checkin_latest` | D-07 |
| 13 | `notification_campaign.escalate_after_s`; channel list checked | D-07 |
| 14 | `action_policy.is_undoable`; checks for the number of approver roles per level | D-13, D-16 |
| 15 | `agent_proposal.proposal_key` (idempotency), `superseded_by`, `edited_payload`; triggers for level, freeze and approval rows | D-12, D-14, D-16 |
| 16 | `proposal_approval`: distinct-approver index, in-order trigger | D-16 |
| 17 | `reference_counter` and `next_reference()` | D-18 |
| 18 | `audit_log.chain_seq`; hash chain trigger; TRUNCATE blocked; `audit_verify_chain()` | D-20 |
| 19 | Grants for `nexira_app`; audit log is insert/read only | D-01 |

The schema has been applied to PostgreSQL 16 + PostGIS 3 (arm64) as `nexira_owner`, and the 35 checks in `docs/schema/checks/` pass when connected as `nexira_api`: tenant isolation, audit chain (including 40 concurrent writers), policy levels, two-person rule, kill switch and check-in history. Prompt 2 turns these into pytest tests.

## 9. Still open (needs a person, not a decision)

1. **Tooling approval:** confirm with the company that the AI coding tools and repository host you use are approved for these Internal documents (master spec assumption 12.1).
2. Pilot customer IdP, hosting environment and classification level.
3. First real intelligence feed and messaging gateway (Phase 2).
4. Who holds the HQ Crisis Director role.
5. Arabic UI in Phase 1 or Phase 2. Current assumption: Phase 2, with the layout kept RTL-ready.
6. Native-speaker review of AR, FR and SW templates (D-15).
7. Packaging: Phase 1 does not deliver a complete "Essentials" tier, because Mass Notification is Phase 2. Either accept Phase 1 as a pilot only, or move a basic notification composer into Phase 1.
