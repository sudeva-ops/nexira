#!/bin/sh
# Nightly backup (NFR 7): one pg_dump of the whole NEXIRA database, custom format,
# a manifest of every tenant's newest audit row, and a SHA-256 file over both. Runs as nexira_backup (infra/postgres/backup-role.sql),
# from the Helm CronJob or `make backup`. Runbook: docs/runbooks/backup-restore.md.
#
# Environment: PGHOST, PGPORT (5432), PGDATABASE, PGUSER (nexira_backup), PGPASSWORD,
# BACKUP_DIR (/backups), BACKUP_KEEP_DAYS (14).
set -eu

: "${PGHOST:?PGHOST is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${PGPASSWORD:?PGPASSWORD is required}"
export PGUSER="${PGUSER:-nexira_backup}"
dir="${BACKUP_DIR:-/backups}"
keep="${BACKUP_KEEP_DAYS:-14}"

name="nexira-$(date -u +%Y%m%dT%H%M%SZ).dump"
mkdir -p "$dir"
# The manifest is read just before the dump. The audit log is append-only (D-20),
# so every row listed here must be in the dump; verify.sh checks that after a
# restore, which catches a dump or restore that lost the newest audit rows.
psql -X -v ON_ERROR_STOP=1 -At -F ' ' --no-password -o "$dir/$name.manifest.partial" -c \
  "SELECT DISTINCT ON (tenant_id) tenant_id, chain_seq, row_hash FROM audit_log
    ORDER BY tenant_id, chain_seq DESC"
# Written under temporary names and renamed at the end, so a failed or
# interrupted dump never looks like a good one.
pg_dump --format=custom --compress=6 --no-password --file="$dir/$name.partial"
mv "$dir/$name.manifest.partial" "$dir/$name.manifest"
mv "$dir/$name.partial" "$dir/$name"
(cd "$dir" && sha256sum "$name" "$name.manifest" > "$name.sha256")

# Keep the last $keep days; never delete the dump just written.
find "$dir" -maxdepth 1 -name 'nexira-*.dump*' -mtime "+$keep" ! -name "$name*" -print -delete
echo "backup ok: $dir/$name ($(du -h "$dir/$name" | cut -f1))"
