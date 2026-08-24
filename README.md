# Agent Barn

Platform for hiring, managing, and running AI agents across supported messaging platforms.

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

- Reach agents through Slack, Telegram, and Discord connections
- Two provider-independent runtimes: Hermes and OpenClaw
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

- Docker (required — everything below runs in containers, including the local
  Kubernetes cluster used for agents)
- `bash` (to run `run.sh`/`stop.sh`; see [Windows](#windows) if you're not on
  macOS/Linux)
- Python `>=3.14` + [uv](https://github.com/astral-sh/uv), Node.js `>=20` +
  [pnpm](https://pnpm.io/) — only needed for the native `dev-*` targets, tests,
  and lint; not required to run the app

## Quick Start

```bash
cp .env.spec .env   # fill in the required values — see the table below
./run.sh            # validates .env, starts everything, follows logs
```

`./run.sh` brings up the k3d cluster + LiteLLM, loads the agent base images
(skipping any already in the cluster), runs database migrations, and starts
db/redis/api/worker/communications/ui in Docker — all with hot reload on source changes. If
any required `.env` value is missing it fails immediately and lists exactly
what to fill in, rather than partway through or at agent-start.

```bash
./run.sh --detach   # same, but don't follow logs
./stop.sh           # stop containers; DB/redis data and the k3d cluster survive
./stop.sh --clean   # also delete the k3d cluster (agent images reload next run);
                     # volumes are never touched
```

`make run`, `make stop`, and `make stop-clean` are thin wrappers around the
same scripts.

Once it's up, log in at `http://localhost:3000` with `PLATFORM_ADMIN_CREDENTIALS`
from `.env`, then create an organization — agents are org-scoped and a fresh
database has none.

### Required `.env` values

| Variable                                                             | Notes                                                                                                                                                          |
| -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` |                                                                                                                                                                |
| `SECRET_SIGNING_KEY`                                                 | any random string                                                                                                                                              |
| `PLATFORM_ADMIN_CREDENTIALS`                                         | `email:password` — password needs 8+ chars, upper, lower, digit                                                                                                |
| `ENVIRONMENT`, `UI_APP_URL`, `API_PORT`                              | defaults in `.env.spec` are fine locally                                                                                                                       |
| `AGENT_TOKEN_ENCRYPTION_KEY`                                         | Fernet key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`                                                        |
| `OPENROUTER_API_KEY`                                                 | passed to LiteLLM; also used for the model picker                                                                                                              |
| `LITELLM_MASTER_KEY`                                                 | **stable** admin key, e.g. `sk-$(openssl rand -hex 16)` — LiteLLM encrypts stored keys with it, so changing it later breaks agents created under the old value |
| `OPENCLAW_IMAGE`, `HERMES_IMAGE`                                     | full `name:tag`; the tag must equal the matching `openclaw-base/VERSION` / `hermes-base/VERSION`                                                               |
| `GH_TOKEN`                                                           | GitHub PAT with read access to [`aai-labs/aai-cli`](https://github.com/aai-labs/aai-cli) — the base-image build clones it                      |

`run.sh` sets `API_K8S_KUBECONFIG_PATH` in `.env` for you once the cluster is up
— no manual kubeconfig wiring needed.

## Native (non-Docker) development

For faster iteration than rebuilding containers, run components directly on
the host instead of through `run.sh`. Each command watches its own source; run
the ones you need in separate terminals alongside `make db-up` (and
`make redis-up` if you need the worker):

```bash
make setup        # one-time: uv sync + pnpm install
make db-up         # Postgres only
make migrate       # apply migrations
make dev-api       # API on :8000; also starts Ingest :8001 and Communications :8002
make dev-ui        # UI on :3000, hot reload
make redis-up      # Redis, needed by the worker
make dev-worker    # Dramatiq worker, hot reload
make dev-communications # Communications only (normally started by dev-api)
make reconcile     # one-shot repair pass for stuck/unpublished deliveries
```

`make db-down` / `make redis-down` stop them; `make db-logs` / `db-restart`
manage Postgres. This path uses the host ports (`3000`, `8000`, `8001`, `8002`), so
don't run it alongside `./run.sh`'s containers at the same time.

Starting agents still needs a running k3d cluster + loaded images even in
native mode — see [Local Kubernetes (k3d) dev environment](#local-kubernetes-k3d-dev-environment)
below; `bash docker/k3d/k3d-up.sh` and `bash docker/k3d/k3d-load-images.sh`
manage the cluster on their own, independent of `run.sh`/`stop.sh`. Point the
host API at it with:

```bash
export KUBECONFIG=.k3d/kubeconfig-host.yaml
export K8S_KUBECONFIG_PATH=.k3d/kubeconfig-host.yaml
```

Also set `LITELLM_BASE_URL=http://127.0.0.1:7070` in `.env` for this path. It's
blank in `.env.spec`, and unlike the Docker path (where compose always
overrides it to the in-network LiteLLM service) nothing here fills it in for
you — `create_agent` silently skips minting a LiteLLM key when it's empty
(`api/domains/agents/service.py:728`, no error either way), so the agent gets
created and *looks* fine but can never actually answer.

See [docs/features/domain-events.md](./docs/features/domain-events.md) for how Domain Event delivery works.

## Local Kubernetes (k3d) dev environment

Agents run as Kubernetes resources, so `./run.sh` needs a cluster and brings
one up automatically. We use [k3d](https://k3d.io) (k3s in Docker): the
cluster runs from a helper container, so no host `k3d` or `helm` install is
needed — only Docker and `kubectl` (used to seed the namespace/secret and, on
a native Linux docker engine, to add a CoreDNS host alias). It's
[supported in GitHub Actions](https://github.com/AbsaOSS/k3d-action), so the same
setup backs CI (see the `test-k8s` job in `.github/workflows/api.yml`).

`./run.sh` drives this via `docker/k3d/k3d-up.sh` (cluster + LiteLLM) and
`docker/k3d/k3d-load-images.sh` (agent base images) — both idempotent and safe
to re-run directly if you need to manage the cluster independent of the app
stack (e.g. the native dev workflow above).

It writes two kubeconfigs into `.k3d/` (gitignored) — the same cluster, reached
differently depending on where the client runs:

- `.k3d/kubeconfig-host.yaml` — server on `127.0.0.1`, for host tools
  (`kubectl`, `helm`, `make dev-api`).
- `.k3d/kubeconfig-internal.yaml` — server on `host.docker.internal`, for the
  API running **inside** Docker (`run.sh` points `API_K8S_KUBECONFIG_PATH` at
  this automatically).

Agent pods inside k3d reach LiteLLM at `http://host.docker.internal:7070` — set
`AGENT_LITELLM_BASE_URL` to that in `.env` if you override the default port. On
Docker Desktop that name resolves inside pods automatically; on a native Linux
docker engine, `k3d-up.sh` adds a CoreDNS entry (via the `coredns-custom`
config map) mapping it to the cluster network gateway, so it resolves there
too — no manual setup on either platform.

**Keep `OPENCLAW_IMAGE`/`HERMES_IMAGE` tags in sync with the `VERSION` files.**
The tag in `OPENCLAW_IMAGE` must match `openclaw-base/VERSION`, and
`HERMES_IMAGE` must match `hermes-base/VERSION` (e.g. if `openclaw-base/VERSION`
is `0.3.0`, then `OPENCLAW_IMAGE` must end in `:0.3.0`). CI publishes each base
image under exactly its `VERSION` tag, and the API launches pods using these
env-var refs — a mismatched tag means running an image that isn't the version
the code expects. `k3d-load-images.sh` refuses to run otherwise, and skips the
build entirely for an image tag it can already see in the cluster.

If a base-image build crawls or times out fetching Debian packages, the default
archive CDN has likely handed you a degraded edge (seen at ~30KB/s, stalling the
build for over an hour). Point the build at another full mirror — it must carry
both `/debian` and `/debian-security`:

```bash
APT_MIRROR=mirror.csclub.uwaterloo.ca bash docker/k3d/k3d-load-images.sh
```

### Multiple clusters (e.g. one per worktree)

The cluster name and its two host ports default to a single shared environment.
Override them as environment variables (not in `.env`) to run a second cluster
alongside the first:

| Variable                                              | Default                         | What it names                   |
| ----------------------------------------------------- | ------------------------------- | ------------------------------- |
| `K3D_CLUSTER`                                         | `agentfarm-dev`                 | the k3d cluster                 |
| `K3D_API_PORT`                                        | `16443`                         | host port for the k8s API       |
| `LITELLM_PORT`                                        | `7070`                          | host port for the LiteLLM proxy |
| `LITELLM_CONTAINER_NAME`, `LITELLM_DB_CONTAINER_NAME` | `aai_litellm`, `aai_litellm_db` | the LiteLLM containers          |

```bash
K3D_CLUSTER=agentfarm-mytask K3D_API_PORT=16444 LITELLM_PORT=7071 \
  LITELLM_CONTAINER_NAME=aai_litellm_mytask \
  LITELLM_DB_CONTAINER_NAME=aai_litellm_db_mytask \
  ./run.sh
```

Without an override, this **adopts an existing cluster of the default name**
rather than creating a new one — it starts it if stopped and re-applies the
namespace and `litellm` secret into it. That's what you want for one shared
environment and not what you want in a second worktree.

### Runtime telemetry (conversations and tool calls)

Agents don't store their history in the pod — runtime plugins push events to the
ingest API, and the UI reads what was persisted. If that path is broken, agents
run but their activity stays empty.

Ingest listens on port `8001`, separate from the main API on `8000`. Pods reach
it through the host via `host.docker.internal`, same as LiteLLM.
`INGEST_BASE_URL=http://host.docker.internal:8001/ingest/v1` is the default for
both `run.sh` and `make dev-api`, overriding the in-cluster Service address
that only applies when the API itself runs in k8s. Override `INGEST_BASE_URL`
(or `INGEST_PORT`) if you need a different address.

Troubleshooting — agents start but show no conversation or tool calls:

```bash
# from inside the cluster: does the ingest API answer?
kubectl run ingest-check --rm -it --restart=Never --image=curlimages/curl -- \
  curl -sS -o /dev/null -w '%{http_code}\n' \
  http://host.docker.internal:8001/ingest/v1/openapi.json
```

`200` means the hop works, and the event endpoint behind it authenticates each
pod with its own `INGEST_API_KEY`. A connection error means the hop is broken:
in native mode, check `make dev-ingest` is running; on native Linux also check
the host firewall allows the k3d bridge network to reach port 8001.

### Communication connections

Slack, Telegram, and Discord sessions run in the separately served
Communications gateway on port `8002`. Agent pods claim and complete deliveries
through `http://host.docker.internal:8002/communications/v1`, because the
Compose service name is not resolvable from k3d. `./run.sh` and `make dev-api`
start the gateway automatically. Override `COMMUNICATIONS_PORT` when the host
port is already in use.

### Common pitfalls

Symptoms you're likely to hit once, with the actual cause.

**API exits at startup with `500: Error while initializing startup data`.** Scroll
up in the log for the real error. The usual cause is the password in
`PLATFORM_ADMIN_CREDENTIALS` failing the API's own policy (≥8 characters, upper,
lower, digit) while bootstrapping the platform admin.

**The containerized API can't reach the cluster:
`x509: certificate is valid for 127.0.0.1, ... not host.docker.internal`.**
`kubeconfig-internal.yaml` dials the API server by that hostname and verifies the
certificate, so the name has to be in the cert's SAN list. A cluster **created
before this was fixed** may carry the old certificate — `./stop.sh --clean`
then `./run.sh` reissues it. Host-mode (`make dev-api`) is immune because it
connects to `127.0.0.1`.

**Starting an agent fails with `Invalid kube-config file. No configuration found.`**
The configured kubeconfig path doesn't resolve to a real file — either
`API_K8S_KUBECONFIG_PATH`/`K8S_KUBECONFIG_PATH` is unset, or it's a relative
path resolved against the wrong working directory. `run.sh` sets
`API_K8S_KUBECONFIG_PATH` for you; in native mode, `K8S_KUBECONFIG_PATH` must
be relative to `api/` (the directory `make dev-api` runs from) or absolute.
Verify inside the container:

```bash
docker exec aai_api ls -l "$(grep '^API_K8S_KUBECONFIG_PATH=' .env | cut -d= -f2-)"
```

It must be `/app/.k3d/kubeconfig-internal.yaml` — `compose.yml` mounts `./.k3d`
read-only at `/app/.k3d`.

**Agent pod stuck in `ErrImagePull` / `ImagePullBackOff`.** The base image for that
tag isn't in _that_ cluster. Pods run `imagePullPolicy=IfNotPresent` against a
private registry, so an image that was never imported cannot be pulled. Compare
what's in the cluster against what the API asks for:

```bash
docker exec k3d-${K3D_CLUSTER:-agentfarm-dev}-server-0 crictl images | grep -E 'openclaw|hermes'
grep -E '^(OPENCLAW|HERMES)_IMAGE=' .env
```

Fix by running `./run.sh` again (it reloads any image missing from the
cluster), or `bash docker/k3d/k3d-load-images.sh` directly with the same
`K3D_CLUSTER` as the cluster.

A second, less obvious cause: an image that *was* imported can still
disappear later. Imported images are unreferenced whenever no agent is
running one, and kubelet garbage-collects unreferenced images under disk
pressure (seen at `usage=87 highThreshold=85` on a constrained host). With
`imagePullPolicy=IfNotPresent` against a private registry and no pull
secret seeded locally, a GC'd image can't be re-pulled — only reimported.
`docker system df` / `docker stats --no-stream` will show whether disk
pressure is the actual trigger before you re-run the fix above.

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
ingest is reachable (see Runtime telemetry above).

### Windows

The k3d flow needs **`bash`** — `run.sh`/`stop.sh` and the underlying
`docker/k3d/*.sh` scripts are shell scripts. Two supported ways:

- **WSL2 (recommended)** — Docker Desktop already uses the WSL2 backend, so
  `./run.sh` works unchanged, and that's the path CI exercises. Docker Desktop
  publishes container ports to `localhost` inside both Windows and your WSL2
  distro, so no manual port forwarding is needed.
- **`bash` on `PATH`** — e.g. Git Bash or MSYS2; run `./run.sh` from that shell.

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
