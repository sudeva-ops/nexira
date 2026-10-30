SHELL := /bin/bash
COMPOSE := docker compose --env-file .env -f infra/docker-compose.yml
APP_ENV ?= $(shell grep -E '^APP_ENV=' .env 2>/dev/null | cut -d= -f2)

.PHONY: help env up down logs test test-backend test-simulator test-frontend \
        lint lint-backend lint-simulator lint-frontend migrate seed reset-demo tiles e2e acceptance \
        backup restore-test helm-check

help:
	@echo "up | down | logs | test | lint | e2e | acceptance | migrate | seed | reset-demo | tiles | backup | restore-test | helm-check"

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
	set -a && . ./.env && set +a && cd backend && uv run pytest

test-simulator: env
	set -a && . ./.env && set +a && cd simulator && uv run pytest

test-frontend:
	cd frontend && npm run test

# Playwright against the running stack (`make up`, then `make seed` or `make reset-demo`).
e2e: env
	cd frontend && npx playwright install chromium
	set -a && . ./.env && set +a && cd frontend && npx playwright test --grep-invert "acceptance"

# Prompt 15: the whole Phase 1 acceptance scenario (decisions.md §7) from a fresh
# demo database; prints the performance numbers (frontend/test-results/performance.json).
# Prompt 22: then the Mass Notification acceptance (requirements-pilot.md §6).
# Prompt 27: then the Journey Management acceptance (requirements-pilot.md §12).
# Prompt 32: then the Air Travel Tracking acceptance (requirements-pilot.md §17).
# Prompt 37: then the Travel & Air agent acceptance (requirements-pilot.md §22), last.
acceptance: env reset-demo up
	$(COMPOSE) restart backend worker
	cd frontend && npx playwright install chromium
	set -a && . ./.env && set +a && cd frontend && npx playwright test e2e/acceptance.spec.ts \
	  e2e/ntf-acceptance.spec.ts e2e/jrn-acceptance.spec.ts e2e/air-acceptance.spec.ts \
	  e2e/ta-acceptance.spec.ts e2e/wx-acceptance.spec.ts e2e/ast-acceptance.spec.ts

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
	set -a && . ./.env && set +a && cd simulator && uv run python -m nexira_sim.seed

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
