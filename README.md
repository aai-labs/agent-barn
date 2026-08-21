# Agent Barn

Platform for hiring, managing, and running AI agents on Slack and Microsoft Teams.

Monorepo layout:

- `api/` — FastAPI, SQLModel/SQLAlchemy, Alembic, Injector DI, pytest
- `ui/` — Next.js App Router, React, TypeScript, TanStack Query
- `helm/` — Helm chart for Kubernetes deployment
- `k8s/` — Kubernetes manifests and helper scripts
- `hermes-base/` — base config for Hermes agents
- `openclaw-base/` — base config for OpenClaw agents

API is served under `/api/v1`; frontend requests to `/api/*` are proxied to the backend.

## Features

**Agents**
- Hire agents on Slack or Microsoft Teams
- Two runtimes: Hermes (Slack-only, lightweight) and OpenClaw (Slack + Teams)
- Automatic Slack app creation via configuration tokens
- Manual Slack app setup with manifest export
- Start, stop, and monitor agents
- Per-agent channel allowlist and DM policies
- Webhook support for agent events

**Templates**
- Versioned agent templates (soul, identity, user, tools, agents, boot, bootstrap, heartbeat files)
- Pre-defined templates (general purpose, code reviewer, scrum master)
- Template seeding on startup

**Conversations & Tool Calls**
- Conversation history per agent
- Tool call tracking and audit log

**Auth & Users**
- Sign-up, login, logout
- Access + refresh token flow (httpOnly cookie)
- Password change and forgot/reset password
- Super-admin user management (list, delete users)
- Organization management

**Infrastructure**
- Slack config token vault (encrypted, auto-renewed)
- Kubernetes deployment via Helm + helmfile

## Project Structure

```text
.
├── api/
├── ui/
├── helm/
├── k8s/
├── hermes-base/
├── openclaw-base/
├── scripts/
├── compose.yml
├── helmfile.yaml.gotmpl
├── deploy.sh
├── Makefile
├── AGENTS.md
└── CLAUDE.md
```

## Prerequisites

- Python `>=3.14` + [uv](https://github.com/astral-sh/uv)
- Node.js `>=20` + [pnpm](https://pnpm.io/)
- Docker (required for Postgres and Redis; sufficient on its own if you run everything via `make up` instead of the native `dev-*` targets)

## Setup

```bash
make setup
```

Installs API + UI dependencies and creates a local `.env` from `.env.spec` if one doesn't
exist yet. Fill in the required values in `.env` before continuing (API reads env from
repo root `.env`).

## First-Time Run

```bash
make db-up
make migrate
```

## Running Locally

Both paths below hot-reload on source changes. Pick native if you already have
`uv`/`pnpm` set up and want faster iteration; pick Docker if you'd rather not run
anything on the host beyond Docker itself.

Native — each command watches its own source; run the ones you need in separate
terminals alongside `make db-up` (and `make redis-up` if you need the worker):

```bash
make dev-api      # API on :8000, hot reload
make dev-ui       # UI on :3000, hot reload
make dev-worker   # Dramatiq worker, hot reload (needs Redis: make redis-up)
```

Fully dockerized (db + redis + api + worker + ui), source bind-mounted into the
containers so api/worker/ui all hot-reload the same way. `up`/`restart` run in the
foreground — leave the terminal open, `Ctrl+C` (or `make down` from another
terminal) to stop:

```bash
make up         # start all (foreground)
make down       # stop all
make restart    # recreate and restart (foreground)
make logs       # tail all logs
make clean      # stop and remove volumes
```

Database only:

```bash
make db-up
make db-down
make db-logs
make db-restart
```

Redis + background worker only (needed alongside `make dev-api` to actually
process Domain Events locally; `make up` starts these automatically):

```bash
make redis-up      # start Redis
make dev-worker    # run the Dramatiq worker (non-docker)
make reconcile     # one-shot repair pass for stuck/unpublished deliveries
make redis-down
```

See [docs/features/domain-events.md](./docs/features/domain-events.md) for how Domain Event delivery works.

## Database Migrations

```bash
make migrate         # apply latest
make merge-heads     # merge multiple Alembic heads
make rollback        # roll back one
make makemigrations  # create new migration (prompts for message)
```

## Tests

```bash
make test-api        # API tests (excludes k8s integration)
make test-api-k8s    # k8s integration tests
make test-ui         # UI tests (Playwright)
make coverage        # API coverage report
```

UI watch/debug:

```bash
cd ui && pnpm test:watch
cd ui && pnpm test:debug
```

## Lint and Type Checks

```bash
make check-api   # ruff check + format check + ty check
make fix-api     # ruff autofix + format
make lint-ui     # ESLint
make check-ui    # TypeScript type check
```

## Deployment

Deployed to Kubernetes via Helm + helmfile. See `helm/`, `k8s/`, `helmfile.yaml.gotmpl`, and `deploy.sh`.

## Development Conventions

See [AGENTS.md](./AGENTS.md) for detailed implementation standards:

- how to create new API and UI domains
- architecture boundaries (routes → services → repositories)
- query key and API client patterns
- testing requirements and examples
- Helm chart versioning and release process
