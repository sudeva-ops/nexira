#!/bin/sh
# Nightly backup (NFR 7): one pg_dump of the whole NEXIRA database, custom format,
# with a SHA-256 file next to it. Runs as nexira_backup (infra/postgres/backup-role.sql),
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
# Written under a temporary name and renamed at the end, so a failed or
# interrupted dump never looks like a good one.
pg_dump --format=custom --compress=6 --no-password --file="$dir/$name.partial"
mv "$dir/$name.partial" "$dir/$name"
(cd "$dir" && sha256sum "$name" > "$name.sha256")

# Keep the last $keep days; never delete the dump just written.
find "$dir" -maxdepth 1 -name 'nexira-*.dump*' -mtime "+$keep" ! -name "$name*" -print -delete
echo "backup ok: $dir/$name ($(du -h "$dir/$name" | cut -f1))"
