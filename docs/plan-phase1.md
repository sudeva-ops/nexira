# NEXIRA · Phase 1 plan

**Status:** draft from Prompt 0 · 2026-10-24 · for review. No code yet.
**Read:** `AGENTS.md`, `docs/decisions.md` (v0.2), `docs/requirements.md` (PRD v0.1), `docs/schema/nexira_schema.sql` (v0.2), `docs/schema/checks/`, and a skim of `docs/design/NEXIRA_Demo_Full.html`.

---

## 1. Phase 1 scope in 10 bullets

1. **Core loop on simulated data:** detect → assess exposure → recommend → a human decides → act → account for people → audit. Proven end to end by the NBO-CIVIL-UNREST scenario, scenes 0–6 (decisions.md §7).
2. **Platform:** Keycloak OIDC login (authentication only). Tenant comes from the token issuer; roles and mission scope come from `user_role` (D-04, D-05). PostgreSQL RLS with `FORCE`, and the API connects as `nexira_api` only (D-01, D-02, D-03).
3. **Audit:** an append-only audit log, hash-chained by the database (D-20). Every state-changing action writes a row through `app/core/audit.py`. There is an admin Audit view and a verify endpoint.
4. **Intelligence:** a simulated connector writes raw signals into Redis Streams. Each signal is normalised on its own through its source's maps (D-11). Fusion uses 3 km / 60 min with the D-10 confidence formula (Nairobi = 92). OSINT is disabled (D-09).
5. **Exposure:** PostGIS `ST_DWithin` finds exposed people, sites and trips (D-22). The service sets `incident.mission_id` (D-06) and raises severity one level when a protected site is exposed (D-11). Nairobi gives 229 people, 3 sites and 1 trip, at CRITICAL (D-23).
6. **Response playbooks:** PB-07 has 8 ordered steps. Step 7 is a mission-scoped HEAD_OF_MISSION gate. Each step writes the timeline and the audit log. All approvals go through the single approval service `app/core/approvals.py` (D-16).
7. **Safety check-in:** campaigns go out through a *simulated* channel adapter only. Responses come from the API, the simulator and the phone preview panel (D-28). The latest answer counts (D-07), non-responders are escalated, and the summary shows personnel and citizens separately.
8. **Agents and the Decision Queue:** four rule-based agents (Watch Officer, Exposure, Response Planner, Communications). The database sets the effective level and fails closed (D-12). The queue supports approve, edit-approve, reject with a reason, use alternative (D-14) and undo (D-13). It enforces the two-person rule and deadlines/expiry, and has a kill switch (D-17). The executor calls the same service functions that users call.
9. **Screens:** only Decision Queue (home), AI Agents, Global Operations (MapLibre + self-hosted PMTiles, offline, D-24), Incidents, People & Sites, Response Playbooks, Safety Check-in, Audit view, and the Presenter bar in demo mode (D-25). Blueprint dark styling. Updates are pushed over WebSocket within 2 s.
10. **Delivery:** a Docker monorepo with docker-compose locally, CI with real PostGIS tests, built as vertical slices M1–M6 (D-26). There are 🔒 human sign-off gates (D-29), and M6 ends with a Helm chart, a backup/restore runbook and an ASVS L2 gap list. No external AI, tile, SMS or email calls at runtime.

---

## 2. Repository structure

```
nexira/
├── AGENTS.md                       # + .github/copilot-instructions.md, .cursor/rules/nexira.mdc (identical)
├── README.md
├── Makefile                        # up, down, test, lint, migrate, seed, reset-demo, tiles
├── .env.example
├── .github/workflows/ci.yml        # backend + frontend lint/test, PostGIS service container
│
├── backend/
│   ├── pyproject.toml              # ruff, mypy --strict, pytest config
│   ├── alembic.ini
│   ├── migrations/
│   │   ├── env.py                  # uses MIGRATIONS_DATABASE_URL (nexira_owner)
│   │   └── versions/0001_initial_schema_v0_2.py
│   └── app/
│       ├── main.py                 # FastAPI app, routers, startup role check
│       ├── core/
│       │   ├── config.py           # pydantic-settings; DATABASE_URL, MIGRATIONS_DATABASE_URL, …
│       │   ├── db.py               # async engine (nexira_api), per-tx set_config (D-02), role guard
│       │   ├── security.py   🔒    # OIDC JWT validation, issuer → tenant, app_user lookup
│       │   ├── approvals.py  🔒    # user_has_role, require_roles, decide() — the only approval logic
│       │   ├── audit.py      🔒    # write(...) — insert only
│       │   ├── events.py           # Redis Streams publish/consume, event envelope (incl. tenant_id)
│       │   ├── realtime.py         # /ws endpoint, auth, tenant-scoped fan-out
│       │   ├── llm.py              # local gateway client + stub
│       │   └── errors.py           # DB constraint/trigger errors → 403/409
│       ├── modules/
│       │   ├── tenancy/            # tenant (kill switch read), app_user, role, user_role, /api/me, /api/me/permissions
│       │   ├── people/             # mission, site, person, location_observation, person_location_current, confidence engine
│       │   ├── travel/             # trip, trip_traveller
│       │   ├── intel/              # sources, raw signals, normaliser, fusion, exposure.py, incidents
│       │   ├── playbooks/          # definitions, runs, step engine
│       │   ├── notifications/      # campaigns, deliveries, channel adapters 🔒 (simulated only)
│       │   ├── checkin/            # responses, summary, escalation
│       │   ├── agents/             # proposals, policy engine 🔒, executor 🔒, agents/{watch_officer,exposure,response_planner,communications}.py
│       │   ├── audit/              # GET /api/audit, /api/audit/verify (router over core/audit.py)
│       │   └── scenarios/          # scenario, scenario_event, scenario_run, player API
│       │   # each: models.py, schemas.py, service.py, router.py, tests/
│       ├── workers/                # consumers + background jobs (expiry, escalation, delivery sim)
│       └── tests/                  # cross-cutting: RLS-per-table, schema checks port, migrations
│
├── simulator/
│   ├── pyproject.toml
│   └── nexira_sim/
│       ├── seed/                   # deterministic (seed=42) loaders via backend service layer
│       │   └── templates/          # advisory EN/AR/FR/SW (AR/FR/SW marked REVIEW REQUIRED, D-15)
│       ├── scenarios/nbo_civil_unrest.py
│       └── player.py               # publishes scenario events to Redis Streams
│
├── frontend/
│   ├── package.json, vite.config.ts, tsconfig.json, .eslintrc
│   ├── public/tiles/ (mounted)     # PMTiles + local glyphs/sprites, not committed
│   ├── src/
│   │   ├── app/                    # shell, left nav (Phase 1 screens only), header (GST/UTC clock, user, pending pill)
│   │   ├── auth/                   # Keycloak OIDC
│   │   ├── api/                    # typed client, TanStack Query hooks, useRealtime()
│   │   ├── map/                    # MapLibre setup, offline style
│   │   ├── screens/{decision-queue,agents,global-ops,incidents,people-sites,playbooks,checkin,audit}/
│   │   └── presenter/              # rendered only when VITE_DEMO_MODE=true
│   └── e2e/                        # Playwright
│
├── infra/
│   ├── docker-compose.yml          # postgres, redis, keycloak, backend, workers, frontend
│   ├── postgres/{Dockerfile,init.sql}   # postgres:16-bookworm + postgis (arm64-native); roles + extensions
│   ├── keycloak/nexira-demo-realm.json  # fictional demo users, fixed user ids
│   ├── tiles/                      # build output of `make tiles` (git-ignored)
│   └── helm/                       # M6
│
└── docs/
    ├── decisions.md, requirements.md, prompts.md, plan-phase1.md
    ├── schema/{nexira_schema.sql, proposed-changes.md, checks/}
    ├── design/NEXIRA_Demo_Full.html
    ├── reference/master-requirements.md
    └── security-review.md          # M6
```

**Notes**
- `workers/` is a second entry point of the same backend image, so consumers and jobs reuse the services and `db.py`. It is not a separate codebase.
- `.cursor/rules/nexira.mdc` does not exist yet. AGENTS.md asks for it, and Prompt 1 adds it.

---

## 3. Conflicts and gaps that decisions.md does not settle

Each item gives a proposed resolution. Items marked **(schema)** would need an entry in `docs/schema/proposed-changes.md` and human approval before any migration.

### 3.1 Security, tenancy and data access

**G-01 · Background workers cannot discover tenants.** Workers handle consumers, proposal expiry, check-in escalation and the delivery simulator. They run with no request and therefore no token. `nexira_api` cannot read `tenant` without a tenant set, and D-04 allows only `resolve_tenant_by_issuer` as a cross-tenant read.
→ *Proposed:* every Redis event envelope carries `tenant_id`, and consumers set it per event. Time-based jobs get their tenant list from config (`WORKER_TENANT_IDS`), which is enough for one tenant in Phase 1. A `SECURITY DEFINER list_tenant_ids()` function would go into proposed-changes for Phase 2 **(schema)**.

**G-02 · Grants and RLS for future tables.** The schema grants `ON ALL TABLES` once, at migration time. Tables added by later migrations get no `nexira_app` grants and no RLS by default.
→ *Proposed:* each later migration adds grants and RLS explicitly. A catalogue test fails if any `public` table with a `tenant_id` column lacks `relrowsecurity AND relforcerowsecurity` and the `tenant_isolation` policy. A second test checks that `audit_log` has no UPDATE/DELETE/TRUNCATE grant.

**G-03 · The tenant row can't be seeded as `nexira_api`.** Prompt 4 says the seed loads "through the backend service layer", but `nexira_api` has no INSERT on `tenant`.
→ *Proposed:* `make seed` runs a small bootstrap as `nexira_owner` that inserts the tenant row only, the same way as `checks/10_setup_owner.sql`. Everything else goes through the services as `nexira_api`.

**G-04 · Keycloak issuer mismatch inside Docker.** *(Implemented in Prompts 1 and 3.)* The token `iss` is whatever URL the browser used, for example `http://localhost:8080/realms/nexira-demo`. The backend reaches Keycloak as `http://keycloak:8080`. Since the tenant is chosen by exact issuer match (D-04), the two must agree.
→ *Proposed:* pin `KC_HOSTNAME` so the issuer is fixed. Seed `tenant.oidc_issuer` from `OIDC_ISSUER`, and fetch JWKS from a separate `OIDC_JWKS_URL` (the internal hostname). Validate `iss` exactly; never derive it from the request.

**G-05 · Linking Keycloak users to roles.** *(Implemented in Prompt 3.)* Prompt 3 creates `app_user` on first login, but someone has to assign `user_role` to demo users before they can act.
→ *Proposed:* the realm export fixes each demo user's `id` (which becomes `sub`). The seed creates the matching `app_user` (`external_id = sub`) and `user_role` rows. A user created on first login who has no seeded roles gets no roles, so they have no access beyond read-only screens (or none). Users are never given VIEWER by default.

**G-06 · The audit trail panel conflicts with ADMIN-only audit access.** *(Implemented in Prompt 3.)* PB-04 and Prompt 11 show an audit trail panel on the playbook run screen for Duty Officers. Prompt 3 makes `GET /api/audit` ADMIN-only.
→ *Proposed:* `GET /api/audit?entity_type=&entity_id=` is allowed for any role that can read that entity. The unfiltered Audit view and `GET /api/audit/verify` stay ADMIN-only.

**G-07 · `GET /api/me/permissions` is used but never specified.** Prompts 11 and 14 rely on it, and no prompt defines it.
→ *Proposed:* define it in Prompt 3 and extend it in Prompts 9 and 12. Shape: `GET /api/me/permissions?entity_type=&entity_id=` returns the allowed actions, for example `{"approve_step": [...step_ids], "decide_proposal": [...]}`. It is computed by calling `approvals.can_decide(...)`, the same code as `decide()`, so the UI and the backend cannot drift apart.

**G-08 · Mapping database errors to HTTP codes.** Some rules are enforced only by triggers or indexes. Examples: the distinct-approver index, step order, the kill switch, and frozen proposals.
→ *Proposed:* `approvals.decide()` checks role, scope, order and the distinct-person rule in Python **first** and returns 403/409. The database constraints are the backstop. `core/errors.py` maps any trigger exception or unique violation that still gets through to 409 and never to 500. Tests cover both layers.

### 3.2 Seed data and the scenario

**G-09 · The Ambassador is missing from the coordinate table.** *(Implemented in Prompt 4.)* decisions.md §7 lists Hana Takeda, Peter Mwangi and "other 11 staff within 0.8 km of the Embassy" (13 people), but D-23 needs 14 staff. In the demo, Amb. Layla Haddad is at the **Residence** (Mobile GPS, 98%).
→ *Proposed:* place her at the Residence coordinates (−1.2745, 36.7935), which is 3.6 km from the epicentre and inside 5 km. Put the other 11 within 0.8 km of the Embassy. Peter Mwangi and James Otieno are LOCAL_STAFF; the other 12 are DIPLOMAT.

**G-10 · Personnel totals: 926 vs about 1,300.** *(Implemented in Prompt 4.)* The demo's MISSIONS array adds up to **926** staff over 36 missions. The demo's "Personnel" KPI shows `926 + 412 = 1,338`. D-27 says "about 1,300 staff and delegates".
→ *Proposed:* seed exactly the per-mission staff numbers from the array as DIPLOMAT and LOCAL_STAFF (Nairobi = 14). Then add 412 more people as DEPENDANT, DELEGATE and CONTRACTOR, all outside Nairobi apart from the 3 delegates. That gives about 1,338, all computed from data (D-27).

**G-11 · Trip "active today" breaks determinism.** *(Seed side implemented in Prompt 4; exposure uses `incident.opened_at` in Prompt 7.)* D-22 counts a trip only if `starts_on ≤ today ≤ ends_on`. Prompt 4 wants the seed to be identical every time it runs, and tests run on any date.
→ *Proposed:* exposure judges the trip against `incident.opened_at::date` (UTC), not `now()`. The seed takes a `SCENARIO_DATE` (default: the seeding date) and sets TRP-8812 to `[SCENARIO_DATE − 1, SCENARIO_DATE + 3]`. The determinism test pins `SCENARIO_DATE`. Seed UUIDs are uuid5 values from natural keys, so `gen_random_uuid()` defaults are never used for seeded rows.

**G-12 · What the Paris control signal should produce is not stated.** The signal sits on the Paris mission coordinates, so the Paris embassy and Paris staff will be exposed.
→ *Proposed:* send it from FACTAL as TRANSPORT_STRIKE / MODERATE. The tests assert: it is a separate incident; it is not escalated (signal severity is below HIGH); there is no START_PLAYBOOK proposal; and there is one Watch Officer and one Exposure proposal, both auto-executed. The tests do not assert Paris head counts.

**G-13 · There is no Location Confidence Engine in any prompt.** *(Implemented in Prompt 4.)* PPL-03 (M) requires that the engine "computes current location and confidence", but Prompt 4 *seeds* `person_location_current` directly.
→ *Proposed:* add a small deterministic engine to `people/service.py` in Prompt 4. Confidence is a per-source base weight times decay with age, and the strongest recent observation wins. The engine recomputes `person_location_current` from `location_observation`. The seed writes observations only and then runs the engine. The tests check the demo values: Hana 72 (CALENDAR_HR), Peter 91 (MOBILE_GPS), delegates 89 (TRAVEL_BOOKING), access control 97–99.

**G-14 · The PB-07 step action types are not defined.** *(Seeded in Prompt 4.)* The demo shows 8 steps and campaigns NTF-3101 to 3104. Prompt 9 lists action types but does not map them to steps. One mismatch: step 7 ("Approve evacuation route B") also sends NTF-3104 in the demo, so it is not just a gate.
→ *Proposed:*

| Step | Name | action_type | requires_approval_role | Effect |
|---|---|---|---|---|
| 1 | Confirm incident & severity | TASK | — | incident_event |
| 2 | Notify HoM & Security Attaché | NOTIFY (ALERT) | — | NTF-3101, 2 recipients, APP·SMS·VOICE |
| 3 | Notify HQ Global Ops Centre | TASK | — | incident_event plus an in-app WebSocket notice. HQ users are `app_user`s, not `person`s, so no campaign is created |
| 4 | Shelter-in-place advisory & BCP-NBO | NOTIFY (ALERT) | — | NTF-3102, 17 recipients, APP·SMS·WHATSAPP |
| 5 | Safety check-in | CHECKIN | — | NTF-3103, 229 recipients |
| 6 | Assistance partner standby | PARTNER_REQUEST | — | incident_event |
| 7 | Approve evacuation route B | NOTIFY (ALERT) | HEAD_OF_MISSION | gate, then NTF-3104, 17 recipients |
| 8 | Brief leadership | BRIEFING | — | incident_event (template text, no LLM) |

`APPROVAL_GATE` stays a valid type for gates that do nothing else. The Communications advisory then takes the next NTF number, and tests check NTF numbers by pattern only (as D-18 already does for INC).

**G-15 · Which event triggers the Response Planner.** Prompt 13 says "incident matches a playbook's trigger_rules". The PB-07 rules (`min_severity HIGH`, `max_distance_m`) depend on exposure and on the escalated severity, and scene 2 expects the proposal there.
→ *Proposed:* the Response Planner observes `EXPOSURE_COMPUTED`. Its `proposal_key` is `START_PLAYBOOK:{incident_id}:{playbook_code}`.

**G-16 · Which agent owns the scene 5 START_EVACUATION proposal.** `agent_proposal.agent_id` is NOT NULL, and decisions.md says the proposal is "injected by the test, not by an agent".
→ *Proposed:* the test inserts it through the proposal service using the RESPONSE_PLANNER agent, with `proposal_key = 'TEST:START_EVACUATION:…'`. No production agent code can emit START_EVACUATION. The seed also marks its policy as test-only in the code comment, so it can be left out of pilot seeds.

### 3.3 Agents, decisions and check-in

**G-17 · The undo window length is undefined.** Prompt 12 sets `undo_until` at level 1, but nothing defines how long the window is. The schema has `decision_deadline_s` only.
→ *Proposed:* add the config key `UNDO_WINDOW_S` (default 300) for Phase 1. A per-policy `undo_window_s` column would go into proposed-changes **(schema)**. With the seed policies nothing in the scenario runs at level 1, so tests raise an agent to level 1 on purpose to exercise undo (DQ-04).

**G-18 · What "escalation" means for overdue proposals (AGT-06).** No target is defined.
→ *Proposed:* the background job sets the status to EXPIRED. It writes an audit row (`PROPOSAL.EXPIRE`), plus an `ESCALATION` incident_event when the proposal has an incident. It also pushes a WebSocket notice to holders of the step's required role. Nothing is sent outside the system.

**G-19 · Which non-responders get escalated.** D-07 says non-responders are escalated after `escalate_after_s`, and Prompt 10 tests only that Hana is escalated once. Applied literally, the 40 silent citizens would also be escalated.
→ *Proposed:* escalate **personnel** one by one: one `ESCALATION` event and one audit row per person, once. Citizens are escalated **as one aggregate**: one event with the count, once per campaign. Idempotency comes from checking for an existing event or audit row, so the schema does not change. See also Q-4.

**G-20 · Auditing simulated delivery status changes.** The simulated adapter moves every delivery SENT → DELIVERED → READ. For 229 people on 3 channels that is about 2,000 audit rows per campaign.
→ *Proposed:* audit only the actions themselves: `CAMPAIGN.CREATE`, `CAMPAIGN.SEND` with counts per channel, and each `CHECKIN.RESPOND`. Delivery status changes are telemetry and update `notification_delivery` only. Seeding writes one `SEED.LOAD` audit row per entity type, with counts. See also Q-5.

**G-21 · Validating edit-and-approve.** `edited_payload` could change what an action does, for example widening an advisory's audience. The policy level cannot change, because `action_type` is frozen.
→ *Proposed:* each action type has a Pydantic payload schema. `edited_payload` must pass the same schema, and for SEND_EXTERNAL_MESSAGE the audience cannot be widened beyond the original. The executor uses `edited_payload` when it is present. The audit row stores both payloads.

**G-22 · Mission risk colour on the map.** The demo turns NBO red during the incident. Scene 0 needs NBO to be LOW. No document says who changes `mission.risk_level`.
→ *Proposed:* the stored `risk_level` stays the baseline and is never changed automatically. The UI and API show `display_risk = max(risk_level, highest ACTIVE incident severity where incident.mission_id = mission.id)`. Labels for missions follow D-08.

### 3.4 Document and ID inconsistencies (no design impact)

**G-23 · Two ID schemes.** Prompt 14 cites DQ-07, and D-28 cites the master spec's CHK-04 ("mobile view"). Both IDs come from `docs/reference/master-requirements.md`. The PRD's own CHK-04 means "pluggable channel adapters".
→ *Proposed:* code and PRs cite PRD IDs, and master-spec IDs carry an `MS-` prefix (for example MS-DQ-07, MS-CHK-04). `docs/reference/` is not in AGENTS.md's sources-of-truth list. Treat it as background unless someone decides otherwise.

**G-24 · Two presenter scene lists.** The demo's presenter has 7 scenes, including "AI briefing" (Copilot) and "Leadership" (Executive), both out of scope under D-25.
→ *Proposed:* the Presenter bar uses the scenes 0–6 from decisions.md §7 only.

**G-25 · Two names for escalation events.** The schema comment lists `ESCALATED`, and D-07 uses `ESCALATION`.
→ *Proposed:* keep both with different meanings. `ESCALATED` means severity was raised (D-11). `ESCALATION` means a non-responder or an overdue proposal. Both go in one constants module.

**G-26 · Small stale references.** The PRD's companion-files table still names `NEXIRA_Phase1_Prompts.md`. CONSULAR_OFFICER is labelled "Phase 2 onwards" but is a Phase 1 approver for SEND_EXTERNAL_MESSAGE (D-17 seed table).
→ *Proposed:* no code impact. Fix the wording in the next documentation pass.

**G-27 · Alembic downgrade and extensions.** The schema file runs `CREATE EXTENSION IF NOT EXISTS`, but the superuser owns the extensions (D-01).
→ *Proposed:* the downgrade drops all objects the migration created, leaves the extensions and roles alone, and does not need to touch the audit TRUNCATE trigger (DROP TABLE is not blocked). The upgrade runs the v0.2 file verbatim, as Prompt 2 says.

**G-28 · The committed demo is the wrong version (found during Prompt 1).** `docs/design/NEXIRA_Demo_Full.html` (md5 `0170a862…`) contains no Decision Queue and no AI Agents screens, and its navigation has no Audit entry. D-25 requires the "NEXIRA_Demo_Full 3.html" version.
→ **Resolved 2026-10-24:** version 3 has been uploaded and stored as `docs/design/NEXIRA_Demo_Full.html` (md5 `b013ce39…`). The shell now follows its navigation groups: COMMAND (Decision Queue, AI Agents), MONITOR, RESPOND. Audit is not in the demo's navigation, so it sits under ADMIN.

---

## 4. Questions before Prompt 1

**Answered 2026-10-24 (Sudev Achuthan):**
- Q1 · Yes, the AI coding tools and the repository host are approved for these documents.
- Q3 · Yes, `make tiles` may download map data and fonts at build time. Runtime stays offline (D-24).
- Q8 · The named reviewer for 🔒 gates (D-29) is Sudev Achuthan.
- Q9 · Commit the pending documentation changes before Prompt 1. Branch and PR workflow still open.

- Q2 · The header clock shows GST as UTC+4. Config key `HOME_TZ`, default `Asia/Dubai` (fixed UTC+4, no daylight saving).
- Q4–Q7, Q10 · The proposed defaults are accepted:
  - Q4 · Citizens are escalated as one group per campaign, personnel one by one.
  - Q5 · Simulated delivery status changes and bulk seeding are not audited row by row.
  - Q6 · Workers read their tenants from `WORKER_TENANT_IDS`.
  - Q7 · `UNDO_WINDOW_S` = 300.
  - Q10 · The simulator imports the backend package as a path dependency.

- Q9 (workflow) · From Prompt 3 on, each prompt is a branch pushed to the private GitHub repo `sudeva-ops/nexira` with a pull request. D-29 sign-offs are recorded in the PR (Prompts 0–2 recorded theirs in merge commits).

1. **Tooling approval (decisions.md §9.1).** Is it confirmed that Claude Code and this repository host are approved for these "Internal" documents? I won't push to a remote until you say so.
2. **Header clock.** Is "GST" Gulf Standard Time (UTC+4)? I'll make it a config key (`HOME_TZ`, default `Asia/Dubai`) unless you want something else.
3. **Map data at build time.** May `make tiles` download an OSM/Protomaps extract and open fonts at **build** time? At runtime everything stays local (D-24). If it may not, who supplies the source files?
4. **Escalating citizens (G-19).** Is aggregate escalation for the 40 silent citizens acceptable, or should each citizen be escalated individually?
5. **Audit granularity (G-20).** Is it acceptable that simulated delivery status changes and bulk seeding are *not* audited row by row?
6. **Workers and tenants (G-01).** For Phase 1, are you happy with `WORKER_TENANT_IDS` from config instead of a new security-definer function?
7. **Undo window (G-17).** Is a config value of 300 s acceptable for Phase 1, with the per-policy column left as a proposed change?
8. **Reviewer for 🔒 gates (D-29).** Who is the named reviewer who signs off Prompts 2, 3, 9, 12 and 16? It is needed in each PR.
9. **Git workflow.** Should each prompt be a branch with a PR on a GitHub remote, or local commits on `main`? Today `main` has uncommitted changes in `docs/decisions.md` and `docs/prompts.md`, and untracked `docs/design/` and `docs/schema/checks/`. Should I commit those docs before Prompt 1?
10. **Simulator packaging.** Can `simulator/` import the backend package to load through the service layer (Prompt 4)? I'd install it as a path dependency instead of calling the HTTP API, so seeding doesn't need Keycloak tokens.

---

*Stopping here for review, as Prompt 0 asks. No code has been written.*
