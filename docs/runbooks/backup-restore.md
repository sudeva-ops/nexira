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

- **Role.** The dump connects as **`nexira_backup`** ([`infra/postgres/backup-role.sql`](../../infra/postgres/backup-role.sql)).
  - Every table has FORCE ROW LEVEL SECURITY, so neither `nexira_owner` nor `nexira_api` can dump the database. `pg_dump` stops with "query would be affected by row-level security policy".
  - `nexira_backup` has `BYPASSRLS` and `pg_read_all_data`. It cannot write, create objects or log in as another role. `app/tests/test_backup_role.py` checks this.
- **Schedule.** 22:00 UTC (02:00 GST), set by `backup.schedule`.
- **Retention.** `backup.keepDays`, 14 by default. The script never deletes the dump it has just written.
- **Partial dumps.** A dump is written as `*.partial` and renamed only when `pg_dump` succeeds, so a failed run never leaves a file that looks good.
- **Storage.** A PersistentVolumeClaim, `<release>-backups`. It has `helm.sh/resource-policy: keep`, so uninstalling the chart does not delete it.
  - Use an **encrypted storage class** (NFR 2: AES-256 at rest).
  - Copy dumps off the cluster (to a second site or offline media) with your platform's tooling. Off-site copy is not part of Phase 1 (see the ASVS gap list).

### Existing clusters

`infra/postgres/init.sql` creates `nexira_backup` on a new cluster. On a cluster bootstrapped before Prompt 16, run this once as the superuser:

```sh
psql -v ON_ERROR_STOP=1 -U postgres -d nexira \
  -v backup_password="$NEXIRA_BACKUP_PASSWORD" -v db_name=nexira \
  -f infra/postgres/backup-role.sql
```

## Restore

A restore is a **break-glass operator action**. It runs as the PostgreSQL **superuser**, because it recreates objects owned by `nexira_owner` and writes every tenant's rows. Always restore into a **new** database and then switch over; `restore.sh` refuses to restore into a database that already exists.

1. **Stop writers.** Scale the backend and worker to 0, e.g. `kubectl scale deploy/<release>-backend deploy/<release>-worker --replicas=0`.
2. **Pick a dump** and copy it and its `.sha256` file to a pod or host that has `psql`, `pg_restore` 16 and the scripts. The `nexira-postgres` image has all three.
3. **Restore and verify:**
   ```sh
   PGHOST=<db host> PGUSER=postgres PGPASSWORD=<superuser password> \
     ./restore.sh /backups/nexira-<timestamp>.dump nexira_restored
   ```
   - `restore.sh` checks the SHA-256 and creates the database with the same grants as `init.sql`. It loads the dump with `--exit-on-error`, then runs `verify.sh`.
   - `verify.sh` checks:
     - the Alembic version;
     - that every table with a `tenant_id` has FORCE RLS;
     - **every tenant's audit hash chain** (`audit_verify_chain()`, D-20).

     It exits 1 on any failure.
   - Rows are loaded before triggers and policies are created, so `audit_log` keeps its stored hashes. The chain check proves the restored log matches the backup exactly.
4. **Switch over** (as the superuser, with no connections to either database):
   ```sql
   ALTER DATABASE nexira RENAME TO nexira_before_restore;
   ALTER DATABASE nexira_restored RENAME TO nexira;
   ```
   Keep `nexira_before_restore` until the restore has been accepted.
5. **Start** the backend and worker again. The migrate hook runs on the next `helm upgrade`; it does nothing if the schema is current. Then check `GET /api/audit/verify` as an admin user.

**Recovery points.**
- **RPO** (data you can lose): up to 24 hours with nightly dumps. Shorter needs WAL archiving (point-in-time recovery). That is not part of Phase 1.
- **RTO** (time to restore): the demo database (616 KB dump) backs up, restores and verifies in about 3 s on a laptop. Measure it again on pilot data volumes before agreeing an RTO.

## Restore test

`make restore-test` (local docker-compose) does the whole cycle:
1. backs up as `nexira_backup`;
2. restores into a scratch database `nexira_restore_test` and runs `verify.sh`;
3. compares the row counts of all 35 tables, and the RLS flags, policies and triggers, with the source;
4. drops the scratch database.

On a pilot, run the same script once after install and then at least quarterly, from a pod with the `nexira-postgres` image.

### Recorded test (Prompt 16, 2026-10-25)

Run on the local stack after the Phase 1 acceptance scenario (`make acceptance`), as required by the prompt ("tested once"):

```
$ make restore-test
backup ok: /backups/nexira-20261025T094703Z.dump (616K)
nexira-20261025T094703Z.dump: OK
schema version: 0001
row-level security: forced on every tenant table
tenant c31e14ca-ec60-5407-8371-6599eadc8e3e: 345 audit rows, chain intact
verify ok: nexira_restore_test
row counts match: 35 tables
RLS flags, 33 policies and 11 triggers match
restore test ok: /backups/nexira-20261025T094703Z.dump
real 2.66
```

Tamper check, done the same day: the dump was restored into a scratch database, and one audit row was changed there (with the no-update trigger disabled as the superuser). `verify.sh` reported `chain 5` and `FAIL: an audit chain is broken`, and exited 1.

This test was run on docker-compose, not on a Kubernetes cluster. The CronJob itself has been rendered and schema-validated (`make helm-check`) but not run on a cluster yet.
