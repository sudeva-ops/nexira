SHELL := /bin/bash
COMPOSE := docker compose --env-file .env -f infra/docker-compose.yml
APP_ENV ?= $(shell grep -E '^APP_ENV=' .env 2>/dev/null | cut -d= -f2)

.PHONY: help env up down logs test test-backend test-simulator test-frontend \
        lint lint-backend lint-simulator lint-frontend migrate seed reset-demo tiles e2e

help:
	@echo "up | down | logs | test | lint | e2e | migrate | seed | reset-demo | tiles"

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
	set -a && . ./.env && set +a && cd frontend && npx playwright test

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
