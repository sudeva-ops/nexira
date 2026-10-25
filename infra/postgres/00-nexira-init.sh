#!/bin/sh
# Runs once, as the superuser, when the data volume is empty.
# Passwords come from the environment (D-01), never from a file in the repo.
set -eu
: "${NEXIRA_OWNER_PASSWORD:?NEXIRA_OWNER_PASSWORD is required}"
: "${NEXIRA_API_PASSWORD:?NEXIRA_API_PASSWORD is required}"
: "${NEXIRA_BACKUP_PASSWORD:?NEXIRA_BACKUP_PASSWORD is required}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v owner_password="$NEXIRA_OWNER_PASSWORD" \
  -v api_password="$NEXIRA_API_PASSWORD" \
  -v backup_password="$NEXIRA_BACKUP_PASSWORD" \
  -v db_name="${NEXIRA_DB:-nexira}" \
  -f /nexira/init.sql
