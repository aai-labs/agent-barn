<div align="center">

<img src=".github/assets/agent-barn-logo.webp" alt="Agent Barn" width="96">

# Agent Barn

**AI coworkers in Slack, Microsoft Teams, Telegram, and Discord, running on your infrastructure.**

[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![Discord](https://img.shields.io/badge/discord-join-5865F2)](https://discord.gg/A3vJF5ZKnu)

[Website](https://agentbarn.dev) · [Docs](https://agentbarn.dev/guide) · [Recipes](https://agentbarn.dev/recipes) · [Discord](https://discord.gg/A3vJF5ZKnu)

</div>

---

Agent Barn is an open-source control plane for AI agents. Define an agent once,
connect it to the tools your team already uses, and run it in your own
Kubernetes cluster. No seat licence, no second workspace to check.

- **Talk to your tools.** Agents live in Slack, Microsoft Teams, Telegram, and Discord.
- **A model per agent.** Each gets its own virtual key on a LiteLLM proxy in your namespace.
- **See what it costs.** Per-agent token and spend attribution, not one opaque monthly number.
- **Multi-tenant from the start.** Organisation roles and per-agent access roles, isolated in the data layer.
- **Audit what happened.** Conversation history, a tool-call log, and a domain-event trail.
- **Self-host it.** Helm charts, Helmfile, PostgreSQL, your cluster.

Everything runs in your namespace: the control plane, the database, the model
proxy, and one pod per running agent. Outbound traffic goes to OpenRouter through
the LiteLLM proxy you operate, and to whichever tool APIs you connect.
Credentials are encrypted at rest in your own PostgreSQL.

## Contents

- [Quick start](#quick-start) — [before you begin](#before-you-begin), then six steps to a running agent
- [What ships in the box](#what-ships-in-the-box) — [agents](#agents), [skills](#skills), [runtimes](#runtimes)
- [Capabilities](#capabilities)
- [Development](#development) — [native](#native-non-docker-development), [k3d](#local-kubernetes-k3d), [migrations](#database-migrations), [tests](#tests-and-checks), [troubleshooting](#troubleshooting)
- [Deploying to Kubernetes](#deploying-to-kubernetes)
- [Repository layout](#repository-layout)
- [Getting help](#getting-help) · [Contributing](#contributing)

## Quick start

Start the full local stack — control plane, database, model proxy, and the
Kubernetes cluster agents run on — and hire your first agent. The step-by-step
version with screenshots is at
[agentbarn.dev/guides/get-started](https://agentbarn.dev/guides/get-started/local-quickstart).

### Before you begin

**Required software**

- **Docker** — everything runs in containers, including the local Kubernetes cluster.
- **`bash`** — `run.sh` and `stop.sh` are shell scripts. On Windows, see [Windows](#windows).
- **`kubectl`** — used to seed the cluster namespace and secret.

Python and Node.js are **not** needed to run the app; they're only for the
native `dev-*` targets, tests, and lint (see [Development](#development)).

**Required credentials**

1. An **[OpenRouter](https://openrouter.ai) API key** — every agent's model calls route through it.
2. A **GitHub PAT** with read access to [`aai-labs/aai-cli`](https://github.com/aai-labs/aai-cli) — the agent base-image build clones that repository.

**Local ports** — these must be free:

| Port    | Service                    |
| ------- | -------------------------- |
| `3000`  | UI                         |
| `5432`  | PostgreSQL                 |
| `7070`  | LiteLLM proxy              |
| `8000`  | API                        |
| `8001`  | Ingest (runtime telemetry) |
| `8002`  | Communications gateway     |
| `16443` | k3d Kubernetes API         |

Every one of these is overridable — see [Multiple clusters](#local-kubernetes-k3d)
if something already has the port.

### 1. Clone the repository

```bash
git clone https://github.com/aai-labs/agent-barn.git
cd agent-barn
```

### 2. Create the local configuration

```bash
cp .env.spec .env
```

Now fill in these values. Every option in `.env.spec` is commented, and
anything not listed here has a working local default:

| Variable                                                             | What to put in it                                                                                                       |
| -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` | anything you like — the database is created on first run                                                                |
| `SECRET_SIGNING_KEY`                                                 | any random string                                                                                                       |
| `PLATFORM_ADMIN_CREDENTIALS`                                         | `email:password` for the admin account created at startup — the password needs 8+ characters, upper, lower, and a digit |
| `ENVIRONMENT`, `UI_APP_URL`, `API_PORT`                              | leave the `.env.spec` defaults                                                                                          |
| `AGENT_TOKEN_ENCRYPTION_KEY`                                         | a Fernet key — generate it below                                                                                        |
| `OPENROUTER_API_KEY`                                                 | your OpenRouter key; passed to LiteLLM and used for the model picker                                                    |
| `LITELLM_MASTER_KEY`                                                 | a **stable** admin key — generate it below                                                                              |
| `OPENCLAW_IMAGE`, `HERMES_IMAGE`                                     | full `name:tag`; each tag must equal the matching `openclaw-base/VERSION` / `hermes-base/VERSION`                       |
| `GH_TOKEN`                                                           | your GitHub PAT from above                                                                                              |

Generate the two keys:

```bash
# AGENT_TOKEN_ENCRYPTION_KEY — encrypts platform credentials at rest
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# LITELLM_MASTER_KEY
echo "sk-$(openssl rand -hex 16)"
```

> [!IMPORTANT]
> `LITELLM_MASTER_KEY` must stay stable. LiteLLM encrypts the virtual keys it
> stores with this value, so changing it later breaks every agent created under
> the old one.

You don't need to touch `API_K8S_KUBECONFIG_PATH` — `run.sh` sets it for you once
the cluster is up.

### 3. Start Agent Barn

```bash
./run.sh
```

This validates `.env`, brings up the k3d cluster and LiteLLM, builds and loads
the agent base images, runs database migrations, then starts `db`, `redis`,
`api`, `worker`, `communications`, and `ui` — all with hot reload — and follows
the logs. `Ctrl-C` detaches without stopping anything; use `./run.sh --detach`
to skip the logs entirely.

If a required `.env` value is missing, `run.sh` fails immediately and lists
exactly which ones, rather than partway through or at agent-start.

> [!NOTE]
> The **first** run builds both agent base images from scratch and takes a
> while. Later runs skip any image tag already present in the cluster.

### 4. Verify the environment

The API reports its own database connectivity:

```bash
curl -s localhost:8000/api/v1/health
# {"status":"ok","db":"connected"}
```

Then check the UI answers and every container is healthy:

```bash
curl -s -o /dev/null -w '%{http_code}\n' localhost:3000   # → 200
docker compose ps                                          # all Up / healthy
```

Finally, confirm the cluster agents will run on is ready and its namespace was
seeded:

```bash
export KUBECONFIG=.k3d/kubeconfig-host.yaml
kubectl get nodes            # one Ready node
kubectl get ns agent-farm    # Active
```

> [!NOTE]
> The namespace is `agent-farm`, not `agent-barn`. Kubernetes namespaces were
> deliberately left unrenamed in the rebrand — moving running workloads would
> mean recreating every agent Deployment and PVC.

### 5. Sign in

Open **`http://localhost:3000`** and log in with the `email:password` you set in
`PLATFORM_ADMIN_CREDENTIALS`.

> [!TIP]
> If the API exited at startup with `500: Error while initializing startup data`,
> that password almost certainly failed the policy check. See
> [Troubleshooting](#troubleshooting).

### 6. Create an organisation, then hire an agent

Agents are organisation-scoped and a fresh database has none, so **create an
organisation first**. Then pick a template (see
[Agents](#agents)), choose a model, attach any credentials its skills need, and
start it. Connecting it to Slack, Teams, Telegram, or Discord is a per-agent
Communication Connection; the UI walks through each platform's setup.

### Stopping and restarting

| Command             | What it does                                                            |
| ------------------- | ----------------------------------------------------------------------- |
| `./run.sh`          | start everything and follow logs                                        |
| `./run.sh --detach` | same, without following logs                                            |
| `./stop.sh`         | stop containers; DB/redis data and the k3d cluster survive              |
| `./stop.sh --clean` | also delete the k3d cluster (images reload next run); volumes untouched |

`make run`, `make stop`, and `make stop-clean` are thin wrappers around the same
scripts. Volumes are never deleted by either script.

## What ships in the box

### Agents

An agent is a template plus a model, one or more communication connections, and
a set of credentialed skills. These templates ship as seeds:

| Agent               | What it does                                                                                          |
| ------------------- | ----------------------------------------------------------------------------------------------------- |
| PR Reviewer         | Reviews pull requests for correctness, clarity, and style                                             |
| Documentation Agent | Documents merged pull requests into Confluence, keeps a changelog, and posts a weekly digest to Slack |
| Email Reminder      | Monitors a mailbox, flags action-required mail, and posts P1/P2 pings to Slack                        |
| Jira Task Helper    | Turns a plain-language request, in any language, into a structured Jira task                          |
| Scrum Master        | Runs sprint ceremonies, tracks blockers, keeps the team on cadence                                    |
| General Purpose     | One flexible assistant for ad-hoc work                                                                |

Templates are content, not code: a `settings.yaml` plus Markdown artifacts
(`soul`, `identity`, `user`, `tools`, `agents`, `boot`, `bootstrap`,
`heartbeat`), with anything a template omits inherited from shared defaults.
The seeds in
[`api/domains/templates/predefined/seeds/`](api/domains/templates/predefined/seeds/)
bootstrap the platform lineages once; after that, new versions are authored
through the platform admin flow, and organisations fork or override them per
agent. Details:
[`docs/features/templates-and-skills.md`](docs/features/templates-and-skills.md).
Each template has a guided setup at
[agentbarn.dev/recipes](https://agentbarn.dev/recipes).

### Skills

Skills are what agents can actually do:

Bitbucket · Confluence · Excel · GitHub · Google Drive · HubSpot · Jira ·
OpenPanel · Pipedrive · PostHog · Zoho Mail

Each mounts documentation into the agent's workspace and is gated on the
credential its provider needs, so an agent only gets a skill once the matching
credential is attached. Skills whose credential lifecycle isn't modelled yet
(Excel, Google Drive, HubSpot, OpenPanel, PostHog) are attachable but not
auto-attached — Excel needs no credential at all, since it works on local files.
Agents also reach a self-hosted Firecrawl for web retrieval.

Building one is a
[contribution we'd welcome](CONTRIBUTING.md#contributing-a-template-or-skill).
Open a Discussion first so we can tell you if one is already in progress.

### Runtimes

Agents run as pods, one per agent, from a pinned base image:

| Runtime  | Base image                         | Notes                                              |
| -------- | ---------------------------------- | -------------------------------------------------- |
| OpenClaw | [`openclaw-base/`](openclaw-base/) | Default runtime; command approval is always `AUTO` |
| Hermes   | [`hermes-base/`](hermes-base/)     | Supports the per-agent command-approval mode       |

Both consume the same runtime-neutral communications protocol, so every platform
works on either runtime. Both are upstream projects; this repository holds the
Dockerfiles that pin and extend them, the telemetry plugins they load, and the
builders that turn an agent record into Kubernetes resources.

## Capabilities

| Area                    | What's there                                                                                                                                                                                                                                 | Docs                                                                                    |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| Agent lifecycle         | Start, stop, monitor; per-agent model within the organisation's default and allowlist; per-agent channel allowlist and DM policy                                                                                                             | [`features/agents.md`](docs/features/agents.md)                                         |
| Communication           | Slack, Microsoft Teams, Telegram, Discord. An agent may own several connections, including more than one on the same platform. Slack apps are created by hand from a generated manifest; Teams connections export an installable app package | [`features/communications/`](docs/features/communications/)                             |
| Templates and skills    | Versioned templates and skills, seeded on startup, forkable per organisation, with per-agent overrides; agents pin the skill version they run                                                                                                | [`features/templates-and-skills.md`](docs/features/templates-and-skills.md)             |
| Activity                | Conversation history and a tool-call audit log per agent, pushed from the runtime to the ingest API                                                                                                                                          | [`features/activity-and-ingest.md`](docs/features/activity-and-ingest.md)               |
| Costs                   | Per-agent and per-organisation token and spend attribution                                                                                                                                                                                   | [`features/costs.md`](docs/features/costs.md)                                           |
| Identity and access     | Sign-up, login, logout, access + refresh tokens in an httpOnly cookie, password change and reset; organisations with fixed permission-backed roles, plus separate per-agent access roles and assignments                                     | [`features/identity-and-organizations.md`](docs/features/identity-and-organizations.md) |
| Platform administration | User and organisation management, platform statistics, and the Event Delivery Monitor                                                                                                                                                        | [`features/platform-administration/`](docs/features/platform-administration/)           |
| Integrations            | Per-agent provider credentials, organisation-scoped shared credentials, Google OAuth for Google Workspace (Gmail, Calendar, Drive, Sheets)                                                                                                   | [`features/integrations.md`](docs/features/integrations.md)                             |
| Domain events           | Transactional outbox, a Dramatiq worker, event handlers, and a security-audit projection                                                                                                                                                     | [`features/domain-events.md`](docs/features/domain-events.md)                           |
| Runtime and deployment  | Kubernetes agent resources, Helm + Helmfile, namespace-scoped Prometheus and Grafana                                                                                                                                                         | [`architecture/runtime-and-deployment.md`](docs/architecture/runtime-and-deployment.md) |

## Development

`./run.sh` is enough for most work. For faster iteration, or to run only part of
the stack, use the native path below. Repository-wide engineering rules are in
[AGENTS.md](AGENTS.md) and [`docs/INDEX.md`](docs/INDEX.md); domain terminology
is in [CONTEXT.md](CONTEXT.md).

Native development, tests, and lint additionally need Python `>=3.14` +
[uv](https://github.com/astral-sh/uv) and Node.js `24` + [pnpm](https://pnpm.io/).

### Native (non-Docker) development

Each command watches its own source. Run the ones you need in separate
terminals, alongside `make db-up` (and `make redis-up` for the worker):

```bash
make setup         # one-time: uv sync + pnpm install, and copies .env.spec to .env
make db-up         # Postgres only
make migrate       # apply migrations
make dev-api       # API on :8000; also starts Ingest :8001 and Communications :8002
make dev-ui        # UI on :3000, hot reload
make redis-up      # Redis, needed by the worker
make dev-worker    # Dramatiq worker, hot reload
make dev-ingest    # Ingest only (normally started by dev-api)
make dev-communications  # Communications only (normally started by dev-api)
make reconcile     # one-shot repair pass for stuck/unpublished deliveries
```

`make db-down` / `make redis-down` stop them; `make db-logs` / `db-restart`
manage Postgres. This path uses host ports `3000`, `8000`, `8001`, and `8002`,
so don't run it alongside `./run.sh`'s containers.

Two gotchas specific to this path:

- **`DB_CONNECTION_URL` must be correct in `.env`.** These targets read it
  directly; the config has no default and doesn't assemble one from the
  `POSTGRES_*` values. `./run.sh` doesn't care, because compose overrides it to
  the in-network `db` hostname.
- **Set `LITELLM_BASE_URL=http://127.0.0.1:7070`.** It's blank in `.env.spec`,
  and unlike the Docker path nothing here fills it in. `create_agent` silently
  skips minting a LiteLLM key when it's empty
  ([`service.py:820`](api/domains/agents/service.py#L820), no error either way),
  so the agent is created and _looks_ fine but can never answer.

Starting agents still needs a k3d cluster with loaded images, even natively.
Bring one up with `bash docker/k3d/k3d-up.sh` and
`bash docker/k3d/k3d-load-images.sh`, then point the host API at it:

```bash
export KUBECONFIG=.k3d/kubeconfig-host.yaml
export K8S_KUBECONFIG_PATH=.k3d/kubeconfig-host.yaml
```

### Local Kubernetes (k3d)

Agents run as Kubernetes resources, so `./run.sh` brings up a cluster
automatically. We use [k3d](https://k3d.io) (k3s in Docker) from a helper
container, so no host `k3d` or `helm` install is needed — only Docker and
`kubectl`. It's [supported in GitHub Actions](https://github.com/AbsaOSS/k3d-action),
so the same setup backs CI (the `test-k8s` job in `.github/workflows/api.yml`).

`./run.sh` drives `docker/k3d/k3d-up.sh` (cluster + LiteLLM) and
`docker/k3d/k3d-load-images.sh` (agent base images). Both are idempotent and
safe to run directly.

> [!IMPORTANT]
> Keep the `OPENCLAW_IMAGE` / `HERMES_IMAGE` tags in sync with
> `openclaw-base/VERSION` and `hermes-base/VERSION`. CI publishes each base image
> under exactly its `VERSION` tag and the API launches pods from these env-var
> refs, so a mismatched tag runs an image that isn't the version the code
> expects. `k3d-load-images.sh` refuses to run otherwise, and skips the build for
> a tag it can already see in the cluster.

<details>
<summary><b>The two kubeconfigs, and how pods reach the host</b></summary>

`./run.sh` writes two kubeconfigs into `.k3d/` (gitignored) — the same cluster,
reached differently depending on where the client runs:

- `.k3d/kubeconfig-host.yaml` — server on `127.0.0.1`, for host tools
  (`kubectl`, `helm`, `make dev-api`).
- `.k3d/kubeconfig-internal.yaml` — server on `host.docker.internal`, for the
  API running **inside** Docker (`run.sh` points `API_K8S_KUBECONFIG_PATH` here
  automatically).

Agent pods inside k3d reach LiteLLM at `http://host.docker.internal:7070` — set
`AGENT_LITELLM_BASE_URL` to that in `.env` if you override the default port. On
Docker Desktop that name resolves inside pods automatically; on a native Linux
docker engine, `k3d-up.sh` adds a CoreDNS entry (via the `coredns-custom` config
map) mapping it to the cluster network gateway. No manual setup on either
platform.

</details>

<details>
<summary><b>Runtime telemetry — where conversations and tool calls come from</b></summary>

Agents don't store their history in the pod. Runtime plugins push events to the
ingest API and the UI reads what was persisted, so a broken path means agents run
but their activity stays empty.

Ingest listens on `8001`, separate from the main API on `8000`, and pods reach it
through the host via `host.docker.internal`, same as LiteLLM.
`INGEST_BASE_URL=http://host.docker.internal:8001/ingest/v1` is the default for
both `run.sh` and `make dev-api`, overriding the in-cluster Service address that
only applies when the API itself runs in k8s. Override `INGEST_BASE_URL` (or
`INGEST_PORT`) for a different address.

To check the hop from inside the cluster:

```bash
kubectl run ingest-check --rm -it --restart=Never --image=curlimages/curl -- \
  curl -sS -o /dev/null -w '%{http_code}\n' \
  http://host.docker.internal:8001/ingest/v1/openapi.json
```

`200` means it works; the event endpoint behind it authenticates each pod with
its own `INGEST_API_KEY`. A connection error means the hop is broken — in native
mode check `make dev-ingest` is running, and on native Linux check the host
firewall allows the k3d bridge network to reach port 8001.

</details>

<details>
<summary><b>Communication connections</b></summary>

Slack, Microsoft Teams, Telegram, and Discord sessions run in the separately
served Communications gateway on port `8002`. Agent pods claim and complete
deliveries through `http://host.docker.internal:8002/communications/v1`, because
the Compose service name isn't resolvable from k3d. `./run.sh` and `make dev-api`
start the gateway automatically. Override `COMMUNICATIONS_PORT` when the host
port is already in use.

</details>

<details>
<summary><b>Multiple clusters (e.g. one per worktree)</b></summary>

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

Without an override this **adopts an existing cluster of the default name**
rather than creating a new one — starting it if stopped and re-applying the
namespace and `litellm` secret. That's what you want for one shared environment,
and not what you want in a second worktree.

</details>

### Windows

The k3d flow needs **`bash`** — `run.sh`/`stop.sh` and the underlying
`docker/k3d/*.sh` scripts are shell scripts. Two supported ways:

- **WSL2 (recommended)** — Docker Desktop already uses the WSL2 backend, so
  `./run.sh` works unchanged, and that's the path CI exercises. Docker Desktop
  publishes container ports to `localhost` inside both Windows and your WSL2
  distro, so no manual port forwarding is needed.
- **`bash` on `PATH`** — e.g. Git Bash or MSYS2; run `./run.sh` from that shell.

Requires Docker Desktop in Linux-container mode (the default).

### Database migrations

Alembic, run from `api/`. The Makefile wraps every command, and `./run.sh`
applies migrations for you before starting the stack.

```bash
make migrate          # apply everything up to head
make makemigrations   # autogenerate a revision (prompts for the message)
make rollback         # downgrade one revision
make merge-heads      # merge divergent heads after a branchy merge
make check-migrations # CI guard: fail unless there is exactly one head
```

### Tests and checks

```bash
make test-api      # unit + integration, minus the k8s client test
                   # (integration needs Docker for Testcontainers)
make test-api-k8s  # the Kubernetes client integration test, on its own
make test-ui       # UI unit tests
make check-api     # ruff lint + format check + ty type-check
make lint-ui       # UI lint
make check-ui      # UI type-check (tsc --noEmit)
make coverage      # API tests with a coverage report
```

Conventions and what CI enforces: [CONTRIBUTING.md](CONTRIBUTING.md#tests) and
[`docs/guidelines/testing.md`](docs/guidelines/testing.md).

### Troubleshooting

Symptoms you're likely to hit once, with the actual cause.

<details>
<summary><b>API exits at startup with <code>500: Error while initializing startup data</code></b></summary>

Scroll up in the log for the real error. The usual cause is the password in
`PLATFORM_ADMIN_CREDENTIALS` failing the API's own policy (≥8 characters, upper,
lower, digit) while bootstrapping the platform admin.

</details>

<details>
<summary><b>Containerized API can't reach the cluster: <code>x509: certificate is valid for 127.0.0.1, ... not host.docker.internal</code></b></summary>

`kubeconfig-internal.yaml` dials the API server by that hostname and verifies the
certificate, so the name has to be in the cert's SAN list. A cluster **created
before this was fixed** may carry the old certificate — `./stop.sh --clean` then
`./run.sh` reissues it. Host mode (`make dev-api`) is immune because it connects
to `127.0.0.1`.

</details>

<details>
<summary><b>Starting an agent fails with <code>Invalid kube-config file. No configuration found.</code></b></summary>

The configured kubeconfig path doesn't resolve to a real file — either
`API_K8S_KUBECONFIG_PATH`/`K8S_KUBECONFIG_PATH` is unset, or it's a relative path
resolved against the wrong working directory. `run.sh` sets
`API_K8S_KUBECONFIG_PATH` for you; in native mode `K8S_KUBECONFIG_PATH` must be
relative to `api/` (the directory `make dev-api` runs from) or absolute. Verify
inside the container:

```bash
docker exec aai_api ls -l "$(grep '^API_K8S_KUBECONFIG_PATH=' .env | cut -d= -f2-)"
```

It must be `/app/.k3d/kubeconfig-internal.yaml` — `compose.yml` mounts `./.k3d`
read-only at `/app/.k3d`.

</details>

<details>
<summary><b>Agent pod stuck in <code>ErrImagePull</code> / <code>ImagePullBackOff</code></b></summary>

The base image for that tag isn't in _that_ cluster. Pods run
`imagePullPolicy=IfNotPresent` against a private registry, so an image that was
never imported cannot be pulled. Compare what's in the cluster against what the
API asks for:

```bash
docker exec k3d-${K3D_CLUSTER:-agentfarm-dev}-server-0 crictl images | grep -E 'openclaw|hermes'
grep -E '^(OPENCLAW|HERMES)_IMAGE=' .env
```

Fix by running `./run.sh` again (it reloads any image missing from the cluster),
or `bash docker/k3d/k3d-load-images.sh` directly with the same `K3D_CLUSTER`.

A second, less obvious cause: an image that _was_ imported can still disappear
later. Imported images are unreferenced whenever no agent is running one, and
kubelet garbage-collects unreferenced images under disk pressure (seen at
`usage=87 highThreshold=85` on a constrained host). With
`imagePullPolicy=IfNotPresent` against a private registry and no pull secret
seeded locally, a GC'd image can't be re-pulled — only reimported.
`docker system df` / `docker stats --no-stream` will show whether disk pressure
is the actual trigger before you re-run the fix above.

</details>

<details>
<summary><b>Warning <code>FailedToRetrieveImagePullSecret (registry-pull-secret)</code> repeating on a pod</b></summary>

Expected locally and harmless on its own — the local flow imports images instead
of pulling, and nothing seeds that secret. It becomes the real error only when
the image is genuinely absent, in which case you'll also see `ErrImagePull`
above.

</details>

<details>
<summary><b>Agent pod <code>CrashLoopBackOff</code> with <code>OOMKilled</code> / exit code 137</b></summary>

The Docker VM ran out of memory, not the pod's own limit — agent pods declare
none, so the kernel picks whichever process spikes, often while the runtime
unpacks a plugin. Check `docker stats --no-stream` and the Docker Desktop memory
allocation; a full local stack plus a k3d cluster plus agents wants noticeably
more than 8 GiB.

</details>

<details>
<summary><b>Agent runs but never answers, or its conversations and tool calls stay empty</b></summary>

Both paths go through the host, so a loopback address in `.env` resolves to the
pod itself. `AGENT_LITELLM_BASE_URL` must be
`http://host.docker.internal:<litellm port>` — it's handed to the pod as
`LITELLM_PROXY_TARGET` and used by the in-pod proxy on `:8090` that the runtime
actually talks to. For empty activity, check ingest is reachable (see **Runtime
telemetry** above).

</details>

<details>
<summary><b>A base-image build crawls or times out fetching Debian packages</b></summary>

The default archive CDN has likely handed you a degraded edge (seen at ~30KB/s,
stalling the build for over an hour). Point the build at another full mirror — it
must carry both `/debian` and `/debian-security`:

```bash
APT_MIRROR=mirror.csclub.uwaterloo.ca bash docker/k3d/k3d-load-images.sh
```

</details>

## Deploying to Kubernetes

Requires a cluster with an ingress controller, a cert-manager `ClusterIssuer`, a
`StorageClass`, and an OpenRouter API key. On your machine: `kubectl`, Helm 3,
[Helmfile](https://helmfile.readthedocs.io/) 0.171+, and the `helm-diff` plugin.

```bash
cp .env.deploy.spec .env.deploy
# fill in registry, image tags, passwords, hosts, and keys

./deploy.sh         # kubectl apply of the deploy RBAC, then helmfile sync
```

Helmfile brings up PostgreSQL (one instance each for the app, LiteLLM, and
Firecrawl), Redis, the LiteLLM proxy, Firecrawl, the API with its worker and
communications gateway, the UI, and a namespace-scoped Prometheus and Grafana.
Ordering, values, and secrets live in
[`helmfile.yaml.gotmpl`](helmfile.yaml.gotmpl); the charts are in
[`helm/`](helm/). Every option in `.env.deploy.spec` is commented.

AAI Labs runs two deploy paths of its own on top of the same charts:
`deploy.yml` ships every `staging`/`main` push to the k3s testing-ground cluster,
and `deploy-public.yml` deploys a `vX.Y.Z` tag to the hosted public Talos
cluster, pushing images pinned to that tag to `registry.agentbarn.dev`. A manual
dispatch of `deploy-public.yml` takes an existing tag, and its `skip_build` input
reuses the images already in the registry for it.

Background:
[`docs/architecture/runtime-and-deployment.md`](docs/architecture/runtime-and-deployment.md)
and [`docs/guidelines/operations.md`](docs/guidelines/operations.md).

## Repository layout

| What                                                                                           | Where                                                                                     |
| ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| [`api/`](api/)                                                                                 | FastAPI control plane, ingest and communications apps, Dramatiq worker, migrations, tests |
| [`ui/`](ui/)                                                                                   | Next.js App Router frontend                                                               |
| [`helm/`](helm/)                                                                               | Helm charts for every deployed service                                                    |
| [`k8s/`](k8s/)                                                                                 | Cluster prerequisites the charts don't own                                                |
| [`hermes-base/`](hermes-base/), [`openclaw-base/`](openclaw-base/)                             | Agent runtime base images                                                                 |
| [`docker/`](docker/)                                                                           | Local k3d cluster and image-loading scripts                                               |
| [`docs/`](docs/)                                                                               | Architecture, feature, and decision records                                               |
| [`compose.yml`](compose.yml), [`run.sh`](run.sh), [`stop.sh`](stop.sh), [`Makefile`](Makefile) | Local development stack                                                                   |
| [`helmfile.yaml.gotmpl`](helmfile.yaml.gotmpl), [`deploy.sh`](deploy.sh)                       | Kubernetes deployment                                                                     |

Two dependencies live outside it: the Hermes and OpenClaw runtimes are upstream
projects, and `aai-cli`, the tool the bundled skills drive, is built from a
separate AAI Labs repository at base-image build time. You can run and deploy the
published base images without it; rebuilding them yourself needs access to that
repository. Third-party components keep their own licences.

## Getting help

| What                                    | Where                                                                                                     |
| --------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Questions, setup help, "is this a bug?" | [Discord `#support`](https://discord.gg/A3vJF5ZKnu)                                                       |
| Confirmed bugs                          | [GitHub Issues](https://github.com/aai-labs/agent-barn/issues)                                            |
| Feature requests and design debate      | [GitHub Discussions](https://github.com/aai-labs/agent-barn/discussions)                                  |
| Security vulnerabilities                | [Private reporting](https://github.com/aai-labs/agent-barn/security/advisories/new), never a public issue |

A maintainer responds to every `#support` post within 3 business days.

## Contributing

Start with [`good first issue`](https://github.com/aai-labs/agent-barn/labels/good%20first%20issue).
Setup, conventions, and the review process are in [CONTRIBUTING.md](CONTRIBUTING.md).
Get a PR merged and you get the Contributor role in Discord.

## Licence

Apache 2.0. See [LICENSE](LICENSE).

Built by [AAI Labs](https://aai-labs.com) in Vilnius, Lithuania.
