#!/bin/sh
# The restore test (NFR 7, Prompt 16): back up the live database as nexira_backup,
# restore the dump into a scratch database, verify it (RLS, every audit chain, the
# backup manifest), compare row counts and the RLS policies and triggers with the
# source, and drop the scratch database. Runs as the superuser.
# Environment: PGHOST/PGPORT/PGDATABASE, PGPASSWORD = the superuser's password,
# BACKUP_PASSWORD = nexira_backup's password, BACKUP_DIR (/backups).
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
source_db="${PGDATABASE:?PGDATABASE is required}"
case "$source_db" in
  *[!a-z0-9_]*) echo "database name must be lower-case letters, digits and _" >&2; exit 2 ;;
esac
scratch="${source_db}_restore_test"
super_password="$PGPASSWORD"
dir="${BACKUP_DIR:-/backups}"
export PGUSER="${PGUSER_SUPER:-postgres}" PGPASSWORD="$super_password"

counts() {
  psql -X -v ON_ERROR_STOP=1 -At -d "$1" -c "SELECT string_agg(format('%s=%s', c.relname,
      (xpath('/row/n/text()', query_to_xml(format('SELECT count(*) AS n FROM %I', c.relname), false, true, '')))[1]::text),
      ' ' ORDER BY c.relname)
    FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'"
}
security() {
  psql -X -v ON_ERROR_STOP=1 -At -d "$1" \
    -c "SELECT string_agg(format('%s:%s%s', c.relname, c.relrowsecurity, c.relforcerowsecurity), ' '
          ORDER BY c.relname) FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'" \
    -c "SELECT string_agg(format('%s.%s', tablename, policyname), ' ' ORDER BY tablename, policyname) FROM pg_policies" \
    -c "SELECT string_agg(format('%s.%s', tgrelid::regclass, tgname), ' ' ORDER BY tgrelid::regclass::text, tgname)
          FROM pg_trigger WHERE NOT tgisinternal"
}

before=$(counts "$source_db")
PGUSER=nexira_backup PGPASSWORD="${BACKUP_PASSWORD:?BACKUP_PASSWORD is required}" "$here/backup.sh"
after=$(counts "$source_db")
dump=$(ls -1t "$dir"/nexira-*.dump | head -1)

psql -X -v ON_ERROR_STOP=1 -qd postgres -c "DROP DATABASE IF EXISTS \"$scratch\""
trap 'psql -X -qd postgres -c "DROP DATABASE IF EXISTS \"$scratch\""' EXIT
"$here/restore.sh" "$dump" "$scratch"

source_security=$(security "$source_db")
[ "$source_security" = "$(security "$scratch")" ] || {
  echo "FAIL: RLS flags, policies or triggers differ between the source and the restore" >&2; exit 1; }
echo "RLS flags, $(psql -X -At -d "$scratch" -c 'SELECT count(*) FROM pg_policies') policies and \
$(psql -X -At -d "$scratch" -c 'SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal') triggers match the source"

# Row counts are compared only if nothing was written while the dump ran; the
# manifest check above covers the audit log either way.
if [ "$before" = "$after" ]; then
  restored=$(counts "$scratch")
  if [ "$before" != "$restored" ]; then
    echo "FAIL: row counts differ" >&2
    echo "source:   $before" >&2
    echo "restored: $restored" >&2
    exit 1
  fi
  echo "row counts match: $(echo "$restored" | wc -w | tr -d ' ') tables"
else
  echo "WARNING: the source changed during the backup; row counts not compared (stop writers for a strict test)"
fi
echo "restore test ok: $dump"
