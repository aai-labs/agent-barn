COMPOSE := docker compose -f compose.yml

.PHONY: \
	dev-api dev-ui migrate rollback makemigrations test-api test-ui lint-ui coverage check-api fix-api test check fix \
	up down restart logs build clean db-up db-down db-logs db-restart

# Non-docker commands

dev-api:
	cd api && uv run python -m fastapi dev main.py --host 0.0.0.0 --port 8000

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
	cd api && uv run python -m pytest tests -v

test-ui:
	cd ui && pnpm test

lint-ui:
	cd ui && pnpm lint

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
