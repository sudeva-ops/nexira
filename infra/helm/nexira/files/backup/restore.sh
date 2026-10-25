#!/bin/sh
# Restore a backup into a NEW database, then check it (runbook:
# docs/runbooks/backup-restore.md). Runs as the PostgreSQL superuser: a restore
# writes every tenant's rows and recreates objects owned by nexira_owner, which
# no application role may do. It is an operator action, never automated.
#
# Usage: restore.sh <dump file> <new database name>
# Environment: PGHOST, PGPORT, PGUSER (the superuser), PGPASSWORD.
# The cluster must already have the NEXIRA roles (infra/postgres/init.sql).
set -eu

dump="${1:?usage: restore.sh <dump file> <new database name>}"
target="${2:?usage: restore.sh <dump file> <new database name>}"
case "$target" in
  *[!a-z0-9_]*) echo "database name must be lower-case letters, digits and _" >&2; exit 2 ;;
esac

(cd "$(dirname "$dump")" && sha256sum -c "$(basename "$dump").sha256")

exists=$(psql -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname = '$target'")
if [ -n "$exists" ]; then
  echo "database $target already exists: restore into a new name, then switch over" >&2
  exit 2
fi

psql -v ON_ERROR_STOP=1 -d postgres <<SQL
CREATE DATABASE "$target" OWNER nexira_owner;
REVOKE ALL ON DATABASE "$target" FROM PUBLIC;
GRANT CONNECT ON DATABASE "$target" TO nexira_app;
GRANT CONNECT ON DATABASE "$target" TO nexira_backup;
SQL
# Rows are loaded before triggers and policies are created (pg_restore's
# post-data section), so audit_log keeps its stored hashes exactly. The
# extensions are created by the dump, as the superuser (plan G-27).
pg_restore --exit-on-error --no-password --dbname="$target" "$dump"

"$(dirname "$0")/verify.sh" "$target"
