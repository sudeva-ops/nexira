# Backup and restore

For pilot operators. Covers requirement NFR 7 ("daily backups; documented restore"). The scripts are in [`infra/helm/nexira/files/backup/`](../../infra/helm/nexira/files/backup/). The Helm CronJob and `make backup` run the same files.

## What is backed up

| Data | Backed up? | Notes |
|---|---|---|
| PostgreSQL database (all tenants, the audit log, Alembic version) | Yes, nightly | `pg_dump --format=custom`, plus a `.sha256` file |
| Redis (internal event stream) | No | Events are transient, and the database is the source of truth. After a Redis loss, playbook runs resume from the database (the worker's 60 s resume loop) and queued notifications are still sent (they are an outbox in PostgreSQL). An event that was in flight is lost, though. If it would have triggered an exposure computation or an agent proposal, that does not happen until the next event for the same incident. The in-chart Redis keeps an append-only file on a volume to make this rare. |
| Keycloak (users, MFA enrolment) | No, not by NEXIRA | Back it up with your IdP's own procedure |
| Map tiles | No | Rebuilt with `make tiles` (D-24) |

## How it works

- **Role.** The dump connects as **`nexira_backup`** ([`infra/postgres/backup-role.sql`](../../infra/postgres/backup-role.sql) for the role, [`backup-grants.sql`](../../infra/postgres/backup-grants.sql) for its grants).
  - Every table has FORCE ROW LEVEL SECURITY, so neither `nexira_owner` nor `nexira_api` can dump the database. `pg_dump` stops with "query would be affected by row-level security policy".
  - `nexira_backup` has `BYPASSRLS` and `SELECT` on the tables and sequences of schema `public` only, including tables that later migrations create (default privileges for `nexira_owner`).
  - It is deliberately **not** a member of `pg_read_all_data`. That role would also let it read `pg_authid` (every role's password hash) and every other database in the cluster.
  - It cannot insert, update, delete or truncate any table, or create objects. `backend/app/tests/test_backup_role.py` checks all of this, including acting as the role.
  - One write remains: like every PostgreSQL role, it can create large objects (`lo_create`). NEXIRA uses none. This is accepted; a `pg_hba.conf` rule can also limit the role to the NEXIRA database.
- **Schedule.** 22:00 UTC (02:00 GST), set by `backup.schedule`.
- **Retention.** `backup.keepDays`, 14 by default. The script never deletes the dump it has just written.
- **Partial dumps.** A dump is written as `*.partial` and renamed only when `pg_dump` succeeds, so a failed run never leaves a file that looks good.
- **Manifest.** Just before the dump, `backup.sh` writes `<dump>.manifest`: each tenant's newest audit row (`chain_seq` and `row_hash`). The audit log is append-only, so every row listed must be in the dump. The `.sha256` file covers the dump and the manifest.
- **Storage.** A PersistentVolumeClaim, `<release>-backups`. It has `helm.sh/resource-policy: keep`, so uninstalling the chart does not delete it.
  - Use an **encrypted storage class** (NFR 2: AES-256 at rest).
  - Copy dumps off the cluster (to a second site or offline media) with your platform's tooling. Off-site copy is not part of Phase 1 (see the ASVS gap list).

### Existing clusters

`infra/postgres/init.sql` creates `nexira_backup` and its grants on a new cluster. On a cluster bootstrapped before Prompt 16, run both files once as the superuser:

```sh
psql -v ON_ERROR_STOP=1 -U postgres -d nexira \
  -v backup_password="$NEXIRA_BACKUP_PASSWORD" -f infra/postgres/backup-role.sql
psql -v ON_ERROR_STOP=1 -U postgres -d nexira -f infra/postgres/backup-grants.sql
```

## Restore

A restore is a **break-glass operator action**. It runs as the PostgreSQL **superuser**, because it recreates objects owned by `nexira_owner` and writes every tenant's rows. Always restore into a **new** database and then switch over; `restore.sh` refuses to restore into a database that already exists.

1. **Stop writers.** Scale the backend and worker to 0, e.g. `kubectl scale deploy/<release>-backend deploy/<release>-worker --replicas=0`.
2. **Pick a dump** and copy it, with its `.manifest` and `.sha256` files, to a pod or host that has `psql` and `pg_restore` 16. The `nexira-postgres` image has both. Take the scripts from `infra/helm/nexira/files/backup/`; in the cluster they are in the `<release>-backup-scripts` ConfigMap, not in the image.
3. **Restore and verify:**
   ```sh
   PGHOST=<db host> PGUSER=postgres PGPASSWORD=<superuser password> \
     ./restore.sh /backups/nexira-<timestamp>.dump nexira_restored
   ```
   - `restore.sh` checks the SHA-256 of the dump and the manifest, and creates the database with the same grants as `init.sql`. It loads the dump with `--exit-on-error`, then runs `verify.sh` with the manifest.
   - `verify.sh` checks:
     - the Alembic version;
     - that every table with a `tenant_id` has RLS enabled, forced and with a policy;
     - **every tenant's audit hash chain** (`audit_verify_chain()`, D-20);
     - from the manifest, that each tenant's newest backed-up audit row is present with the same hash.

     It exits 1 on any failure. A failing query stops it; it never reports success because a check found nothing to check.
   - Rows are loaded before triggers and policies are created, so `audit_log` keeps its stored hashes.
   - What the checks prove, together: the chain check proves the restored log is internally consistent, so no row was changed or removed from the middle. The manifest check proves that the end of the log was not lost. A dump without a manifest (made before this version) gets the chain check only, and `verify.sh` warns about it.
4. **Switch over** (as the superuser, with no connections to either database):
   ```sql
   ALTER DATABASE nexira RENAME TO nexira_before_restore;
   ALTER DATABASE nexira_restored RENAME TO nexira;
   ```
   Keep `nexira_before_restore` until the restore has been accepted.
5. **Start** the backend and worker again. The migrate hook runs on the next `helm upgrade`; it does nothing if the schema is current. Then check `GET /api/audit/verify` as an admin user.

**Recovery points.**
- **RPO** (data you can lose): up to 24 hours with nightly dumps. Shorter needs WAL archiving (point-in-time recovery). That is not part of Phase 1.
- **RTO** (time to restore): the demo database (700 KB dump) backs up, restores and verifies in about 3 s on a laptop. Measure it again on pilot data volumes before agreeing an RTO.

## Restore test

`make restore-test` (local docker-compose) does the whole cycle:
1. backs up as `nexira_backup`;
2. restores into a scratch database `nexira_restore_test` and runs `verify.sh` with the manifest;
3. compares the RLS flags, policies and triggers with the source;
4. compares the row counts of all 35 tables with the source, but only if nothing was written during the backup. Otherwise it warns and skips this step; the manifest check still covers the audit log;
5. drops the scratch database.

On a pilot, run the same script once after install and then at least quarterly, from a pod with the `nexira-postgres` image. For a strict row-count comparison, scale the backend and worker to 0 first.

### Recorded test (Prompt 16, 2026-10-25)

Run on the local stack after the Phase 1 acceptance scenario (`make acceptance`), as required by the prompt ("tested once"):

```
$ make restore-test
backup ok: /backups/nexira-20261025T101325Z.dump (700K)
nexira-20261025T101325Z.dump: OK
nexira-20261025T101325Z.dump.manifest: OK
schema version: 0001
row-level security: enabled, forced and with a policy on every tenant table
tenant c31e14ca-ec60-5407-8371-6599eadc8e3e: 489 audit rows, newest seq 489, chain intact
manifest: the newest audit row of 1 tenant(s) is present and unchanged
verify ok: nexira_restore_test
RLS flags, 33 policies and 11 triggers match the source
row counts match: 35 tables
restore test ok: /backups/nexira-20261025T101325Z.dump
real 3.12
```

**Negative checks, the same day.** Each one restored the dump into a scratch database, broke it as the superuser, and ran `verify.sh` with the manifest. Each failed with exit 1:

| Change made | `verify.sh` output |
|---|---|
| One audit row changed (no-update trigger disabled) | `audit chain broken at chain_seq 5` |
| The newest audit row deleted. The chain itself still verified as intact. | `audit row 489 from the backup manifest is missing or changed` |
| `ALTER TABLE incident NO FORCE ROW LEVEL SECURITY` | `tenant tables without RLS enabled, forced and a policy: incident` |
| A database name that does not exist | psql's connection error (exit 2) |

**Where it ran.** This test ran on docker-compose, not on a Kubernetes cluster. The backup image also ran there the way the chart runs it, with UID 10001, a read-only root filesystem and no capabilities. The CronJob itself has been rendered and schema-validated (`make helm-check`) but not run on a cluster.
