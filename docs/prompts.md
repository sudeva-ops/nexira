# NEXIRA · Phase 1 prompts for the AI coding tool · v0.2

For GitHub Copilot (agent mode), Cursor or Claude Code. Replaces `NEXIRA_Phase1_Prompts.md` v0.1.

**What changed from v0.1**
- Prompts follow the PRD milestones M1–M6, and each screen is built in the same milestone as its backend.
- Large prompts are split, so each fits in one review.
- Every prompt names the decisions (D-xx) it depends on.
- Prompts marked 🔒 need human review before merging (D-29).

**How to run them**
- One prompt at a time, in order.
- After each prompt: read the diff, run `make test lint` yourself, then commit.
- Run the review prompts at the end of this file after every 🔒 prompt.

**Put these files in the repository before you start**

| File | Where |
|---|---|
| `AGENTS.md` | repo root, plus an identical copy at `.github/copilot-instructions.md` |
| `decisions.md` | `docs/decisions.md` |
| Phase 1 PRD (as text) | `docs/requirements.md` |
| `nexira_schema.sql` v0.2 | `docs/schema/nexira_schema.sql` |
| `NEXIRA_Demo_Full 3.html` | `docs/design/NEXIRA_Demo_Full.html` |

---

## M1 · Foundation (weeks 1–2)

### Prompt 0 · Read and plan (no code)
```
Read AGENTS.md, docs/decisions.md, docs/requirements.md, docs/schema/nexira_schema.sql
and skim docs/design/NEXIRA_Demo_Full.html.

Do not write code. Create docs/plan-phase1.md with:
1. Phase 1 scope in 10 bullets.
2. The repository structure you will create.
3. Any remaining conflicts or gaps between the four documents that decisions.md does
   NOT already settle, each with a proposed resolution.
4. Questions you need answered before Prompt 1.
Stop and wait for review.
```

### Prompt 1 · Repository and local environment
```
Create the monorepo skeleton from AGENTS.md.

- /backend: FastAPI app with app/main.py and app/core/{config,db,audit,security,approvals,llm}.py
  as stubs. GET /api/health returns {"status":"ok"}. pytest, ruff and mypy (strict) configured.
- /frontend: Vite + React + TypeScript + Blueprint dark theme; app shell with the left
  navigation listing only the Phase 1 screens (D-25) and a header with a GST/UTC clock.
- /simulator: empty Python package.
- /infra/docker-compose.yml: postgres, redis, keycloak, backend, frontend.
  Postgres image: build infra/postgres/Dockerfile from docs/schema/checks/Dockerfile.postgres
  (official postgres:16 + PostGIS package). Do NOT use postgis/postgis:16-3.4: it has no
  arm64 build and runs under emulation on Apple Silicon.
- /infra/postgres/init.sql, run once as the superuser:
  creates the extensions postgis and pgcrypto, the roles nexira_owner (LOGIN, no superuser),
  nexira_app (NOLOGIN) and nexira_api (LOGIN, IN ROLE nexira_app), and the database owned
  by nexira_owner. Passwords come from environment variables (D-01).
- Backend config has two DSNs: MIGRATIONS_DATABASE_URL (nexira_owner) and DATABASE_URL (nexira_api).
- .env.example with every variable. Makefile targets: up, down, test, lint, migrate, seed,
  reset-demo (drops and recreates the local DB volume, then migrate + seed; D-21), tiles (stub for now).
- CI workflow: lint + tests for backend and frontend, with a PostGIS service container.

Acceptance: `make up` starts everything; /api/health is ok; `make test lint` passes;
README.md explains local setup.
```

### Prompt 2 · Database and migrations 🔒
```
Implement the database from docs/schema/nexira_schema.sql (v0.2).

- One initial Alembic migration that reproduces the file exactly, run as nexira_owner.
  Do not change the schema; put proposals in docs/schema/proposed-changes.md.
- SQLAlchemy 2.x models per module under app/modules/<domain>/models.py (GeoAlchemy2 for geography).
  Mark columns set by triggers (effective_level, deadline_at, chain_seq, prev_hash, row_hash)
  as server-generated so the app never writes them.
- app/core/db.py: async session per request, connected as nexira_api; at the start of each
  transaction run SELECT set_config('app.tenant_id', :tid, true) (D-02).

docs/schema/checks/ contains 35 SQL checks that already pass against this schema on
PostgreSQL 16 + PostGIS. Port every one of them into pytest first, then add:

Tests (real PostGIS, connected as nexira_api):
 a) migration upgrades and downgrades cleanly;
 b) tenant A cannot read or write tenant B rows in EVERY tenant table, including the child
    tables listed in D-03 (generate this test from the table list, don't hand-pick);
 c) with no tenant set, queries return zero rows and do not error;
 d) nexira_api cannot UPDATE, DELETE or TRUNCATE audit_log; the chain verifies after
    50 concurrent inserts (audit_verify_chain() IS NULL) and chain_seq has no gaps;
 e) next_reference('INC', true) gives unique values under 20 concurrent callers;
 f) the connection role is not a superuser and has no BYPASSRLS (fail fast at startup if it does).
```

### Prompt 3 · Authentication, roles and audit 🔒
```
Implement identity, authorisation and audit (D-04, D-05, D-20).

- app/core/security.py: validate Keycloak OIDC JWTs (signature, issuer, audience, expiry).
  Resolve the tenant with resolve_tenant_by_issuer(iss), set it on the session, then find
  app_user by (tenant, sub); create it on first login. Ignore role claims in the token.
- app/core/approvals.py, first part: user_has_role(user, role_codes, mission_id) where
  role_codes may contain '|' alternatives and a role with mission_id NULL applies to all
  missions. FastAPI dependency require_roles(*codes, mission_id=None).
- Seed roles: ADMIN, DUTY_OFFICER, SECURITY_OFFICER, HEAD_OF_MISSION, HQ_CRISIS_DIRECTOR,
  TRAVEL_DESK, CONSULAR_OFFICER, VIEWER.
- app/core/audit.py: write(actor_type, actor_id, action, entity_type, entity_id, details).
  Inserts only; the database computes the hash chain. GET /api/audit?entity_type=&entity_id=
  and GET /api/audit/verify (ADMIN only).
- Keycloak realm export in /infra/keycloak: one demo user per role (fictional names), plus a
  Nairobi Head of Mission, a Cairo Head of Mission (to test mission scope) and one user who holds
  both HEAD_OF_MISSION and HQ_CRISIS_DIRECTOR (to test D-16). OTP optional in this realm.
  Passwords only in .env.example.
- Frontend: Keycloak login; header shows user name and roles (from GET /api/me, not the token).

Tests: valid/expired/wrong-issuer tokens; 403 for a forbidden role; the Cairo HoM cannot act on
a Nairobi-scoped check; a role claim injected into the token grants nothing; audit rows chain.
```

## M2 · Data and simulator (week 3)

### Prompt 4 · Seed data
```
Build /simulator/seed: deterministic (seed=42), loading through the backend service layer.
Follow docs/decisions.md exactly for numbers and coordinates (D-09, D-10, D-18, D-22, D-23, D-27).

- Tenant "Ministry of Foreign Affairs (demo)" with oidc_issuer = the demo realm issuer.
- 36 missions from the MISSIONS array in docs/design/NEXIRA_Demo_Full.html; risk_level LOW,
  except Baghdad, Islamabad, Abuja and Jakarta, which are MODERATE.
- Sites: embassy + residence per mission; Nairobi also has the delegation hotel (HOTEL).
  Nairobi coordinates from decisions.md section 7.
- People: the 17 named Nairobi people from the AFFECTED array with the same roles, location
  sources and confidence values; 212 Nairobi citizens inside the zone; about 1,300 staff and
  about 1,000 citizens across the other missions; NO other people inside the Nairobi zone.
- location_observation rows plus person_location_current matching the confidences.
- Trip TRP-8812 (the 3 delegates), active on the scenario date.
- Intel sources DATAMINR, MAX, RISKLINE, DRAGONFLY, FACTAL, SAMDESK, XWEATHER, HEALIX
  (SIMULATED, reliabilities from D-10) and OSINT (disabled, takes_part_in_fusion=false).
  severity_map: Dataminr High→HIGH; MAX Level 4→HIGH; Riskline Moderate→MODERATE (D-11).
- Playbook PB-07 with the 8 demo steps; step 7 requires HEAD_OF_MISSION.
- Agents and action_policy rows from the table in D-17, including the test-only START_EVACUATION policy.
- Reference counters: INC (current year) = 1041, NTF = 3100.
- Citizen advisory templates in EN/AR/FR/SW, with REVIEW REQUIRED markers on AR/FR/SW (D-15).

Tests: seeding twice gives identical data; counts match D-23 when computed with PostGIS.
```

### Prompt 5 · Scenario player
```
Implement the NBO-CIVIL-UNREST scenario from decisions.md section 7.

- Store scenes 0–6 in scenario / scenario_event: 3 Nairobi raw signals plus the Paris control
  signal, check-in responses (15 safe, Peter Mwangi NEED_HELP, Hana Takeda no response;
  citizens 168 safe, 4 need help, 40 none). Check-in escalate_after_s = 20.
- Scenario player: publishes events to Redis Streams at their offsets, with play / pause /
  next scene / reset (reset = scenario state only; D-21).
- API: POST /api/scenarios/{code}/play|pause|next|reset (ADMIN or DUTY_OFFICER).
  Scenario events go through the same ingestion paths as real data; the player never writes
  business tables directly.

Tests: events replay in order with correct relative timing (use a fake clock); pause and
resume keep order; reset returns to scene 0.
```

## M3 · Incidents and map (weeks 4–6)

### Prompt 6 · Ingestion, normalisation and fusion
```
Implement app/modules/intel (D-09, D-10, D-11).

1. Consumer: reads RAW_SIGNAL events from Redis and inserts raw_signal rows (idempotent on source_id + external_id).
2. Normaliser: maps category and severity through the source's maps, one signal at a time.
   Unknown values → norm_status DISCARDED, with an audit entry.
3. Fusion exactly as D-10: same category, ≤ 3 km from the incident location, ≤ 60 min from
   last_signal_at, source takes part in fusion. Incident reference from next_reference('INC', true).
   signal_severity = max of linked signals. Confidence formula from D-10, documented in a docstring.
4. Write incident_event (SIGNAL, FUSED) and audit entries. Publish INCIDENT_CREATED / INCIDENT_UPDATED.
5. API: GET /api/signals?status=, GET /api/incidents, GET /api/incidents/{id}.

Tests: the three Nairobi signals → one incident, confidence 92, signal_severity HIGH, Riskline
signal normalised to MODERATE; the Paris signal → a separate incident; a duplicate event is ignored;
an OSINT signal never fuses.
```

### Prompt 7 · Exposure and severity escalation
```
Implement exposure in app/modules/intel/exposure.py (D-06, D-11, D-22, D-23).

- On INCIDENT_CREATED/UPDATED, compute incident_exposure for people, sites and trips using
  PostGIS ST_DWithin on geography (index-backed). Replace the previous rows atomically.
- Set incident.mission_id to the mission of the nearest exposed site.
- Apply the D-11 escalation: protected mission site exposed and signal_severity ≥ HIGH →
  severity one level up; write an ESCALATED incident_event.
- Publish EXPOSURE_COMPUTED. Extend GET /api/incidents/{id} with exposure, signals and timeline.
- PATCH /api/incidents/{id}/status and POST /api/incidents/{id}/notes (INC-07), audited.

Tests: Nairobi exposure = 14 staff, 3 delegates, 212 citizens, 3 sites, 1 trip; mission_id = NBO;
severity CRITICAL; signal-to-exposure time ≤ 5 s on seed data.
```

### Prompt 8 · First screens: Global Operations, Incidents, People & Sites
```
Build the first screens in /frontend, matching docs/design/NEXIRA_Demo_Full.html (D-25).

- useRealtime(): one WebSocket per tab (backend endpoint /ws, authenticated, tenant-scoped);
  events update the TanStack Query cache. UI updates ≤ 2 s after the event (PLT-05).
- make tiles: build a world PMTiles extract (z0–6) and a Nairobi extract (z0–15) with the
  pmtiles CLI into infra/tiles/ (not committed); serve from the frontend container. MapLibre
  style with local glyphs and sprites only; OSM attribution shown (D-24).
- Global Operations: KPI strip computed from data; map with missions coloured by risk, the
  incident and its impact circle, people in zone at city zoom; live feed where raw signals
  visibly merge into the incident; impact panel with people, confidence and source.
- Incidents: register table and detail with the source-normalisation table (column
  "Normalised (signal)", D-11), exposure summary and timeline; status change and notes.
- People & Sites: searchable tables with location confidence; the sites tab shows readiness
  and last drill. Sites count shows mission property only (D-23).
- Label simulated sources "(simulated)"; no "Connected", "AIP" or "Object explorer" (D-19).

Tests: Vitest for the components; one Playwright test: start scene 1 through the API → the
incident appears on the map without a page reload.
```

## M4 · Response (weeks 7–8)

### Prompt 9 · Approval service and playbook engine 🔒
```
Complete app/core/approvals.py and implement app/modules/playbooks (D-05, D-16).

- approvals.decide(...) is the single place where any approval is checked: role (with '|'
  alternatives), mission scope from incident.mission_id, the same person not deciding two steps,
  and step order. Playbook gates and (later) agent proposals both call it.
- Playbook engine: start a run for an incident (POST /api/playbook-runs, DUTY_OFFICER or
  SECURITY_OFFICER); execute steps in order, recording timestamps; a step with
  requires_approval_role pauses the run (AWAITING_APPROVAL) until
  POST /api/playbook-runs/{id}/steps/{step_id}/approve succeeds.
- Step actions in Phase 1: NOTIFY and CHECKIN create notification_campaign rows (Prompt 10);
  PARTNER_REQUEST, TASK and BRIEFING write incident_event only.
- Every step writes incident_event + audit and publishes PLAYBOOK_STEP events.
- Steps are idempotent: a worker restart does not run a step twice.

Tests: PB-07 runs to step 7 and waits; the Duty Officer gets 403; the Cairo HoM gets 403;
the Nairobi HoM approves and the run completes; a restart mid-run resumes without duplicates.
```

### Prompt 10 · Notifications and safety check-in
```
Implement app/modules/notifications and app/modules/checkin (D-07, D-28).

- Channel adapter interface send(person, channel, text) -> provider_ref. SimulatedChannelAdapter
  moves deliveries SENT→DELIVERED→READ over time. No real channels exist in Phase 1.
- Campaign references from next_reference('NTF', false).
- Check-in: a campaign to exposed people (229 for Nairobi); responses via
  POST /api/checkin/{campaign_id}/respond and from simulator events; the latest answer counts
  (v_checkin_latest). Non-responders are escalated after escalate_after_s with an ESCALATION
  incident_event and an audit row.
- Summary endpoint: personnel and citizens separately, each with safe / need_help / pending / accounted %.

Tests: scenario check-in ends at personnel 15/1/1 and citizens 168/4/40; Hana Takeda is
escalated once; a SAFE then NEED_HELP answer counts as NEED_HELP.
```

### Prompt 11 · Playbooks and Check-in screens
```
Build the Response Playbooks and Safety Check-in screens to match the demo.

- Playbooks: library, run view with step states and timestamps, approve button shown only when
  GET /api/me/permissions says the user may approve that step (the backend still enforces it);
  audit trail panel for the run.
- Check-in: summary donut, live responses list, citizen progress bar, "escalate non-responders"
  action, and the phone preview panel that posts a response through the API (D-28).

Playwright: the Duty Officer cannot see the step-7 approve button; the Nairobi HoM approves it;
check-in numbers update live.
```

## M5 · Agents (weeks 9–10)

### Prompt 12 · Policy engine, proposals and executor 🔒
```
Implement the decision core of app/modules/agents (D-12, D-13, D-14, D-16, D-17).

- Proposal creation service: inserts agent_proposal with a proposal_key. The database sets
  effective_level, deadline_at and the approval rows; the app must not compute or override them.
  Level 0 → execute immediately; level 1 → execute and set undo_until; level 2/3 → PENDING;
  level 4 → advisory only, never executable.
- Executor: on final approval, call the SAME service functions a user calls (for example
  playbooks.start_run); record executed_at; on failure set status FAILED with the error.
  START_EVACUATION is a stub service in Phase 1 that only writes an incident_event.
- API: GET /api/proposals?status=; POST /api/proposals/{id}/approve;
  POST /api/proposals/{id}/edit-approve {edited_action, edited_payload};
  POST /api/proposals/{id}/reject {reason}; POST /api/proposals/{id}/use-alternative {index}
  (supersedes and creates a new proposal, D-14); POST /api/proposals/{id}/undo;
  GET/PATCH /api/agents (ADMIN); POST /api/agents/pause-all and /resume-all (ADMIN, D-17).
- Overdue PENDING proposals → EXPIRED plus an escalation event (background job).
- Everything audited; rejection reasons stored.

Tests: an agent set to level 0 still needs approval for SEND_EXTERNAL_MESSAGE; an unknown
action type is advise-only; START_EVACUATION does not run after one approval; the user holding
both HoM and HQ roles cannot approve both steps; step 2 cannot be decided before step 1;
using an alternative with a higher floor creates a proposal with the higher level; undo works
only before undo_until; pause-all makes proposal creation fail; edit-approve keeps the
original action_payload unchanged.
```

### Prompt 13 · The four Phase 1 agents
```
Implement the agents in app/modules/agents/agents/ (D-15, D-17 seed table).

Each agent is a class with observe(event) -> list[ProposalDraft], is deterministic (rules +
templates), and may use app/core/llm.py only through its stub in tests.
- WatchOfficer: INCIDENT_CREATED → LOG_INFO.
- Exposure: EXPOSURE_COMPUTED → POST_INTERNAL_NOTE with the exposure summary.
- ResponsePlanner: incident matches a playbook's trigger_rules → START_PLAYBOOK, with
  structured alternatives (D-14).
- Communications: PB-07 step 4 (shelter-in-place) DONE → SEND_EXTERNAL_MESSAGE to registered
  citizens, using the EN/AR/FR/SW templates.
Every draft contains title, proposed_action, action_payload, evidence with sources,
alternatives, risk_if_no_action and confidence. A stable proposal_key makes re-observed
events harmless.

Tests: replaying scenes 1–3 produces exactly one proposal per agent per trigger; with
agents paused, no proposals are created and the playbook can still be started manually.
```

### Prompt 14 · Decision Queue and AI Agents screens
```
Build the Decision Queue (home) and AI Agents screens to match the demo.

- Decision Queue: pending / decided / all tabs; cards with evidence and sources, confidence,
  risk if no action, alternatives ("Use"), approver chain with step status, deadline countdown;
  Approve / Edit / Reject (reason picker) / Undo. Actions are hidden when
  GET /api/me/permissions says the user cannot take them.
- Header pill with the pending count (DQ-07). Decision policy legend; agent activity log.
- AI Agents: roster with what each agent watches, proposals and acceptance rate; autonomy
  dropdown (ADMIN only); kill switch with confirmation built into the page.

Playwright: approve the PB-07 proposal; reject a proposal with a reason; two-person rule with
the Nairobi HoM and then the HQ Crisis Director (two browser contexts).
```

## M6 · Pilot-ready (weeks 11–12)

### Prompt 15 · Presenter bar and end-to-end acceptance
```
- Presenter bar (only when VITE_DEMO_MODE=true) calling the scenario API.
- Playwright suite that runs the whole Phase 1 acceptance scenario (decisions.md section 7)
  from `make reset-demo`, with each decision made by a logged-in user with the correct role,
  and finishes by checking GET /api/audit/verify returns intact.
- Performance check on seed data: signal → incident ≤ 5 s; incident → exposure ≤ 5 s;
  UI update ≤ 2 s. Report the measured numbers.
```

### Prompt 16 · Hardening and pilot deployment 🔒
```
- Helm chart for Kubernetes/OpenShift: separate secrets for the owner and API users; network
  policies; no external egress except the configured IdP.
- Backups: nightly pg_dump plus documented restore, tested once (NFR availability).
- Security checklist against OWASP ASVS L2 for the implemented scope; list gaps honestly.
- docs/security-review.md: what a human reviewer must check (RLS, approvals, audit, agents,
  WebSocket auth), with file paths. Do not mark items as reviewed yourself.
```

---

## Prompts to run after every task

| Purpose | Prompt |
|---|---|
| Self-review | `Review the changes you just made against AGENTS.md and docs/decisions.md. List any rule you broke, missing tests, or security concerns, then fix them.` |
| Security check | `Check this change for tenant-isolation gaps, connections that could bypass RLS, missing role or mission-scope checks, missing audit entries, and any path where an agent could act without approval. Show the evidence (file and line) for each finding.` |
| Tests | `Run the full test suite and linters. Fix failures without weakening, skipping or deleting tests. Report the real output and what changed.` |
| Reviewer summary | `Summarise this change for a reviewer in 8 bullets: what, why, decisions relied on (D-xx), files touched, how to test manually, anything needing 🔒 sign-off.` |
