# Proposed schema changes

Changes to `docs/schema/nexira_schema.sql` (v0.2) that are **proposed, not approved**. Nothing here goes into a migration until a human approves it, and changes to RLS or grants also need a D-29 sign-off. Once approved, each change ships as a new Alembic migration; migration 0001 is never edited.

| ID | Status | Change | Why | Source |
|---|---|---|---|---|
| PC-01 | Proposed | `list_tenant_ids()` — `SECURITY DEFINER`, returns `SETOF uuid` from `tenant`, `EXECUTE` granted to `nexira_app` only | Background jobs (proposal expiry, check-in escalation) have no token, so they cannot discover tenants. D-04 allows only `resolve_tenant_by_issuer` as a cross-tenant read, so this needs a decision. Phase 1 uses `WORKER_TENANT_IDS` from config instead. | plan G-01, Q6 |
| PC-02 | Proposed | `action_policy.undo_window_s integer NOT NULL DEFAULT 300 CHECK (undo_window_s > 0)` | The undo window for level 1 is not defined anywhere. Phase 1 uses the `UNDO_WINDOW_S` config value. | plan G-17, Q7 |
| PC-03 | Proposed | In the migration that adds the first new table: `ALTER DEFAULT PRIVILEGES FOR ROLE nexira_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nexira_app` (and the same for sequences) | v0.2 grants `ON ALL TABLES` only once, so tables created later would have no runtime grants. The alternative is explicit grants in every migration. Either way, the catalogue test `test_every_tenant_table_forces_rls_with_tenant_policy` catches a missing RLS policy. | plan G-02 |
| PC-04 | Proposed | Make `next_reference()` `SECURITY DEFINER` (with `SET search_path`), then `REVOKE INSERT, UPDATE, DELETE ON reference_counter FROM nexira_app` | Today `nexira_api` can `UPDATE reference_counter SET last_value = …` in its own tenant. Unique keys on `reference` stop duplicates, but the next inserts would fail. Found in the Prompt 2 security check. | D-18 |
| PC-05 | Proposed | Block `DELETE` on `proposal_approval` (trigger or revoke), and block `INSERT` of extra steps after the proposal row exists | `nexira_app` can delete an undecided approval row, or add one. Until then the executor (Prompt 12) must check that the number of approved steps equals the number required by `effective_level` (1 for level 2, 2 for level 3), not just that "all rows are approved". Found in the Prompt 2 security check. | D-16 |
| PC-06 | Proposed | `CREATE UNIQUE INDEX playbook_run_step_distinct_approver_uq ON playbook_run_step (run_id, approved_by) WHERE approved_by IS NOT NULL`, plus a trigger that allows setting `approved_by` only while the step is `AWAITING_APPROVAL` and never changing it afterwards | Playbook gates have no database backstop for D-16 (one person, one step) or for decided-once. Today `approvals.decide()` enforces both, with the run row locked, and that is the only enforcement. `proposal_approval` already has the equivalent index and triggers. Found in the independent review of Prompt 9. | D-16, plan G-08 |

## Applied outside the schema file

These are part of migration 0001, but they are not changes to the schema file:

- `REVOKE ALL ON alembic_version FROM nexira_app`. Alembic creates `alembic_version` before the schema runs, so the schema's `GRANT ... ON ALL TABLES` also covered it, and the API could have changed migration state. Tested in `app/tests/test_migrations.py`.
