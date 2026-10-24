# NEXIRA – rules for AI coding agents

Copy this file to `.github/copilot-instructions.md` too (Cursor: `.cursor/rules/nexira.mdc`). Keep the copies identical.

## Product
NEXIRA is a sovereign resilience platform for organisations with people and sites abroad
(first customer type: a ministry of foreign affairs).

Sources of truth, in this order:
1. `docs/decisions.md` – settles conflicts; cite decision IDs (D-xx) in code comments and PRs.
2. `docs/requirements.md` – Phase 1 requirements (PRD v0.1).
3. `docs/schema/nexira_schema.sql` – Phase 1 database (v0.2).
4. `docs/design/NEXIRA_Demo_Full.html` – visual reference only (D-25). Match layout and
   Blueprint dark styling. Do not copy its code, state handling or patching pattern.

Phase 1 screens (build only these): Decision Queue (home), AI Agents, Global Operations,
Incidents, People & Sites, Response Playbooks, Safety Check-in, Audit view, Presenter bar
(demo mode only). Every other screen in the demo is out of scope (D-25).

## Stack (do not substitute)
- Backend: Python 3.12, FastAPI, SQLAlchemy 2.x (async, asyncpg), Alembic, Pydantic v2, pytest.
- DB: PostgreSQL 16 + PostGIS 3. geography(Point,4326) for all locations.
- Realtime: Redis Streams for internal events; WebSockets to the browser.
- Frontend: React 18 + TypeScript + Vite, @blueprintjs/core (dark theme), MapLibre GL with
  self-hosted PMTiles (D-24), TanStack Query, Vitest, Playwright.
- Auth: Keycloak (OIDC) for authentication only. Tenant from the token issuer; roles and
  mission scope from the `user_role` table. Never use role claims from the token or the client (D-04).
- Packaging: Docker; docker-compose locally; no cloud-only services; no external URLs at runtime.

## Architecture rules
- Monorepo: /backend, /frontend, /simulator, /infra, /docs.
- Backend modules: app/modules/<domain>/{models,schemas,service,router,tests}.
- The API connects only as `nexira_api` (member of `nexira_app`), never as the owner or a
  superuser, because those bypass row-level security (D-01).
- Each transaction starts with `SELECT set_config('app.tenant_id', :tid, true)` (D-02).
  Never `SET LOCAL ... = :param`.
- Every state-changing action writes to audit_log via app/core/audit.py. audit.py inserts
  rows only; the database computes the hash chain (D-20). No exceptions.
- All role and mission-scope checks for approvals go through app/core/approvals.py, for both
  agent proposals and playbook gates (D-05, D-16).
- AI agents act only through the proposal/approval flow in app/modules/agents and then
  through the same service functions users call. Agents never call channels, external
  systems or the database directly. The database sets effective_level; the app never writes it (D-12).
- No real personal data in code, fixtures or tests. Simulator data only.
- No calls to external AI APIs. LLM access goes through app/core/llm.py (local vLLM/Ollama
  endpoint, plus a stub for tests).
- No real SMS/email/WhatsApp in Phase 1; channel adapters are simulated.

## Code quality
- Type hints everywhere; ruff + mypy (strict) for Python, eslint + `tsc --noEmit` for TS.
- Each feature ships with tests. Database tests run against real PostgreSQL + PostGIS
  (testcontainers or the CI service), connected as `nexira_api`. No SQLite, no DB mocks.
- Run tests and linters before declaring a task done; report the actual output.
- Small, reviewable changes. Explain any deviation from requirements or decisions in the PR.
- Do not change the schema in place. Propose changes in docs/schema/proposed-changes.md and
  add them as new Alembic migrations only after a human approves.
- Changes to RLS/grants, security.py, approvals.py, audit.py, the agent policy engine/executor
  and channel adapters need a named human reviewer's sign-off in the PR (D-29).
- Never commit secrets. Configuration keys go in .env.example.
