COMPOSE := docker compose -f compose.yml

.PHONY: \
	dev-api dev-ingest dev-ui dev-worker reconcile migrate rollback makemigrations test-api test-ui lint-ui check-ui coverage check-api check-migrations check-monitoring fix-api test check fix \
	up down restart logs build clean db-up db-down db-logs db-restart redis-up redis-down redis-logs worker-logs \
	cluster-up cluster-down cluster-reset k3d-load-images k3d-load-openclaw k3d-load-hermes

# Non-docker commands

# Agent pods in k3d push telemetry back through the host, so the pod-facing URL
# has to override the in-cluster default (which only resolves when the API runs
# in k8s). Same value as compose.
INGEST_PORT ?= 8001
INGEST_BASE_URL ?= http://host.docker.internal:$(INGEST_PORT)/ingest/v1
# Overridable so a second worktree can run its own stack without port clashes.
API_DEV_PORT ?= 8000

# Runs ingest alongside the main app, mirroring the container entrypoint
# (api/start.sh) so host and Docker behave the same. Without ingest, agents
# start and chat normally but their activity silently never persists — the
# worst failure mode to leave to a second, easily-forgotten command.
# The trap kills both on Ctrl-C; a stray listener on $(INGEST_PORT) otherwise
# breaks the next run confusingly.
dev-api:
	@cd api && \
	trap 'kill 0' EXIT INT TERM; \
	uv run python -m fastapi dev ingest_main.py --host 0.0.0.0 --port $(INGEST_PORT) & \
	INGEST_BASE_URL=$(INGEST_BASE_URL) uv run python -m fastapi dev main.py --host 0.0.0.0 --port $(API_DEV_PORT)

# Ingest on its own — `make dev-api` already starts it; use this to run or
# restart the telemetry sink independently.
# --host 0.0.0.0 is required: the default loopback bind is unreachable from pods.
dev-ingest:
	cd api && uv run python -m fastapi dev ingest_main.py --host 0.0.0.0 --port $(INGEST_PORT)

dev-ui:
	cd ui && pnpm dev

dev-worker:
	cd api && uv run dramatiq api.worker_app --processes 1 --threads 4

# One-shot reconciliation pass; production runs this on a CronJob schedule.
reconcile:
	cd api && uv run python -m api.domains.events.reconciliation

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
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) down
	$(COMPOSE) up -d --build

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

# k3d dev environment — k3s cluster + LiteLLM + litellm-db in Docker.
# Requires: Docker running. No host k3d or helm install needed.
# kubeconfigs are written to ./.k3d/ (host + in-container variants).
# Ports: LiteLLM → 127.0.0.1:7070 | k8s API → 127.0.0.1:16443

cluster-up:
	@bash docker/k3d/k3d-up.sh

cluster-down:
	$(COMPOSE) --profile k3d run --rm k3d-runner k3d cluster delete agentfarm-dev
	$(COMPOSE) --profile k3d stop litellm litellm-db

cluster-reset: cluster-down cluster-up

# Build both agent base images locally and import them into the k3d cluster.
# Requires GH_TOKEN in env (GitHub PAT with repo read access).
# OPENCLAW_IMAGE and HERMES_IMAGE are read from the environment (your .env).

k3d-load-images:
	@bash docker/k3d/k3d-load-images.sh

k3d-load-openclaw:
	@TARGET=openclaw bash docker/k3d/k3d-load-images.sh

k3d-load-hermes:
	@TARGET=hermes bash docker/k3d/k3d-load-images.sh
