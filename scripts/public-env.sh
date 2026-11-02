#!/usr/bin/env bash
# Write .env.public from .env for the public profile (docs/plan-demo-codespaces.md §2): the whole
# stack on one origin, with Keycloak under /auth. Usage: scripts/public-env.sh [origin]
# (default http://localhost:3000, the frontend's local port). Then, for example:
#   make acceptance ENV_FILE=.env.public COMPOSE_EXTRA="-f infra/docker-compose.public.yml"
set -euo pipefail
origin="${1:-http://localhost:3000}"
origin="${origin%/}"
cd "$(dirname "$0")/.."
test -f .env || cp .env.example .env
grep -vE '^(NEXIRA_PUBLIC_ORIGIN|OIDC_ISSUER|OIDC_JWKS_URL|VITE_OIDC_URL|E2E_KEYCLOAK_URL)=' .env > .env.public
cat >> .env.public <<ENV
# --- the public profile (scripts/public-env.sh) ---
NEXIRA_PUBLIC_ORIGIN=${origin}
OIDC_ISSUER=${origin}/auth/realms/nexira-demo
OIDC_JWKS_URL=${origin}/auth/realms/nexira-demo/protocol/openid-connect/certs
VITE_OIDC_URL=/auth
E2E_KEYCLOAK_URL=${origin}/auth
ENV
echo "wrote .env.public for ${origin}"
