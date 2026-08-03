COMPOSE := docker compose -f compose.yml

.PHONY: \
	setup \
	dev-api dev-ui dev-worker reconcile seed-event-deliveries migrate rollback makemigrations test-api test-ui lint-ui check-ui coverage check-api check-migrations check-monitoring fix-api test check fix \
	up down restart logs build clean db-up db-down db-logs db-restart redis-up redis-down redis-logs worker-logs

# One-time project bootstrap: installs deps for api + ui and creates a local
# .env from the tracked template if one doesn't already exist.
setup:
	cd api && uv sync
	cd ui && pnpm install
	@test -f .env || cp .env.spec .env
	@echo "Setup complete. Fill in .env, then run: make db-up && make migrate && make up"

# Non-docker commands

dev-api:
	cd api && uv run python -m fastapi dev main.py --host 0.0.0.0 --port 8000

dev-ui:
	cd ui && pnpm dev

dev-worker:
	cd api && uv run dramatiq api.worker_app --path .. --processes 1 --threads 4 --watch .

# One-shot reconciliation pass; production runs this on a CronJob schedule.
reconcile:
	cd api && uv run python -m api.domains.events.reconciliation

# Local-only: populate the dev database with realistic Event Deliveries for
# manually exercising the Platform Event Delivery Monitor UI. Safe to re-run.
seed-event-deliveries:
	api/.venv/bin/python -m api.scripts.seed_event_delivery_monitor_fixtures --count 200

migrate:
	cd api && uv run python -m alembic upgrade head

rollback:
	cd api && uv run python -m alembic downgrade -1

makemigrations:
	@cd api && read -p "Enter migration message: " message; \
	uv run python -m alembic revision --autogenerate -m "$$message"

test-api:
	cd api && uv run python -m pytest tests --ignore=tests/integration/test_kubernetes_client.py -v

test-api-k8s:
	cd api && uv run python -m pytest tests/integration/test_kubernetes_client.py -v

test-ui:
	cd ui && pnpm test

lint-ui:
	cd ui && pnpm lint

check-ui:
	cd ui && pnpm exec tsc --noEmit

coverage:
	cd api && uv run python -m pytest tests -v --cov=api --cov-report=term-missing --cov-report=xml

check-api:
	cd api && uv run ruff check . && uv run ruff format --check . && uv run ty check .

check-migrations:
	@cd api && heads=$$(uv run python -m alembic heads); \
	count=$$(printf '%s\n' "$$heads" | grep -c .); \
	if [ "$$count" -ne 1 ]; then \
		echo "Expected exactly one alembic head, found $$count:"; \
		printf '%s\n' "$$heads"; \
		exit 1; \
	fi

check-monitoring:
	helm/monitoring/tests/run.sh

fix-api:
	cd api && uv run ruff check --fix && uv run ruff format .

# Docker commands

up:
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) down
	$(COMPOSE) up --build

logs:
	$(COMPOSE) logs -f

build:
	$(COMPOSE) build

clean:
	$(COMPOSE) down -v --remove-orphans

db-up:
	$(COMPOSE) up -d db

db-down:
	$(COMPOSE) stop db

db-logs:
	$(COMPOSE) logs -f db

db-restart:
	$(COMPOSE) restart db

redis-up:
	$(COMPOSE) up -d redis

redis-down:
	$(COMPOSE) stop redis

redis-logs:
	$(COMPOSE) logs -f redis

worker-logs:
	$(COMPOSE) logs -f worker
