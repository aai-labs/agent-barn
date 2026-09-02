COMPOSE := docker compose -f compose.yml

.PHONY: \
	setup run stop stop-clean \
	restart-ui \
	dev-api dev-ingest dev-communications dev-ui dev-worker reconcile seed-event-deliveries seed-agent-overrides migrate merge-heads rollback makemigrations test-api test-ui lint-ui check-ui coverage check-api check-migrations check-monitoring fix-api test check fix \
	db-up db-down db-logs db-restart redis-up redis-down redis-logs

# One-command local dev: validates .env, brings up k3d + LiteLLM, loads agent
# images (skipping any already in the cluster), migrates, starts the app
# stack in Docker with hot reload, and follows logs. See run.sh for details.
run:
	@./run.sh

# Stops containers; DB/redis data and the k3d cluster survive.
stop:
	@./stop.sh

# Stops containers and deletes the k3d cluster (images will need reloading on
# the next `make run`). Volumes are never touched.
stop-clean:
	@./stop.sh --clean

# Next's Docker bind-mount watcher reliably refreshes changed files but may
# miss a newly created App Router directory. This refreshes its route manifest
# without rebuilding the UI image or restarting the rest of the local stack.
restart-ui:
	$(COMPOSE) restart ui

# One-time project bootstrap: installs deps for api + ui and creates a local
# .env from the tracked template if one doesn't already exist.
setup:
	cd api && uv sync
	cd ui && pnpm install
	@test -f .env || cp .env.spec .env
	@echo "Setup complete. Fill in .env, then run: ./run.sh"

# Non-docker commands

# Agent pods in k3d push telemetry back through the host, so the pod-facing URL
# has to override the in-cluster default (which only resolves when the API runs
# in k8s). Same value as compose.
INGEST_PORT ?= 8001
INGEST_BASE_URL ?= http://host.docker.internal:$(INGEST_PORT)/ingest/v1
COMMUNICATIONS_PORT ?= 8002
COMMUNICATIONS_BASE_URL ?= http://host.docker.internal:$(COMMUNICATIONS_PORT)/communications/v1
# Overridable so a second worktree can run its own stack without port clashes.
API_DEV_PORT ?= 8000

# Runs Ingest and Communications alongside the main app so native development
# has the same service topology as Docker and Helm. The trap kills every child
# on Ctrl-C; stray listeners otherwise break the next run confusingly.
dev-api:
	@cd api && \
	trap 'kill 0' EXIT INT TERM; \
	uv run python -m fastapi dev ingest_main.py --host 0.0.0.0 --port $(INGEST_PORT) & \
	uv run python -m fastapi dev communications_main.py --host 0.0.0.0 --port $(COMMUNICATIONS_PORT) & \
	INGEST_BASE_URL=$(INGEST_BASE_URL) COMMUNICATIONS_BASE_URL=$(COMMUNICATIONS_BASE_URL) uv run python -m fastapi dev main.py --host 0.0.0.0 --port $(API_DEV_PORT)

# Ingest on its own — `make dev-api` already starts it; use this to run or
# restart the telemetry sink independently.
# --host 0.0.0.0 is required: the default loopback bind is unreachable from pods.
dev-ingest:
	cd api && uv run python -m fastapi dev ingest_main.py --host 0.0.0.0 --port $(INGEST_PORT)

# Communications on its own — `make dev-api` already starts it.
dev-communications:
	cd api && uv run python -m fastapi dev communications_main.py --host 0.0.0.0 --port $(COMMUNICATIONS_PORT)

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

# Local-only: create stopped Telegram Agents for manually exercising Agent-owned
# template override authoring. Set SEED_AGENT_ORGANIZATION_ID before invoking.
seed-agent-overrides:
	api/.venv/bin/python -m api.scripts.seed_agent_override_fixtures \
		--organization-id "$${SEED_AGENT_ORGANIZATION_ID:?Set SEED_AGENT_ORGANIZATION_ID}" \
		--count "$${SEED_AGENT_COUNT:-3}"

migrate:
	cd api && uv run python -m alembic upgrade head

merge-heads:
	@cd api && \
	head_output="$$(uv run alembic heads)" && \
	heads="$$(printf '%s\n' "$$head_output" | awk '$$2 == "(head)" { print $$1 }')" && \
	count="$$(printf '%s\n' "$$heads" | awk 'NF { count += 1 } END { print count + 0 }')" && \
	if [ "$$count" -eq 0 ]; then \
		echo "No Alembic heads found."; \
		exit 1; \
	elif [ "$$count" -eq 1 ]; then \
		echo "One Alembic head found ($$heads); nothing to merge."; \
	else \
		echo "Merging $$count Alembic heads: $$heads"; \
		uv run alembic merge -m "merge heads" $$heads; \
	fi

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
#
# The full app stack (db/redis/api/worker/communications/ui + k3d cluster) is run via
# ./run.sh and ./stop.sh at the repo root, not make targets — see README.
# The db/redis-only targets below remain for the native dev-* workflow.

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
