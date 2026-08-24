<div align="center">

# Agent Barn

**Six AI coworkers in Slack, Microsoft Teams, Telegram, and Discord, running on your infrastructure.**

[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![Discord](https://img.shields.io/badge/discord-join-5865F2)](https://discord.gg/A3vJF5ZKnu)

[Website](https://agentbarn.dev) · [Docs](https://agentbarn.dev/guide) · [Recipes](https://agentbarn.dev/recipes) · [Discord](https://discord.gg/A3vJF5ZKnu)

</div>

---

Agent Barn is an open-source control plane for AI agents. You define agents once,
connect them to the tools your team already uses, and run them in your own
Kubernetes cluster. No seat licence, no second workspace to check.

- **Talk to your tools.** Agents live in Slack, Microsoft Teams, Telegram, and
  Discord. People use them where they already work.
- **Choose a model per agent.** Every agent gets its own virtual key on a LiteLLM
  proxy that runs in your namespace and routes to OpenRouter. Organisations pin a
  default model and an allowlist.
- **See what it costs.** Per-agent token and spend attribution, not one opaque
  monthly number.
- **Multi-tenant from the start.** Organisations, fixed organisation roles, and
  per-agent access roles, with tenant isolation enforced in the data layer.
- **Audit what happened.** Conversation history and a tool-call log per agent,
  plus a domain-event trail behind the platform admin views.
- **Self-host it.** Helm charts, Helmfile, PostgreSQL, your cluster.

Everything runs in your namespace: the control plane, the database, the model
proxy, and one pod per running agent. Outbound traffic goes to OpenRouter through
the LiteLLM proxy you operate, and to whichever tool APIs you connect. Platform
and tool credentials are encrypted at rest in your own PostgreSQL.

## Quickstart

Local evaluation needs Docker, plus [uv](https://github.com/astral-sh/uv) and
[pnpm](https://pnpm.io/) if you want to run services natively.

```bash
git clone https://github.com/aai-labs/agent-farm.git
cd agent-farm

make setup          # installs API + UI dependencies, copies .env.spec to .env
# fill in the required values in .env before continuing

make db-up
make migrate
make up             # db, redis, api, worker, and ui, all hot-reloading
```

The UI comes up on `http://localhost:3000` and the API on
`http://localhost:8000`, with routes under `/api/v1`. Sign in with the
`PLATFORM_ADMIN_CREDENTIALS` you set in `.env`.

Prefer to run services on the host? `make dev-api`, `make dev-ui`, and
`make dev-worker` each watch their own source. See
[CONTRIBUTING.md](CONTRIBUTING.md#development-setup) for the full set.

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
Firecrawl), Redis, the LiteLLM proxy, Firecrawl, the API and its worker, the UI,
and a namespace-scoped Prometheus and Grafana. Ordering, values, and secrets live
in [`helmfile.yaml.gotmpl`](helmfile.yaml.gotmpl); the charts themselves are in
[`helm/`](helm/). Every option in `.env.deploy.spec` is commented.

Background on the runtime and deploy shape:
[`docs/architecture/runtime-and-deployment.md`](docs/architecture/runtime-and-deployment.md)
and [`docs/guidelines/operations.md`](docs/guidelines/operations.md).

## Agents

An agent is a template plus a model, a chat platform, and a set of credentialed
skills. Six templates ship in the box:

| Agent | What it does |
|---|---|
| PR Reviewer | Reviews pull requests for correctness, clarity, and style |
| Documentation Agent | Documents merged pull requests into Confluence, keeps a changelog, and posts a weekly digest to Slack |
| Email Reminder | Monitors a mailbox, flags action-required mail, and posts P1/P2 pings to Slack |
| Jira Task Helper | Turns a plain-language request, in any language, into a structured Jira task |
| Scrum Master | Runs sprint ceremonies, tracks blockers, keeps the team on cadence |
| General Purpose | One flexible assistant for ad-hoc work |

Templates are content, not code: a `settings.yaml` plus Markdown artifacts
(`soul`, `identity`, `user`, `tools`, `agents`, `boot`, `bootstrap`,
`heartbeat`), with anything a template omits inherited from shared defaults. The
seed files live in
[`api/domains/templates/predefined/seeds/`](api/domains/templates/predefined/seeds/)
and bootstrap the platform lineages once; after that, new versions are authored
through the platform admin flow, and organisations fork or override them per
agent. See
[`docs/features/templates-and-skills.md`](docs/features/templates-and-skills.md).

Each template has a guided setup at
[agentbarn.dev/recipes](https://agentbarn.dev/recipes).

## Skills

Skills are what agents can actually do. These ship in the box:

Jira · Confluence · GitHub · Bitbucket · Gmail · Zoho Mail · Google Sheets · Excel · Slack · Pipedrive

Each skill mounts documentation into the agent's workspace and is gated on the
credential its provider needs, so an agent only gets a skill once the matching
credential is attached. Excel is the exception: it works on local files and needs
no credential. Agents also reach a self-hosted Firecrawl for web retrieval.

Building one is a
[contribution we'd welcome](CONTRIBUTING.md#contributing-a-template-or-skill).
Open a Discussion first so we can tell you if one is already in progress.

## Runtimes

Agents run as pods, one per agent, built from a pinned base image:

| Runtime | Platforms | Base image |
|---|---|---|
| Hermes | Slack, Telegram, Discord | [`hermes-base/`](hermes-base/) |
| OpenClaw | Slack, Microsoft Teams, Telegram, Discord | [`openclaw-base/`](openclaw-base/) |

Both are upstream projects. This repository holds the Dockerfiles that pin and
extend them, the telemetry plugins they load, and the builders that turn an agent
record into Kubernetes resources.

## Architecture

```
Slack · Microsoft Teams · Telegram · Discord
                   │
                   ▼
┌───────────────────────────────────────┐      ┌──────────────┐
│  Agent pod — Hermes or OpenClaw       │─────▶│   LiteLLM    │──▶ OpenRouter
│  mounted skills + scoped credentials  │      └──────────────┘
└──────┬─────────────────────────┬──────┘
       │ telemetry               │ tool calls ──▶ Jira · Confluence · GitHub
       ▼                         ▼                Bitbucket · Gmail · Zoho Mail
┌──────────────┐        ┌──────────────┐          Google Sheets · Slack
│ Ingest :8001 │        │  your tools  │          Pipedrive · Firecrawl
└──────┬───────┘        └──────────────┘
       ▼
┌───────────────────────────────────────┐      ┌──────────────┐
│  Control plane — API :8000            │─────▶│  PostgreSQL  │
│  + Dramatiq worker (Redis)            │      └──────────────┘
│  agents · templates · skills · RBAC   │
│  costs · domain events · audit        │─────▶ Kubernetes API ──▶ agent pods
└───────────────────┬───────────────────┘
                    ▲ /api/*
          ┌──────────────────┐
          │     UI :3000     │
          └──────────────────┘
```

## What's in this repo

| Path | What |
|---|---|
| [`api/`](api/) | FastAPI control plane, Dramatiq worker, ingest app, migrations, tests |
| [`ui/`](ui/) | Next.js App Router frontend |
| [`helm/`](helm/) | Helm charts for every deployed service |
| [`k8s/`](k8s/) | Cluster prerequisites the charts don't own |
| [`hermes-base/`](hermes-base/), [`openclaw-base/`](openclaw-base/) | Agent runtime base images |
| [`docs/`](docs/) | Architecture, feature, and decision records |

Two dependencies live outside it: the Hermes and OpenClaw runtimes are upstream
projects, and `aai-cli`, the tool the bundled skills drive, is built from a
separate AAI Labs repository at base-image build time. You can run and deploy the
published base images without it; rebuilding them yourself needs access to that
repository.

Third-party components keep their own licences.

## Where things go

| What | Where |
|---|---|
| Questions, setup help, "is this a bug?" | [Discord `#support`](https://discord.gg/A3vJF5ZKnu) |
| Confirmed bugs | [GitHub Issues](https://github.com/aai-labs/agent-farm/issues) |
| Feature requests and design debate | [GitHub Discussions](https://github.com/aai-labs/agent-farm/discussions) |
| Security vulnerabilities | [Private reporting](https://github.com/aai-labs/agent-farm/security/advisories/new), never a public issue |

A maintainer responds to every `#support` post within 3 business days.

## Contributing

Start with [`good first issue`](https://github.com/aai-labs/agent-farm/labels/good%20first%20issue).
Setup, conventions, and the review process are in [CONTRIBUTING.md](CONTRIBUTING.md).
Repository-wide engineering rules live in [AGENTS.md](AGENTS.md) and
[`docs/INDEX.md`](docs/INDEX.md); domain terminology is in [CONTEXT.md](CONTEXT.md).

Get a PR merged and you get the Contributor role in Discord.

## Licence

Apache 2.0. See [LICENSE](LICENSE).

Built by [AAI Labs](https://aai-labs.com) in Vilnius, Lithuania.
