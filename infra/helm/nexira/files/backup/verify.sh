#!/bin/sh
# Checks a NEXIRA database after a restore (exit 1 on any failure):
# - the schema version;
# - row-level security enabled and forced, with a policy, on every tenant table (D-01);
# - every tenant's audit hash chain (D-20);
# - with a manifest (backup.sh): each tenant still has the newest audit row the
#   backup listed, with the same hash, so no audit rows were lost.
# Usage: verify.sh <database> [manifest]. Runs as the superuser (reads every tenant).
set -eu
db="${1:?usage: verify.sh <database> [manifest]}"
manifest="${2:-}"
q() { psql -X -v ON_ERROR_STOP=1 -At -d "$db" "$@"; }
fail() { echo "FAIL: $1" >&2; exit 1; }

# Plain assignments: a failing psql stops the script (set -e), unlike a for list.
version=$(q -c "SELECT version_num FROM alembic_version")
echo "schema version: $version"

unprotected=$(q -c "SELECT coalesce(string_agg(c.relname, ', ' ORDER BY c.relname), '') FROM pg_class c
  JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped
  WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
    AND (NOT c.relrowsecurity OR NOT c.relforcerowsecurity
         OR NOT EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid))")
[ -z "$unprotected" ] || fail "tenant tables without RLS enabled, forced and a policy: $unprotected"
echo "row-level security: enabled, forced and with a policy on every tenant table"

tenants=$(q -c "SELECT id FROM tenant ORDER BY id")
[ -n "$tenants" ] || fail "no tenants: nothing was restored"
for tenant in $tenants; do
  # One session: set the tenant (as the API does, D-02), then check its chain.
  result=$(q <<SQL
SELECT set_config('app.tenant_id', '$tenant', false) \\g /dev/null
SELECT count(*) || ' ' || coalesce(max(chain_seq), 0) || ' ' || coalesce(audit_verify_chain()::text, 'intact')
  FROM audit_log WHERE tenant_id = '$tenant';
SQL
)
  set -- $result
  echo "tenant $tenant: $1 audit rows, newest seq $2, chain $3"
  [ "$3" = "intact" ] || fail "tenant $tenant: audit chain broken at chain_seq $3"
done

if [ -n "$manifest" ]; then
  checked=0
  while read -r tenant seq hash; do
    case "$tenant$seq$hash" in
      *[!0-9a-f-]*) fail "manifest line is not <uuid> <seq> <sha256 hex>: $tenant $seq $hash" ;;
    esac
    found=$(q -c "SELECT row_hash FROM audit_log WHERE tenant_id = '$tenant' AND chain_seq = $seq")
    [ "$found" = "$hash" ] || fail "tenant $tenant: audit row $seq from the backup manifest is missing or changed"
    checked=$((checked + 1))
  done < "$manifest"
  echo "manifest: the newest audit row of $checked tenant(s) is present and unchanged"
else
  echo "WARNING: no manifest; lost audit rows at the end of a chain cannot be detected"
fi
echo "verify ok: $db"
