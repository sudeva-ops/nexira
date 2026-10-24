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
```

| Service | URL | Notes |
|---|---|---|
| Frontend | http://localhost:3000 | nginx serving the built app; proxies `/api` and `/ws` to the backend |
| Backend | http://localhost:8000/api/health | FastAPI; API docs at `/api/docs` |
| Keycloak | http://localhost:8080 | admin login from `.env`; realm `nexira-demo` |
| PostgreSQL 16 + PostGIS 3 | localhost:5432 | database `nexira` |
| Redis | localhost:6379 | |

All ports are bound to 127.0.0.1. Change them in `.env` if they clash with something already running.

### Database roles (D-01)

`infra/postgres/init.sql` runs once, as the superuser, when the data volume is first created. It installs PostGIS and pgcrypto and creates three roles:

- `nexira_owner` owns the database and runs migrations. It is not a superuser.
- `nexira_app` is the group role that holds the runtime grants.
- `nexira_api` is the only role the backend connects as.

Only the one-shot `migrate` service receives the owner password; the backend container never does.

### Everyday commands

```sh
make test        # backend + simulator (pytest) and frontend (Vitest), on the host
make lint        # ruff, mypy --strict, eslint, tsc --noEmit
make logs        # follow container logs
make down        # stop (keeps the database volume)
make reset-demo  # D-21: drop and recreate the local DB volume, then migrate + seed
make seed        # Prompt 4
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
