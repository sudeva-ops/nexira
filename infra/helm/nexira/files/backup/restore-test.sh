#!/bin/sh
# The restore test (NFR 7, Prompt 16): back up the live database, restore the dump
# into a scratch database, check it, compare every table's row count with the
# source, and drop the scratch database. Runs as the superuser; the dump itself is
# taken as nexira_backup. Usage: restore-test.sh (PGHOST/PGPORT/PGDATABASE,
# PGPASSWORD = superuser password, BACKUP_PASSWORD = nexira_backup's password).
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
source_db="${PGDATABASE:?PGDATABASE is required}"
scratch="${source_db}_restore_test"
super_password="$PGPASSWORD"
dir="${BACKUP_DIR:-/backups}"

PGUSER=nexira_backup PGPASSWORD="${BACKUP_PASSWORD:?BACKUP_PASSWORD is required}" "$here/backup.sh"
dump=$(ls -1t "$dir"/nexira-*.dump | head -1)

export PGUSER="${PGUSER_SUPER:-postgres}" PGPASSWORD="$super_password"
psql -d postgres -qc "DROP DATABASE IF EXISTS \"$scratch\""
trap 'psql -d postgres -qc "DROP DATABASE IF EXISTS \"$scratch\""' EXIT
"$here/restore.sh" "$dump" "$scratch"

counts() {
  psql -d "$1" -Atc "SELECT string_agg(format('%s=%s', c.relname,
      (xpath('/row/n/text()', query_to_xml(format('SELECT count(*) AS n FROM %I', c.relname), false, true, '')))[1]::text),
      ' ' ORDER BY c.relname)
    FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'"
}
security() {
  psql -d "$1" -Atc "SELECT string_agg(format('%s:%s%s', c.relname, c.relrowsecurity, c.relforcerowsecurity), ' '
      ORDER BY c.relname) FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'" \
    -c "SELECT string_agg(format('%s.%s', tablename, policyname), ' ' ORDER BY tablename, policyname) FROM pg_policies" \
    -c "SELECT string_agg(format('%s.%s', tgrelid::regclass, tgname), ' ' ORDER BY tgrelid::regclass::text, tgname) FROM pg_trigger WHERE NOT tgisinternal"
}
for check in counts security; do
  before=$($check "$source_db")
  after=$($check "$scratch")
  if [ "$before" != "$after" ]; then
    echo "FAIL: $check differ between the source and the restored database" >&2
    echo "source:   $before" >&2
    echo "restored: $after" >&2
    exit 1
  fi
done
echo "row counts match: $(counts "$scratch" | wc -w | tr -d ' ') tables"
echo "RLS flags, $(psql -d "$scratch" -Atc 'SELECT count(*) FROM pg_policies') policies and \
$(psql -d "$scratch" -Atc 'SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal') triggers match"
echo "restore test ok: $dump"
