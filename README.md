# Agent Farm

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
- Docker (required for Postgres)

## Setup

```bash
cd api && uv sync
cd ../ui && pnpm install
```

Environment: API reads env from repo root `.env`. Optional test env: `.env.spec`.

## First-Time Run

```bash
make db-up
make migrate
```

## Running Locally

```bash
make dev-api    # API on :8000
make dev-ui     # UI on :3000
```

With Docker (db + api + ui):

```bash
make up         # start all
make down       # stop all
make restart    # rebuild and restart
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

## Local Kubernetes (k3d) dev environment

Agents run as Kubernetes resources, so working on that path locally needs a
cluster. We use [k3d](https://k3d.io) (k3s in Docker): it needs only Docker —
no host `k3d`, `kubectl`, or `helm` install — and is
[supported in GitHub Actions](https://github.com/AbsaOSS/k3d-action), so the
same setup backs CI (see the `test-k8s` job in `.github/workflows/api.yml`).

### 1. Start the cluster

`cluster-up` requires `OPENROUTER_API_KEY` in `.env` (and uses
`LITELLM_MASTER_KEY` if set, otherwise generates one).

```bash
make cluster-up      # start LiteLLM + a k3d cluster; write kubeconfigs to .k3d/
make cluster-down    # delete the cluster and stop LiteLLM
make cluster-reset   # cluster-down + cluster-up
```

It writes two kubeconfigs into `.k3d/` (gitignored) — the same cluster, reached
differently depending on where the client runs:

- `.k3d/kubeconfig-host.yaml` — server on `127.0.0.1`, for host tools
  (`kubectl`, `helm`, `make dev-api`).
- `.k3d/kubeconfig-internal.yaml` — server on `host.docker.internal`, for the
  API running **inside** Docker.

### 2. Point the API at the cluster

Pick the block that matches how you run the API.

**API on the host** (`make dev-api`):

```bash
export KUBECONFIG=.k3d/kubeconfig-host.yaml
export K8S_KUBECONFIG_PATH=.k3d/kubeconfig-host.yaml
make dev-api
```

**API in Docker** (`make up`): add this one line to `.env` (one-time — the path
is always the same), then `make up`:

```dotenv
API_K8S_KUBECONFIG_PATH=/app/.k3d/kubeconfig-internal.yaml
```

Without this line the containerized API can't reach the cluster, so leave it out
if you're not using k3d.

Ports: LiteLLM proxy on `127.0.0.1:7070`, k8s API on `127.0.0.1:16443`.

## Database Migrations

```bash
make migrate         # apply latest
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
