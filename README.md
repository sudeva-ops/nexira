# NEXIRA

Personal study project: a resilience platform for organisations with people and sites abroad. All data is fictional.

Start here:
1. `AGENTS.md` — rules for AI coding tools
2. `docs/decisions.md` — decisions that settle conflicts between documents
3. `docs/requirements.md` — Phase 1 requirements
4. `docs/prompts.md` — the build prompts, run in order
5. `docs/plan-phase1.md` — Phase 1 plan, open gaps and answered questions

## Local setup

**Prerequisites:** Docker with Compose v2, [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you), Node.js 24 and GNU make. These work natively on Apple Silicon (arm64).

```sh
make up        # creates .env from .env.example on first run, builds and starts everything
make migrate   # applies the schema (docs/schema/nexira_schema.sql v0.2) as nexira_owner
make seed      # deterministic demo data: 36 missions, 2,550 fictional people, PB-07, agents
```

| Service | URL | Notes |
|---|---|---|
| Frontend | http://localhost:3000 | nginx serving the built app; proxies `/api` and `/ws` to the backend |
| Backend | http://localhost:8000/api/health | FastAPI; API docs at `/api/docs` |
| Keycloak | http://localhost:8080 | admin login from `.env`; realm `nexira-demo` |
| PostgreSQL 16 + PostGIS 3 | localhost:5432 | database `nexira` |
| Redis | localhost:6379 | |

All ports are bound to 127.0.0.1. Change them in `.env` if they clash with something already running.

### Demo users

Open http://localhost:3000 and sign in with one of these fictional users. The password for all of them is `DEMO_USER_PASSWORD` in `.env` (default `local-demo-pw`). Roles come from the database (`make seed`), not from Keycloak (D-04).

| Username | Name | Roles |
|---|---|---|
| `admin` | Nora Lind | ADMIN |
| `duty.officer` | Daniel Mercer | DUTY_OFFICER |
| `security.officer` | Leila Nasser | SECURITY_OFFICER |
| `hom.nairobi` | Layla Haddad | HEAD_OF_MISSION · NBO |
| `hom.cairo` | Ahmed Farouk | HEAD_OF_MISSION · CAI (tests mission scope) |
| `hq.director` | Miriam Okafor | HQ_CRISIS_DIRECTOR |
| `travel.desk` | Tomas Reyes | TRAVEL_DESK |
| `consular.officer` | Anika Shah | CONSULAR_OFFICER |
| `viewer` | Victor Lowe | VIEWER |
| `dual.role` | Elias Brandt | HEAD_OF_MISSION · NBO and HQ_CRISIS_DIRECTOR (tests the two-person rule) |

The realm also has a `nexira-dev-cli` client that allows the password grant, for local scripts and tests only. It must not exist in a pilot realm.

### Database roles (D-01)

`infra/postgres/init.sql` runs once, as the superuser, when the data volume is first created. It installs PostGIS and pgcrypto and creates three roles:

- `nexira_owner` owns the database and runs migrations. It is not a superuser.
- `nexira_app` is the group role that holds the runtime grants.
- `nexira_api` is the only role the backend connects as.

Only the one-shot `migrate` service receives the owner password; the backend container never does.

### Seed data

`make seed` loads fictional data through the backend service layer, as `nexira_api`. The only exception is the tenant row, which `nexira_owner` creates (plan G-03). The data is deterministic: random seed 42, and every timestamp comes from `SCENARIO_DATE` (default: today in UTC). Running it again changes nothing.

| What | Count | Source |
|---|---|---|
| Missions | 36 (Baghdad, Islamabad, Abuja and Jakarta are MODERATE) | demo `MISSIONS` |
| Sites | 73: an embassy and a residence per mission, plus the Nairobi delegation hotel | D-23 |
| Personnel | 1,338: 926 mission staff plus 412 dependants, contractors and delegates | plan G-10 |
| Registered citizens | 1,212: 212 inside the Nairobi zone, 1,000 elsewhere | D-23, D-27 |
| Nairobi exposure | 229 people (14 staff, 3 delegates, 212 citizens), 3 sites, trip TRP-8812 | D-23 |
| Intel sources | 8 simulated, plus OSINT (disabled) | D-09, D-10 |
| Playbook | PB-07, 8 steps; step 7 needs HEAD_OF_MISSION | plan G-14 |
| Agents and policies | 4 agents, 5 policies (START_EVACUATION is for tests only) | D-17 |
| Reference counters | the next incident is `INC-<year>-1042`, the next campaign `NTF-3101` | D-18 |

Current locations come from the Location Confidence Engine (`backend/app/modules/people/location.py`). The advisory templates in AR, FR and SW are marked `[REVIEW REQUIRED]` until a native speaker reviews them (D-15).

### Scenario player

The NBO-CIVIL-UNREST scenario (decisions.md §7) is stored by `make seed`. ADMIN or DUTY_OFFICER users drive it:

```sh
POST /api/scenarios/NBO-CIVIL-UNREST/next    # go to the next scene and play its events
POST /api/scenarios/NBO-CIVIL-UNREST/pause   # stop, keeping the position and elapsed time
POST /api/scenarios/NBO-CIVIL-UNREST/play    # resume the current scene
POST /api/scenarios/NBO-CIVIL-UNREST/reset   # back to scene 0 as a new run; business data is kept (D-21)
GET  /api/scenarios/NBO-CIVIL-UNREST         # state and scene list
```

The player publishes to the Redis stream `nexira:events` and never writes business tables. The `worker` container consumes the stream (check-in answers follow in Prompt 10). Only scenes 1 (four signals) and 4 (check-in answers) contain data events; the other scenes need the platform or logged-in users.

### Signals and incidents

The `worker` container (`python -m app.workers`, same image as the backend) reads `RAW_SIGNAL` events from the stream. For each one it:

1. stores a `raw_signal` row, ignoring a repeat of the same source and `external_id`;
2. maps category and severity through that source's own maps, and discards the signal (with an audit entry) when a value is unknown;
3. joins it to an active incident of the same category within 3 km and 60 min, or opens a new one (D-10).

It then publishes `INCIDENT_CREATED` or `INCIDENT_UPDATED`. A second consumer group recomputes the incident's exposure on each of those events:
- people, sites and trips within the impact radius (D-22);
- the incident's mission, taken from the nearest exposed site (D-06);
- severity raised one level when a protected site is exposed (D-11).

It then publishes `EXPOSURE_COMPUTED`.

Any user with a role can read the results:

```sh
GET /api/signals?status=FUSED   # NEW, NORMALISED, FUSED or DISCARDED; newest first
GET /api/incidents?status=ACTIVE
GET /api/incidents/{id}         # with exposure, signals and timeline
```

Duty and Security Officers and the HQ Crisis Director can change an incident's status and add notes, and so can the Head of Mission for the incident's mission. Consular Officers and the Travel Desk can add notes too. Both actions are audited and appear on the timeline (INC-07):

```sh
PATCH /api/incidents/{id}/status   {"status": "MONITORING"}   # ACTIVE, MONITORING or CLOSED
POST  /api/incidents/{id}/notes    {"text": "..."}
```

`make logs` shows the worker's output.

### Everyday commands

```sh
make test        # backend + simulator (pytest) and frontend (Vitest), on the host
make lint        # ruff, mypy --strict, eslint, tsc --noEmit
make logs        # follow container logs
make down        # stop (keeps the database volume)
make reset-demo  # D-21: drop and recreate the local DB volume, then migrate + seed
make tiles       # D-24: map tiles, fonts and sprites into infra/tiles/ (downloads once)
make e2e         # Playwright against the running stack
```

`make reset-demo` only runs when `APP_ENV` is `local` or `demo`.

### Database tests

Backend tests run against the real PostgreSQL + PostGIS from `make up`; there is no SQLite and no DB mock. The tests use `TEST_ADMIN_DATABASE_URL` (a superuser) only to create throwaway databases (`nexira_test`, `nexira_test_migrations`). They then migrate those databases as `nexira_owner` and run every assertion as `nexira_api`. Your `nexira` database is not touched.

### Playbooks and approvals

A Duty or Security Officer starts a playbook for an ACTIVE incident; the worker runs its steps in order:

```sh
POST /api/playbook-runs   {"playbook_code": "PB-07", "incident_id": "..."}
GET  /api/playbook-runs/{id}                          # steps with status, timestamps, results
POST /api/playbook-runs/{id}/steps/{step_id}/approve  # gated steps (PB-07 step 7)
GET  /api/me/permissions?entity_type=playbook_run&entity_id=...   # steps you may approve now
```

- **Approvals:** `app/core/approvals.py` (`decide()`) checks every approval: role, mission scope from the incident, step order, and that no person decides two steps (D-05, D-16). Refusals are 403 or 409.
- **Step effects:** NOTIFY and CHECKIN steps create notification campaigns (NTF-3101 and on); sending them comes in Prompt 10.
- **No duplicates:** each step runs in one transaction with the run locked, so a worker restart never runs a step twice.
- **Resuming:** the worker resumes RUNNING runs for the tenants in `WORKER_TENANT_IDS`.
- **Pacing:** `PLAYBOOK_STEP_DELAY_S` adds a pause between steps for demos.

### Notifications and safety check-in

- **Sending:** NOTIFY and CHECKIN steps create a campaign and queue one delivery per recipient and channel in the same transaction (an outbox). The worker sends the queued deliveries through the channel adapter.
- **Simulated channels only:** Phase 1 has only `CHANNEL_ADAPTER=simulated`, so nothing leaves the platform (CHK-04). Deliveries move SENT → DELIVERED → READ over a few seconds.
- **Answers:** check-in answers come from the simulator (scene 4) and from staff through the API (D-28):

```sh
POST /api/checkin/{campaign_id}/respond   {"person_id": "...", "status": "SAFE" | "NEED_HELP"}
GET  /api/checkin/{campaign_id}/summary    # personnel and citizens: safe / need_help / pending / accounted %
GET  /api/checkin/{campaign_id}/people?group=personnel&status=PENDING
GET  /api/campaigns?incident_id=...        # campaigns with delivery counts
```

- **Latest answer counts:** every answer is kept, and the latest one counts.
- **Escalation:** after `escalate_after_s` (600 s; 20 s while a demo scenario runs), each silent staff member is escalated once, and silent citizens are escalated once as a group (plan G-19).
- **Worker settings:** escalation, and catching up on unsent deliveries, run in the worker for the tenants in `WORKER_TENANT_IDS`.

### Map and screens

`make tiles` downloads the map data once (about 90 MB) into `infra/tiles/`, which is not committed:
- `world.pmtiles` (zoom 0–6) and `nairobi.pmtiles` (zoom 0–15), extracted from a Protomaps daily build;
- fonts and sprites for the dark style.

The frontend container serves them at `/tiles/`. After that the map needs no internet connection (D-24).

- `TILES_BUILD=YYYYMMDD make tiles` pins a build.
- Without tiles, the map shows a plain background and still draws missions, incidents and people.

The browser keeps one WebSocket per tab on `/ws` (PLT-05):
- It sends the access token in its first message, never in the URL, and renews it every minute.
- The server forwards only events for the user's tenant, with ids and counts and no personal data.
- Screens then refetch through the REST API.

Read APIs used by the screens, for any user with a role:

```sh
GET /api/missions                    # display_risk = max(baseline, worst ACTIVE incident) (plan G-22)
GET /api/people?q=&in_zone=&limit=   # with location confidence and source; no phone or email
GET /api/sites?q=                    # mission_property counts site types other than HOTEL (D-23)
GET /api/operations/summary          # the KPI strip (D-27)
```

`make e2e` runs the Playwright test: scene 1 started through the API puts the incident on the map without a reload. It needs `make up` and seeded data, and it moves any ACTIVE incidents to MONITORING first.

### Frontend development with hot reload

```sh
make up                      # backend and dependencies
cd frontend && npm run dev   # http://localhost:5173, proxies /api to :8000
```

### Running the backend on the host

```sh
cd backend
uv sync
set -a; . ../.env; set +a
uv run uvicorn app.main:app --reload
uv run python -m app.workers      # in a second terminal: the stream consumer
```

## Repository layout

```
backend/    FastAPI app (app/core, app/modules/<domain>), Alembic migrations
frontend/   React 18 + TypeScript + Vite, Blueprint dark theme
simulator/  seed data and scenario player (fictional data only)
infra/      docker-compose, PostgreSQL image + init, Keycloak realm, tiles
docs/       decisions, requirements, schema, design reference, plan
```
