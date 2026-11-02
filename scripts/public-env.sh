#!/usr/bin/env bash
# Write .env.public from .env for the public profile (docs/plan-demo-codespaces.md §2): the whole
# stack on one origin, with Keycloak under /auth. Usage: scripts/public-env.sh [origin]
# (default http://localhost:3000, the frontend's local port). Then, for example:
#   make acceptance ENV_FILE=.env.public COMPOSE_EXTRA="-f infra/docker-compose.public.yml"
set -euo pipefail
umask 077  # the file holds the database and Keycloak passwords
origin="${1:-http://localhost:3000}"
origin="${origin%/}"
if ! [[ "$origin" =~ ^https?://[A-Za-z0-9.-]+(:[0-9]+)?$ ]]; then
  echo "public-env: the origin is scheme://host[:port], nothing else: $origin" >&2
  exit 1
fi
cd "$(dirname "$0")/.."
test -f .env || cp .env.example .env
rm -f .env.public  # a new file, so umask 077 applies
grep -vE '^(NEXIRA_PUBLIC_ORIGIN|OIDC_ISSUER|OIDC_JWKS_URL|VITE_OIDC_URL|E2E_KEYCLOAK_URL)=' .env > .env.public
cat >> .env.public <<ENV
# --- the public profile (scripts/public-env.sh) ---
NEXIRA_PUBLIC_ORIGIN=${origin}
OIDC_ISSUER=${origin}/auth/realms/nexira-demo
OIDC_JWKS_URL=${origin}/auth/realms/nexira-demo/protocol/openid-connect/certs
VITE_OIDC_URL=/auth
E2E_KEYCLOAK_URL=${origin}/auth
ENV
if [[ "$origin" != http://localhost* ]] && grep -qE '=local-' .env.public; then
  echo "public-env: warning: local default passwords with a non-local origin; generate new ones" >&2
fi
echo "wrote .env.public for ${origin}"
