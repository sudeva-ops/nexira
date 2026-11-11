SHELL := /bin/bash
# ENV_FILE and COMPOSE_EXTRA let the same targets run the public profile (one origin under /auth;
# docs/plan-demo-codespaces.md), e.g. make acceptance ENV_FILE=.env.public \
#   COMPOSE_EXTRA="-f infra/docker-compose.public.yml".
ENV_FILE ?= .env
COMPOSE_EXTRA ?=
COMPOSE := docker compose --env-file $(ENV_FILE) -f infra/docker-compose.yml $(COMPOSE_EXTRA)
APP_ENV ?= $(shell grep -E '^APP_ENV=' $(ENV_FILE) 2>/dev/null | cut -d= -f2)

.PHONY: help env up down logs test test-backend test-simulator test-frontend \
        lint lint-backend lint-simulator lint-frontend migrate seed reset-demo tiles cctv-clips e2e acceptance \
        backup restore-test helm-check

help:
	@echo "up | down | logs | test | lint | e2e | acceptance | migrate | seed | reset-demo | tiles | cctv-clips | backup | restore-test | helm-check"

env:
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")

up: env
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

# --- tests and linters run on the host (uv + npm) ------------------------------
test: test-backend test-simulator test-frontend

test-backend: env
	set -a && . ./$(ENV_FILE) && set +a && cd backend && uv run pytest

test-simulator: env
	set -a && . ./$(ENV_FILE) && set +a && cd simulator && uv run pytest

test-frontend:
	cd frontend && npm run test

# Playwright against the running stack (`make up`, then `make seed` or `make reset-demo`).
e2e: env
	cd frontend && npx playwright install chromium
	set -a && . ./$(ENV_FILE) && set +a && cd frontend && npx playwright test --grep-invert "acceptance"

# Prompt 15: the whole Phase 1 acceptance scenario (decisions.md §7) from a fresh
# demo database; prints the performance numbers (frontend/test-results/performance.json).
# Prompt 22: then the Mass Notification acceptance (requirements-pilot.md §6).
# Prompt 27: then the Journey Management acceptance (requirements-pilot.md §12).
# Prompt 32: then the Air Travel Tracking acceptance (requirements-pilot.md §17).
# Prompt 37: then the Travel & Air agent acceptance (requirements-pilot.md §22).
# Prompt 52: then the Document Expiry acceptance (requirements-pilot.md §37).
# Prompt 58: then the Natural Hazards acceptance (requirements-pilot.md §42).
# Prompt 70: then the Evacuation Management acceptance (requirements-pilot.md §52).
# Prompt 76: and the Fleet & Assets acceptance (requirements-pilot.md §57).
# Prompt 82: and the VIP Protection acceptance (requirements-pilot.md §62).
# Prompt 88: and the Site Twin acceptance (requirements-pilot.md §67).
# Prompt 94: and the Supply Chain acceptance (requirements-pilot.md §72).
# Prompt 98: and the Executive Overview acceptance (requirements-pilot.md §77).
# Prompt 105: and the Predictive Risk acceptance (requirements-pilot.md §82). Playwright runs the
# files in name order.
# Prompt 111: then, last and on its own, the After-Action Review acceptance (requirements-pilot.md
# §87): later specs set INC-<year>-1042 back to ACTIVE, and it needs the whole run's record
# (plan-pilot-aar G-4).
# Prompt 126: then the Incident Replay acceptance (requirements-pilot.md §102), which opens the
# replay from the review the After-Action Review spec left (plan-pilot-rpl §6). It only reads.
acceptance: env reset-demo up
	$(COMPOSE) restart backend worker
	cd frontend && npx playwright install chromium
	set -a && . ./$(ENV_FILE) && set +a && cd frontend && npx playwright test e2e/acceptance.spec.ts \
	  e2e/ntf-acceptance.spec.ts e2e/jrn-acceptance.spec.ts e2e/air-acceptance.spec.ts \
	  e2e/ta-acceptance.spec.ts e2e/wx-acceptance.spec.ts e2e/ast-acceptance.spec.ts \
	  e2e/dx-acceptance.spec.ts e2e/ev-acceptance.spec.ts e2e/flt-acceptance.spec.ts \
	  e2e/hl-acceptance.spec.ts e2e/hz-acceptance.spec.ts e2e/vip-acceptance.spec.ts \
	  e2e/twn-acceptance.spec.ts e2e/sup-acceptance.spec.ts \
	  e2e/exe-acceptance.spec.ts e2e/prd-acceptance.spec.ts
	# The Copilot reads the record the specs above left, before After-Action Review changes it.
	set -a && . ./$(ENV_FILE) && set +a && cd frontend && npx playwright test e2e/cop-acceptance.spec.ts
	set -a && . ./$(ENV_FILE) && set +a && cd frontend && npx playwright test e2e/aar-acceptance.spec.ts
	set -a && . ./$(ENV_FILE) && set +a && cd frontend && npx playwright test e2e/rpl-acceptance.spec.ts
	# Exercise & Training (§92, §93 Q12): on its own, after a second reset.
	$(MAKE) reset-demo
	$(COMPOSE) restart backend worker
	set -a && . ./$(ENV_FILE) && set +a && cd frontend && npx playwright test e2e/exr-acceptance.spec.ts

lint: lint-backend lint-simulator lint-frontend

lint-backend:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy

lint-simulator:
	cd simulator && uv run ruff check . && uv run ruff format --check . && uv run mypy

lint-frontend:
	cd frontend && npm run lint

# --- database --------------------------------------------------------------------
# Runs Alembic as nexira_owner in a one-shot container (D-01).
migrate: env
	$(COMPOSE) run --rm --build migrate

# Loads seed data through the backend service layer (identities now, the rest in Prompt 4).
seed: env
	set -a && . ./$(ENV_FILE) && set +a && cd simulator && uv run python -m nexira_sim.seed

# D-21: drops and recreates the LOCAL/DEMO database volume only, then migrates and
# seeds. Refuses to run for any other APP_ENV. Never deletes audit rows in a live DB.
reset-demo: env
	@if [ "$(APP_ENV)" != "local" ] && [ "$(APP_ENV)" != "demo" ]; then \
	  echo "reset-demo refused: APP_ENV=$(APP_ENV) (only local or demo)"; exit 1; fi
	$(COMPOSE) rm --stop --force postgres
	docker volume rm --force nexira_pgdata
	$(COMPOSE) up -d --wait postgres
	$(MAKE) migrate
	$(MAKE) seed

# D-24: world (z0-6) and Nairobi (z0-15) PMTiles, fonts and sprites into infra/tiles/
# (not committed). Downloads at build time only; the app works offline afterwards.
tiles:
	infra/scripts/build-tiles.sh

# TWN-03: the Site Twin's CCTV loops, from free Pexels stock clips, into frontend/public/cctv/
# (git-ignored; checked against SHA-256; the app never fetches them from the internet).
cctv-clips:
	infra/scripts/build-cctv-clips.sh

# --- backups (Prompt 16, NFR 7; docs/runbooks/backup-restore.md) ----------------
# A pg_dump as nexira_backup into ./backups (git-ignored).
backup: env
	$(COMPOSE) run --rm --build backup

# Back up, restore into a scratch database, verify (RLS, audit chains, row counts), drop it.
restore-test: env
	$(COMPOSE) run --rm --build restore-test

# --- Helm chart (infra/helm/nexira): lint, render and validate against the
# Kubernetes schemas, with pinned images instead of host installs.
HELM_IMAGE := alpine/helm:3.19.0
KUBECONFORM_IMAGE := ghcr.io/yannh/kubeconform:v0.7.0
helm-check:
	for values in pilot openshift; do \
	  docker run --rm -v "$(CURDIR)/infra/helm:/charts" -w /charts $(HELM_IMAGE) lint nexira --strict \
	    -f nexira/ci/$$values-values.yaml || exit 1; \
	  docker run --rm -v "$(CURDIR)/infra/helm:/charts" -w /charts $(HELM_IMAGE) template nexira nexira \
	    -f nexira/ci/$$values-values.yaml > infra/helm/.rendered.yaml || exit 1; \
	  docker run --rm -v "$(CURDIR)/infra/helm:/charts" $(KUBECONFORM_IMAGE) -strict -summary \
	    -kubernetes-version 1.30.0 -skip Route /charts/.rendered.yaml || exit 1; \
	  sh infra/helm/check-render.sh infra/helm/.rendered.yaml $$values || exit 1; \
	done
