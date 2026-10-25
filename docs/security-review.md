# Security review checklist (human reviewer)

For the named human reviewer who signs off D-29 changes. It lists what to check before a pilot, where the code is, and how to test it. All line numbers are for Prompt 16.

**Every box is unchecked on purpose.** This file was written by an AI agent, and an agent must not mark items as reviewed (Prompt 16). The reviewer ticks each item, adds their name and the date, and records findings below the section. The position against ASVS L2 is in [security/asvs-l2.md](security/asvs-l2.md).

Reviewed by: ______________________  Date: __________  Commit: __________

## How to run the evidence

```sh
make up && make reset-demo   # local stack, demo data only
make test                    # backend (real PostgreSQL + PostGIS, as nexira_api), simulator, frontend
make acceptance              # the Phase 1 scenario end to end, ending with /api/audit/verify
make restore-test            # backup as nexira_backup, restore, verify RLS and audit chains
make helm-check              # chart lint, render, Kubernetes schema validation
```

---

## 1. Tenant isolation: RLS and database roles (D-01, D-02, D-03)

- [ ] Every tenant table has `ENABLE` and `FORCE ROW LEVEL SECURITY` and the `tenant_isolation` policy with both `USING` and `WITH CHECK`. See `docs/schema/nexira_schema.sql:750-771`. The table `tenant` is enabled but not forced; it has the `tenant_self` policy (line 771). Is that intended?
- [ ] `current_tenant_id()` (`nexira_schema.sql:45`) returns NULL when no tenant is set, so a session without a tenant sees no rows (test `test_01_no_tenant_returns_zero_rows_without_error`).
- [ ] `resolve_tenant_by_issuer()` (`nexira_schema.sql:774-777`) is the **only** `SECURITY DEFINER` cross-tenant read. It has `search_path` pinned and `EXECUTE` revoked from PUBLIC.
- [ ] The grants in `nexira_schema.sql:815-825` give `nexira_app` no more than it needs. Note PC-04 (it can update `reference_counter`) and PC-05 (it can delete undecided `proposal_approval` rows), both in `docs/schema/proposed-changes.md`.
- [ ] Every transaction calls `set_config('app.tenant_id', :tid, true)` and never `SET LOCAL … = :param`. See `backend/app/core/db.py:47` and `tenant_session` (line 87).
- [ ] The API refuses to start as a superuser or BYPASSRLS role: `verify_connection_role`, `backend/app/core/db.py:105`.
- [ ] Bootstrap roles: `infra/postgres/init.sql`. `nexira_owner`, `nexira_app` and `nexira_api` are NOSUPERUSER and NOBYPASSRLS. PUBLIC has no CONNECT and cannot CREATE in `public`.
- [ ] Tests: `backend/app/tests/test_tenant_isolation.py`, `test_schema_checks.py`, `test_db_session.py`, `test_migrations.py`.

## 2. New in Prompt 16: the backup role (grants change, D-29)

- [ ] `infra/postgres/backup-role.sql` creates `nexira_backup` with **BYPASSRLS** and `pg_read_all_data`. It is not a superuser, cannot create roles or databases, is not a member of `nexira_app` or `nexira_owner`, and has no write privilege.
  - It is needed because FORCE RLS stops the owner from running `pg_dump`.
  - Decide whether a BYPASSRLS read-all role is acceptable, and how its password is held: the backup Secret, mounted only by the CronJob.
- [ ] The test `backend/app/tests/test_backup_role.py` checks these properties.
- [ ] Restore runs as the superuser (`infra/helm/nexira/files/backup/restore.sh`) and only into a new database. Is that acceptable as a break-glass procedure?

## 3. Authentication (`backend/app/core/security.py`, D-04)

- [ ] `decode_token` (line 113):
  - RS256 only; a `kid` is required and must be in the JWKS;
  - issuer and audience checked;
  - `exp`, `iat`, `iss`, `aud` and `sub` required;
  - 30 s leeway.
- [ ] The JWKS URL comes from config, never from the token (`get_jwks` line 77, `JwksCache`). Its refresh is rate-limited (`min_refresh_s`).
- [ ] The tenant comes from the issuer only (`principal_from_token`, line 134). Role claims in the token are ignored everywhere. Search for `realm_access`, `resource_access` and `roles` in `backend/app` and `frontend/src`.
- [ ] First login creates `app_user` and audits it (`current_user`, line 188). Inactive users get 403 on every request (`active_user`, line 223).
- [ ] Tests: `backend/app/tests/test_security.py`.

## 4. Approvals: roles and mission scope (`backend/app/core/approvals.py`, D-05, D-16)

- [ ] `can_decide` (line 126) and `decide` (line 151) are the only place where approval roles and mission scope are checked, for both agent proposals and playbook gates. Search for other checks of `role` or `HEAD_OF_MISSION` outside this file.
- [ ] Role alternatives (`DUTY_OFFICER|SECURITY_OFFICER`) are parsed by `parse_role_codes` (line 50). Mission-scoped roles match `incident.mission_id`, and unscoped roles are not treated as matching every mission by mistake.
- [ ] The same person cannot take two steps (D-16). Steps are taken in order. A decision can be made once only.
- [ ] Playbook gates: `backend/app/modules/playbooks/service.py:236` (`approve_step`) uses `approvals.decide` with the run locked. PC-06 (no database backstop for playbook steps) is still open.
- [ ] Tests: `backend/app/tests/test_approvals.py`, `test_approvals_decide.py`, `test_playbooks.py`, and e2e `frontend/e2e/scene5-decisions.spec.ts`.

## 5. Audit (`backend/app/core/audit.py`, D-20)

- [ ] `audit.write` (line 19) only inserts. The hash chain is computed by the trigger `audit_log_chain` (`nexira_schema.sql:679`). UPDATE, DELETE (line 687) and TRUNCATE are blocked.
- [ ] Every state-changing route writes an audit row. Check each POST and PATCH in `backend/app/modules/*/router.py` against the service function it calls. Known exceptions: simulated delivery status changes and bulk seeding (plan G-20, an open question).
- [ ] `audit_verify_chain()` (`nexira_schema.sql:694`) and `GET /api/audit/verify` (`backend/app/modules/audit/router.py:55`) detect a changed row. `verify.sh` checks every tenant after a restore; the tamper test is recorded in `docs/runbooks/backup-restore.md`.

## 6. AI agents: proposal, approval and execution (D-12, D-14, D-16, D-17)

- [ ] Agents never write to the database or call channels directly.
  - `observe()` runs in a session that is always rolled back (`backend/app/modules/agents/runner.py:1-30`).
  - Proposals are created only through `proposals.create` (`backend/app/modules/agents/proposals.py:111`).
- [ ] `effective_level` and the approval rows are set by the database (`nexira_schema.sql:462-603`: `agent_proposal_level`, `agent_proposal_frozen`, `agent_proposal_approvals`). The app never writes `effective_level`. Search `backend/app` for writes.
- [ ] Execution happens only when the number of approved steps equals `REQUIRED_STEPS[effective_level]`, not when "all rows are approved". See `proposals.py:45` and `:422`, and PC-05. Execution goes through the same service functions users call (`backend/app/modules/agents/actions.py`, `ACTIONS` line 174, `execute` line 235).
- [ ] Edit-and-approve cannot change `action_type` or widen the audience beyond the editable field (`EDITABLE_FIELD`; plan G-21).
- [ ] The kill switch: while agents are paused, nothing is proposed or executed (`set_paused` line 685; the trigger at `nexira_schema.sql:495` refuses inserts).
- [ ] Overdue proposals expire and escalate (`expire_overdue` line 626).
- [ ] No production agent can emit `START_EVACUATION`. Only the local/demo test fixture can (`simulator/nexira_sim/fixtures/evacuation.py`).
- [ ] No external AI calls. `backend/app/core/llm.py` has only a stub, and nothing calls it in Phase 1.
- [ ] Tests: `backend/app/tests/test_proposals.py`, `test_agents.py`, `simulator/tests/test_agents_nbo.py`.

## 7. WebSocket authentication (`backend/app/core/realtime.py`)

- [ ] The token arrives in the first message within 10 s, never in the URL (lines 197-225, `_authorise` line 179).
  - It is validated by the same `principal_from_token`.
  - An active user with a role is required.
  - Close codes: 4401, 4403 and 4408.
- [ ] Re-authentication on token refresh keeps the same subject and tenant. The socket closes when the token expires.
- [ ] Fan-out sends an event only to sockets of the event's tenant, and only `FORWARDED` types. Payloads have ids and counts, not personal data.
- [ ] The `Origin` header is not checked. Is that acceptable, given bearer tokens and no cookies?
- [ ] Tests: `backend/app/tests/test_realtime.py`.

## 8. Channel adapters (`backend/app/modules/notifications/channels.py`, CHK-04)

- [ ] `SimulatedChannelAdapter` (line 49) is the only adapter. `adapter_for` (line 81) refuses anything else, and `CHANNEL_ADAPTER` accepts only `simulated` (`backend/app/core/config.py`).
- [ ] Dispatch uses idempotency (delivery id) and SKIP LOCKED, with conditional completion (`backend/app/modules/notifications/consumer.py`, `service.py`).
- [ ] Simulated check-in answers and the `CHECKIN_CLOCK` event are accepted only while a demo scenario is running (`backend/app/modules/checkin/consumer.py`).

## 9. New in Prompt 16: deployment and hardening

- [ ] **Pilot mode.** `APP_ENV=pilot` removes the scenario API and the API docs (`backend/app/main.py`, `create_app`; test `test_a_pilot_has_no_scenario_api_and_no_api_docs`). The chart always sets `APP_ENV=pilot` (`infra/helm/nexira/templates/configmap.yaml`).
- [ ] **Secrets.** There are separate Secrets for the API, owner, backup and Redis users, and each workload mounts only its own:
  - backend and worker: `api`;
  - migrate: `owner` only (`backend/migrations/env.py` reads `MIGRATIONS_DATABASE_URL` directly);
  - backup: `backup` only.

  Check this in the output of `helm template … -f infra/helm/nexira/ci/pilot-values.yaml`.
- [ ] **Network policies** (`infra/helm/nexira/templates/networkpolicies.yaml`, `_netpol.tpl`):
  - default-deny for the release;
  - no egress except PostgreSQL, Redis, DNS, the configured IdP and (when enabled) the LLM gateway;
  - on the first install the migrate hook runs before the policies exist.
- [ ] **Pod security:** non-root, read-only root filesystem, all capabilities dropped, RuntimeDefault seccomp, no service-account token (`_helpers.tpl`).
- [ ] **Headers:** the CSP and other headers (`frontend/security-headers.conf.template`, `templates/frontend-configmap.yaml`) and `Cache-Control: no-store` on `/api/`. The acceptance e2e suite fails on CSP violations (`frontend/e2e/support.ts`).
- [ ] **The demo seed** refuses to run outside local or demo (`simulator/nexira_sim/seed/__main__.py`). The fixtures already did.
- [ ] **Deny by default.** Every API operation except `/api/health` requires a bearer token (`test_every_api_operation_but_health_needs_a_bearer_token`).
- [ ] **Not tested on a real cluster.** The chart has been linted and schema-validated, not installed on one (G-16).

## 10. Pilot prerequisites outside this repository

- [ ] A pilot Keycloak realm with MFA required and no password-grant client (G-02; `docs/runbooks/pilot-deployment.md` §4).
- [ ] Encrypted storage classes for PostgreSQL, Redis and the backups; off-site copies of the backups.
- [ ] TLS 1.3 at the ingress or route; TLS to PostgreSQL (`?ssl=require`).
- [ ] The gaps in `docs/security/asvs-l2.md` accepted or scheduled by the pilot's risk owner.

## Findings

| # | Section | Finding | Severity | Owner | Status |
|---|---|---|---|---|---|
| | | | | | |
