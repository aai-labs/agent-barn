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

## Local Kubernetes (k3d) dev environment

Agents run as Kubernetes resources, so working on that path locally needs a
cluster. We use [k3d](https://k3d.io) (k3s in Docker): the cluster runs from a
helper container, so no host `k3d` or `helm` install is needed — only Docker and
`kubectl` (`cluster-up` uses host `kubectl` to seed the namespace/secret and, on
a native Linux docker engine, to add a CoreDNS host alias). It's
[supported in GitHub Actions](https://github.com/AbsaOSS/k3d-action), so the same
setup backs CI (see the `test-k8s` job in `.github/workflows/api.yml`).

### What to add to `.env` first

`make setup` seeds `.env` from `.env.spec`, which covers the app but **not** this
k3d flow. Add these before starting, or the cluster and agent steps fail:

| Variable | Needed by | Notes |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | `cluster-up` | passed to LiteLLM; also used for the model picker |
| `LITELLM_MASTER_KEY` | `cluster-up` | **stable** admin key, e.g. `sk-$(openssl rand -hex 16)` |
| `AGENT_TOKEN_ENCRYPTION_KEY` | creating agents | Fernet key; agent creation fails without it |
| `OPENCLAW_IMAGE`, `HERMES_IMAGE` | `k3d-load-images` | full `name:tag`, tag must equal the matching `*-base/VERSION` |
| `GH_TOKEN` | `k3d-load-images` | PAT with read access to `aai-labs/agent-cli-tools` |
| `API_K8S_KUBECONFIG_PATH` | `make up` only | `/app/.k3d/kubeconfig-internal.yaml` (see step 2) |

`LITELLM_MASTER_KEY` is worth setting once and leaving alone: LiteLLM encrypts the
virtual keys it stores in Postgres with it, so changing it between runs breaks
agents created under the old key.

`cluster-up` also needs every variable the compose file marks as required, even
though it only starts LiteLLM and the k3d runner: Compose interpolates the whole
file before it looks at `--profile`, so a missing one aborts the command with
`error while interpolating ... required variable X is missing a value` and nothing
starts. `make setup` seeds them all from `.env.spec` — the list matters only if
you assembled `.env` by hand or carried one over from an older checkout:

```text
API_PORT   ENVIRONMENT   PLATFORM_ADMIN_CREDENTIALS   SECRET_SIGNING_KEY
UI_APP_URL   POSTGRES_USER   POSTGRES_PASSWORD   POSTGRES_DB   POSTGRES_PORT
```

`PLATFORM_ADMIN_CREDENTIALS` is `email:password`, and the password must pass the
API's own policy — at least 8 characters with an uppercase letter, a lowercase
letter and a digit. A weaker value lets `cluster-up` through but fails API
startup; see Common pitfalls below.

Optional overrides, all with working defaults: `API_LITELLM_BASE_URL` (how the
API in Docker reaches LiteLLM, defaults to the compose service — `.env`'s
`LITELLM_BASE_URL` is host-facing and would resolve to the container itself),
`INGEST_PORT` / `INGEST_BASE_URL`, and `API_DEV_PORT` (lets a second worktree run
its own stack without port clashes).

### 1. Start the cluster

```bash
make cluster-up      # start LiteLLM + a k3d cluster; write kubeconfigs to .k3d/
make cluster-down    # stop the cluster and LiteLLM (nothing is lost)
make cluster-delete  # destroy the cluster
make cluster-reset   # cluster-delete + cluster-up
```

`cluster-down` **stops**, matching `db-down`/`redis-down` — imported base images,
the namespace and any running agents survive, and `cluster-up` brings it back in
seconds. `cluster-delete` throws all of that away, so you'll need to re-run
`make k3d-load-images` afterwards; reach for it when a stopped cluster comes back
unhealthy.

The cluster name and its two host ports default to a single shared environment.
Override them — as environment variables, not in `.env` — when you want a second
cluster alongside the first, e.g. one per worktree. Pass the same values to every
`cluster-*` and `k3d-load-images` command that should act on that cluster:

| Variable | Default | What it names |
| --- | --- | --- |
| `K3D_CLUSTER` | `agentfarm-dev` | the k3d cluster |
| `K3D_API_PORT` | `16443` | host port for the k8s API |
| `LITELLM_PORT` | `7070` | host port for the LiteLLM proxy |
| `LITELLM_CONTAINER_NAME`, `LITELLM_DB_CONTAINER_NAME` | `aai_litellm`, `aai_litellm_db` | the LiteLLM containers |

```bash
K3D_CLUSTER=agentfarm-mytask K3D_API_PORT=16444 LITELLM_PORT=7071 \
  LITELLM_CONTAINER_NAME=aai_litellm_mytask \
  LITELLM_DB_CONTAINER_NAME=aai_litellm_db_mytask \
  make cluster-up
```

Without an override, `cluster-up` **adopts an existing cluster of the default
name** rather than creating a new one — it starts it if stopped and re-applies the
namespace and `litellm` secret into it. That's what you want for one shared
environment and not what you want in a second worktree.

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
make dev-api      # starts the API and the ingest sink together
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

If a base-image build crawls or times out fetching Debian packages, the default
archive CDN has likely handed you a degraded edge (seen at ~30KB/s, stalling the
build for over an hour). Point the build at another full mirror — it must carry
both `/debian` and `/debian-security`:

```bash
APT_MIRROR=mirror.csclub.uwaterloo.ca make k3d-load-images
```

### 4. Create an organization

A fresh database has a platform admin but **no organization**, and agents live
under one — so agent creation fails until an org exists. Create it in the UI on
first login, or via the API:

```bash
curl -X POST http://localhost:8000/api/v1/organizations \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Local Dev"}'
```

Agent routes are org-scoped from there:
`/api/v1/organizations/{organization_id}/agents`.

### 5. Runtime telemetry (conversations and tool calls)

Agents don't store their history in the pod — runtime plugins push events to the
ingest API, and the UI reads what was persisted. If that path is broken, agents
run but their activity stays empty.

Ingest listens on port `8001`, separate from the main API on `8000`. Pods reach
it through the host, using the same `host.docker.internal` hop as LiteLLM:

- **API in Docker** (`make up`) — `api/start.sh` runs ingest inside the
  container, and compose publishes `8001`. Nothing to do.
- **API on the host** (`make dev-api`) — starts ingest alongside the main app,
  the same pairing as the container. `make dev-ingest` runs it on its own.

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

### Common pitfalls

Symptoms you're likely to hit once, with the actual cause.

**`make cluster-up` aborts with `required variable X is missing a value`, nothing
starts.** Compose interpolates the entire file before applying `--profile`, so the
k3d services can't start until every `${VAR:?}` in the file resolves — including
app-only ones. See the variable list under "What to add to `.env` first".

**API exits at startup with `500: Error while initializing startup data`.** Scroll
up in the log for the real error. The usual cause is the password in
`PLATFORM_ADMIN_CREDENTIALS` failing the API's own policy (≥8 characters, upper,
lower, digit) while bootstrapping the platform admin. Older `.env` files carried a
non-compliant default.

**The containerized API can't reach the cluster:
`x509: certificate is valid for 127.0.0.1, ... not host.docker.internal`.**
`kubeconfig-internal.yaml` dials the API server by that hostname and verifies the
certificate, so the name has to be in the cert's SAN list. `cluster-up` passes
`--tls-san=host.docker.internal`, but a cluster **created before that flag existed**
still has the old certificate — `make cluster-delete && make cluster-up` (then
re-run `make k3d-load-images`) reissues it. Host-mode (`make dev-api`) is immune
because it connects to `127.0.0.1`.

**Starting an agent fails with `Invalid kube-config file. No configuration found.`**
The configured kubeconfig path doesn't exist. The message names neither the path
nor the variable, and the check is lazy — the API boots clean and only fails when
something first touches the cluster, so this looks like an agent bug rather than a
config one. Verify the path resolves *inside* the container:

```bash
docker exec aai_api ls -l "$(grep '^API_K8S_KUBECONFIG_PATH=' .env | cut -d= -f2-)"
```

It must be `/app/.k3d/kubeconfig-internal.yaml` — `compose.yml` mounts `./.k3d`
read-only at `/app/.k3d`, and that is the only filename `cluster-up` writes there
for in-container use. An older `.env` pointing at `/app/.k3d/kubeconfig.yaml`
resolves to nothing. A path that is a directory instead surfaces as a raw
`IsADirectoryError`. On the host the equivalent variable is `K8S_KUBECONFIG_PATH`,
pointing at `.k3d/kubeconfig-host.yaml`.

**Agent pod stuck in `ErrImagePull` / `ImagePullBackOff`.** The base image for that
tag isn't in *that* cluster. Pods run `imagePullPolicy=IfNotPresent` against a
private registry, so an image that was never imported cannot be pulled. Compare
what's in the cluster against what the API asks for:

```bash
docker exec k3d-${K3D_CLUSTER:-agentfarm-dev}-server-0 crictl images | grep -E 'openclaw|hermes'
grep -E '^(OPENCLAW|HERMES)_IMAGE=' .env
```

Fix by running `make k3d-load-images` with the same `K3D_CLUSTER` as the cluster.
A related trap: the tag must equal the matching `*-base/VERSION`;
`k3d-load-images` now refuses to run otherwise.

**Warning `FailedToRetrieveImagePullSecret (registry-pull-secret)` repeating on a
pod.** Expected locally and harmless on its own — the local flow imports images
instead of pulling, and nothing seeds that secret. It becomes the real error only
when the image is genuinely absent, in which case you'll also see `ErrImagePull`
above.

**Agent pod `CrashLoopBackOff` with `OOMKilled` / exit code 137.** The Docker VM ran
out of memory, not the pod's own limit — agent pods declare none, so the kernel
picks whichever process spikes, often while the runtime unpacks a plugin. Check
`docker stats --no-stream` and the Docker Desktop memory allocation; a full local
stack plus a k3d cluster plus agents wants noticeably more than 8 GiB.

**Agent runs but never answers, or its conversations and tool calls stay empty.**
Both paths go through the host, so a loopback address in `.env` resolves to the pod
itself. `AGENT_LITELLM_BASE_URL` must be `http://host.docker.internal:<litellm
port>` — it is handed to the pod as `LITELLM_PROXY_TARGET` and used by the in-pod
proxy on `:8090` that the runtime actually talks to. For empty activity, check
ingest is running and reachable (step 5).

**`VAR=x make cluster-up` seems to ignore `VAR`.** Known gap, no error is printed.
The `cluster-*` and `k3d-load-images` scripts `source .env` after they start, which
unconditionally overwrites anything already in the environment that `.env` also
defines. The rule in practice:

- Works on the command line: `K3D_CLUSTER`, `K3D_API_PORT`, `LITELLM_PORT`,
  `LITELLM_CONTAINER_NAME`, `LITELLM_DB_CONTAINER_NAME`, `APT_MIRROR`, `TARGET` —
  none of them appear in `.env`.
- Ignored on the command line: anything `.env` sets, notably `OPENCLAW_IMAGE`,
  `HERMES_IMAGE`, `GH_TOKEN`, `INGEST_PORT`, `AGENT_LITELLM_BASE_URL`. Edit `.env`
  for those.

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
