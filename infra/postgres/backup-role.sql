-- nexira_backup: the role the nightly pg_dump connects as (Prompt 16, NFR 7).
-- Run as the superuser: by init.sql on a new cluster, or once by hand on an
-- existing one (docs/runbooks/backup-restore.md). psql variable: backup_password.
-- Changes need human sign-off (D-29: grants). The per-database grants are in
-- backup-grants.sql.
--
-- Every table has FORCE ROW LEVEL SECURITY and nexira_app sees one tenant at a
-- time, so neither nexira_owner nor nexira_api can dump the database (pg_dump
-- stops with "query would be affected by row-level security policy"). This role
-- reads the NEXIRA tables of every tenant and nothing else:
--   BYPASSRLS   reads all tenants' rows (needed for a whole-database dump)
--   SELECT      on the tables and sequences of schema public only (backup-grants.sql);
--               not pg_read_all_data, which would also expose pg_authid's password
--               hashes and every other database in the cluster
--   no ownership, no CREATE, not a superuser, not a member of nexira_app.
-- Only the backup CronJob gets its password. Restores run as the superuser.

CREATE ROLE nexira_backup LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS
  PASSWORD :'backup_password';
