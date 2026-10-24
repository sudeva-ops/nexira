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

### Everyday commands

```sh
make test        # backend + simulator (pytest) and frontend (Vitest), on the host
make lint        # ruff, mypy --strict, eslint, tsc --noEmit
make logs        # follow container logs
make down        # stop (keeps the database volume)
make reset-demo  # D-21: drop and recreate the local DB volume, then migrate + seed
make tiles       # Prompt 8: builds self-hosted PMTiles into infra/tiles/
```

`make reset-demo` only runs when `APP_ENV` is `local` or `demo`.

### Database tests

Backend tests run against the real PostgreSQL + PostGIS from `make up`; there is no SQLite and no DB mock. The tests use `TEST_ADMIN_DATABASE_URL` (a superuser) only to create throwaway databases (`nexira_test`, `nexira_test_migrations`). They then migrate those databases as `nexira_owner` and run every assertion as `nexira_api`. Your `nexira` database is not touched.

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
```

## Repository layout

```
backend/    FastAPI app (app/core, app/modules/<domain>), Alembic migrations
frontend/   React 18 + TypeScript + Vite, Blueprint dark theme
simulator/  seed data and scenario player (fictional data only)
infra/      docker-compose, PostgreSQL image + init, Keycloak realm, tiles
docs/       decisions, requirements, schema, design reference, plan
```
