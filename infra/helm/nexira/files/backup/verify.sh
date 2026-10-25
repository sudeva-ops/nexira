#!/bin/sh
# Checks a NEXIRA database after a restore: the schema version, row-level security
# on every table, and every tenant's audit hash chain (D-20). Exit 1 on any failure.
# Usage: verify.sh <database>. Runs as the superuser (reads every tenant).
set -eu
db="${1:?usage: verify.sh <database>}"

version=$(psql -d "$db" -Atc "SELECT version_num FROM alembic_version")
echo "schema version: $version"

# Every tenant-owned table (one with a tenant_id column) keeps FORCE RLS (D-01).
unforced=$(psql -d "$db" -Atc "SELECT string_agg(c.relname, ', ') FROM pg_class c
  JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped
  WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r' AND NOT c.relforcerowsecurity")
if [ -n "$unforced" ]; then
  echo "FAIL: tenant tables without FORCE ROW LEVEL SECURITY: $unforced" >&2
  exit 1
fi
echo "row-level security: forced on every tenant table"

failed=0
for tenant in $(psql -d "$db" -Atc "SELECT id FROM tenant ORDER BY id"); do
  # One session: set the tenant (as the API does, D-02), then check its chain.
  result=$(psql -d "$db" -At \
    -c "SELECT set_config('app.tenant_id', '$tenant', false)" \
    -c "SELECT count(*), coalesce(audit_verify_chain()::text, 'intact')
          FROM audit_log WHERE tenant_id = '$tenant'" | tail -1)
  rows=${result%%|*}
  chain=${result#*|}
  echo "tenant $tenant: $rows audit rows, chain $chain"
  [ "$chain" = "intact" ] || failed=1
done
if [ "$failed" -ne 0 ]; then
  echo "FAIL: an audit chain is broken (the value is the first bad chain_seq)" >&2
  exit 1
fi
echo "verify ok: $db"
