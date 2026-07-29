COMPOSE := docker compose -f compose.yml

.PHONY: \
	dev-api dev-ingest dev-ui migrate rollback makemigrations test-api test-ui lint-ui check-ui coverage check-api fix-api test check fix \
	up down restart logs build clean db-up db-down db-logs db-restart \
	cluster-up cluster-down cluster-reset k3d-load-images k3d-load-openclaw k3d-load-hermes

# Non-docker commands

# Agent pods in k3d push telemetry back through the host, so the pod-facing URL
# has to override the in-cluster default (which only resolves when the API runs
# in k8s). Same value as compose; run `make dev-ingest` alongside `make dev-api`.
INGEST_PORT ?= 8001
INGEST_BASE_URL ?= http://host.docker.internal:$(INGEST_PORT)/ingest/v1

dev-api:
	cd api && INGEST_BASE_URL=$(INGEST_BASE_URL) uv run python -m fastapi dev main.py --host 0.0.0.0 --port 8000

# Ingest API — the sink agent pods push telemetry to. Under Docker this runs
# inside the api container (api/start.sh); on the host it needs its own process.
# --host 0.0.0.0 is required: the default loopback bind is unreachable from pods.
dev-ingest:
	cd api && uv run python -m fastapi dev ingest_main.py --host 0.0.0.0 --port $(INGEST_PORT)

dev-ui:
	cd ui && pnpm dev

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
