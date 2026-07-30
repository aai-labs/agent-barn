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
- Docker (required for Postgres and Redis)

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

With Docker (db + redis + api + worker + ui):

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

Redis + background worker only (needed alongside `make dev-api` to actually
process Domain Events locally; `make up` starts these automatically):

```bash
make redis-up      # start Redis
make dev-worker    # run the Dramatiq worker (non-docker)
make reconcile     # one-shot repair pass for stuck/unpublished deliveries
make redis-down
```

See [docs/features/domain-events.md](./docs/features/domain-events.md) for how Domain Event delivery works.

## Local Kubernetes (k3d) dev environment

Agents run as Kubernetes resources, so working on that path locally needs a
cluster. We use [k3d](https://k3d.io) (k3s in Docker): the cluster runs from a
helper container, so no host `k3d` or `helm` install is needed — only Docker and
`kubectl` (`cluster-up` uses host `kubectl` to seed the namespace/secret and, on
a native Linux docker engine, to add a CoreDNS host alias). It's
[supported in GitHub Actions](https://github.com/AbsaOSS/k3d-action), so the same
setup backs CI (see the `test-k8s` job in `.github/workflows/api.yml`).

### 1. Start the cluster

`cluster-up` requires two values in `.env`:

- `OPENROUTER_API_KEY` — passed to LiteLLM.
- `LITELLM_MASTER_KEY` — a **stable** admin key for LiteLLM (e.g.
  `LITELLM_MASTER_KEY=sk-$(openssl rand -hex 16)`). Set it once and leave it:
  LiteLLM encrypts the virtual keys it stores in Postgres with this value, so
  changing it between runs breaks agents created under the old key.

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
make dev-ingest   # second shell — see "Runtime telemetry" below
```

**API in Docker** (`make up`): add this one line to `.env` (one-time — the path
is always the same), then `make up`:

```dotenv
API_K8S_KUBECONFIG_PATH=/app/.k3d/kubeconfig-internal.yaml
```

Without this line the containerized API can't reach the cluster, so leave it out
if you're not using k3d.

Ports: LiteLLM proxy on `127.0.0.1:7070`, k8s API on `127.0.0.1:16443`, ingest
API on `127.0.0.1:8001`.

Agent pods inside k3d reach LiteLLM at `http://host.docker.internal:7070` — set
`AGENT_LITELLM_BASE_URL` to that in `.env`. On Docker Desktop that name resolves
inside pods automatically; on a native Linux docker engine `cluster-up` adds a
CoreDNS entry (via the `coredns-custom` config map) mapping it to the cluster
network gateway, so it resolves there too — no manual setup on either platform.

### 3. Load the agent base images (only needed to run agents)

`cluster-up` brings up the cluster but does **not** build or import the
OpenClaw/Hermes base images. Do that separately when you actually want to launch
agents (the cluster must already be running):

```bash
make k3d-load-images                   # build + import both
TARGET=openclaw make k3d-load-images   # just OpenClaw
TARGET=hermes   make k3d-load-images   # just Hermes
```

This builds each base image from source, tags it with the corresponding env var,
and imports it into the k3d cluster. Agent pods run with
`imagePullPolicy=IfNotPresent`, so they use the imported image and never hit a
registry. It needs, in `.env`:

- `GH_TOKEN` — a GitHub PAT with **read access to
  [`aai-labs/agent-cli-tools`](https://github.com/aai-labs/agent-cli-tools)**;
  the base-image build clones that repo.
- `OPENCLAW_IMAGE`, `HERMES_IMAGE` — the fully-qualified image name+tag the agent
  pods request.

**Keep the image tags in sync with the `VERSION` files.** The tag in
`OPENCLAW_IMAGE` must match `openclaw-base/VERSION`, and `HERMES_IMAGE` must match
`hermes-base/VERSION` (e.g. if `openclaw-base/VERSION` is `0.3.0`, then
`OPENCLAW_IMAGE` must end in `:0.3.0`). CI publishes each base image under exactly
its `VERSION` tag, and the API launches pods using these env-var refs — so if a
tag doesn't match its `VERSION`, you'll build, import, or pull an image that isn't
the version the code expects.

### 4. Runtime telemetry (conversations and tool calls)

Agents don't store their history in the pod — runtime plugins push events to the
ingest API, and the UI reads what was persisted. If that path is broken, agents
run but their activity stays empty.

Ingest listens on port `8001`, separate from the main API on `8000`. Pods reach
it through the host, using the same `host.docker.internal` hop as LiteLLM:

- **API in Docker** (`make up`) — `api/start.sh` already runs ingest inside the
  container, and compose publishes `8001`. Nothing to do.
- **API on the host** (`make dev-api`) — ingest needs its own process:
  `make dev-ingest`.

Both paths hand pods `INGEST_BASE_URL=http://host.docker.internal:8001/ingest/v1`
by default, overriding the in-cluster Service address that only applies when the
API itself runs in k8s. Override `INGEST_BASE_URL` (or `INGEST_PORT`) if you need
a different address; no `.env` entry is required for the default setup.

Troubleshooting — agents start but show no conversation or tool calls:

```bash
# from inside the cluster: does the ingest API answer?
kubectl run ingest-check --rm -it --restart=Never --image=curlimages/curl -- \
  curl -sS -o /dev/null -w '%{http_code}\n' \
  http://host.docker.internal:8001/ingest/v1/openapi.json
```

`200` means the hop works, and the event endpoint behind it authenticates each
pod with its own `INGEST_API_KEY`. A connection error means the hop is broken:
with the API on the host, check `make dev-ingest` is running; on native Linux
also check the host firewall allows the k3d bridge network to reach port 8001.

### Windows

The k3d flow needs **`bash` and `make`** — the `make cluster-*` and
`make k3d-load-images` targets shell out to `bash docker/k3d/*.sh`, so installing
GNU Make alone (without a Unix shell) isn't enough. Two supported ways:

- **WSL2 (recommended)** — Docker Desktop already uses the WSL2 backend, so
  `make cluster-up` and the whole bash flow work unchanged, and that's the path
  CI exercises. Docker Desktop publishes the container ports to `localhost`
  inside both Windows and your WSL2 distro, so no manual port forwarding is
  needed.
- **`bash` on `PATH`** — e.g. Git Bash or MSYS2 installed alongside `make`; run
  the `make` targets from that shell.

Requires Docker Desktop in Linux-container mode (the default).

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
