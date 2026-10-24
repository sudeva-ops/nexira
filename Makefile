SHELL := /bin/bash
COMPOSE := docker compose --env-file .env -f infra/docker-compose.yml
APP_ENV ?= $(shell grep -E '^APP_ENV=' .env 2>/dev/null | cut -d= -f2)

.PHONY: help env up down logs test test-backend test-simulator test-frontend \
        lint lint-backend lint-simulator lint-frontend migrate seed reset-demo tiles

help:
	@echo "up | down | logs | test | lint | migrate | seed | reset-demo | tiles"

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

test-simulator:
	cd simulator && uv run pytest

test-frontend:
	cd frontend && npm run test

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

seed: env
	@echo "seed: not implemented yet (Prompt 4)."

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

# D-24: builds PMTiles into infra/tiles/. Implemented in Prompt 8.
tiles:
	@mkdir -p infra/tiles
	@echo "tiles: not implemented yet (Prompt 8)."
