-- nexira_backup: the role the nightly pg_dump connects as (Prompt 16, NFR 7).
-- Run as the superuser: by init.sql on a new cluster, or once by hand on an
-- existing one (docs/runbooks/backup-restore.md). psql variables: backup_password,
-- db_name. Changes need human sign-off (D-29: grants).
--
-- Every table has FORCE ROW LEVEL SECURITY and nexira_app sees one tenant at a
-- time, so neither nexira_owner nor nexira_api can dump the database (pg_dump
-- stops with "query would be affected by row-level security policy"). This role
-- can read every row and change nothing:
--   BYPASSRLS        reads all tenants' rows (needed for a whole-database dump)
--   pg_read_all_data SELECT on every table and sequence; no INSERT/UPDATE/DELETE
--   no ownership, no CREATE, not a superuser, not a member of nexira_app.
-- Only the backup CronJob gets its password. Restores run as the superuser.

CREATE ROLE nexira_backup LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS
  PASSWORD :'backup_password';
GRANT pg_read_all_data TO nexira_backup;
GRANT CONNECT ON DATABASE :"db_name" TO nexira_backup;
