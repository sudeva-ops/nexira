-- Grants for nexira_backup in one NEXIRA database (backup-role.sql has the role).
-- Run as the superuser, connected to that database: by init.sql, by the test
-- fixtures for their throwaway databases, or by hand on an existing cluster.
-- Idempotent. Changes need human sign-off (D-29: grants).

DO $$
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO nexira_backup', current_database());
END
$$;
GRANT USAGE ON SCHEMA public TO nexira_backup;
-- What exists now (PostGIS's spatial_ref_sys; every table on an existing cluster) ...
GRANT SELECT ON ALL TABLES IN SCHEMA public TO nexira_backup;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO nexira_backup;
-- ... and every table and sequence nexira_owner creates later (Alembic migrations).
ALTER DEFAULT PRIVILEGES FOR ROLE nexira_owner IN SCHEMA public
  GRANT SELECT ON TABLES TO nexira_backup;
ALTER DEFAULT PRIVILEGES FOR ROLE nexira_owner IN SCHEMA public
  GRANT SELECT ON SEQUENCES TO nexira_backup;
