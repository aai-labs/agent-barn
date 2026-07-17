# System Map

## Read when

Read before introducing a domain, moving ownership between domains, or changing a flow that crosses API, UI, runtime, or deployment boundaries.

## Source map

Agent Farm is a monorepo with four operational areas:

| Area           | Responsibility                                                                                         | Authoritative sources                                                        |
| -------------- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| API            | Product and ingest HTTP contracts, authorization, business orchestration, persistence, runtime control | `../../api/api_app.py`, `../../api/ingest_app.py`, `../../api/domains/`, `../../api/infrastructure/` |
| UI             | Authenticated organization-scoped product interface                                                    | `../../ui/src/app/`, `../../ui/src/features/`, `../../ui/src/shared/`                          |
| Agent runtimes | Execute rendered agent configuration and report activity                                               | `../../api/domains/agents/builders/`, `../../hermes-base/`, `../../openclaw-base/`             |
| Deployment     | Build and deploy databases, LiteLLM, API, UI, and runtime images                                       | `../../helm/`, `../../helmfile.yaml.gotmpl`, `../../.github/workflows/`                        |

Product routes are registered in `../../api/api_app.py` beneath `/api/v1`. Runtime telemetry is a separate FastAPI application registered in `../../api/ingest_app.py` beneath `/ingest/v1` and served on a separate process/port by `../../api/start.sh`. The UI normally reaches product routes through `../../ui/src/shared/api`.

## Domain relationships

```text
Organization
├── Membership ── User/Auth
├── Template lineage ── Template versions ── required Skills
└── Agent
    ├── pinned Template version
    ├── assigned Skills
    ├── Agent Secrets ── Integrations
    ├── Runtime resources ── Kubernetes
    ├── Conversation Messages / Tool Calls ← Ingest
    └── LiteLLM key ── Costs
```

The Agent domain is the central orchestration boundary. It coordinates templates, skills, encrypted credentials, runtime builders, Kubernetes resources, Slack checks, LiteLLM keys, and ingest credentials. This cross-domain orchestration belongs in services rather than routes or repositories.

## Dependency direction

- API requests flow through routes → services → repositories → PostgreSQL delegate.
- Services may also call infrastructure adapters such as Kubernetes, Slack, LiteLLM, OpenRouter, email, and crypto.
- UI routes compose feature components; feature hooks use the shared API client and centralized query-key patterns.
- Agent startup renders a pinned template, combines skills and integration context, builds runtime resources, and applies them through the Kubernetes client.
- Runtime telemetry flows back through Ingest into conversation and tool-call persistence.
- Costs are queried from LiteLLM and joined to agents by LiteLLM key identity; they are not derived from conversation or tool-call records.

## Cross-cutting invariants

- Organization is the tenant-scoping axis for user-visible data.
- API DTOs and database models remain distinct types even when they share a domain `models.py` file.
- Agent runtime configuration is assembled from the agent's pinned template version, explicit skill assignments, eligible integration skills, and encrypted credentials at start time.
- Runtime and platform are separate concepts: Hermes/OpenClaw are runtimes; Slack/Teams are platforms.
- Schema changes are represented by Alembic migrations and exercised against PostgreSQL in API integration tests.
- API and UI deployment versions are independent; `../../AGENTS.md` owns the release-version rules.

## Change impact

A new domain normally requires API registration, DI-compatible layering, tests, UI schema/query integration where exposed, this system map, and the task route in `../INDEX.md`. A change crossing organization, agent, template, or skill boundaries should be checked for tenant isolation and for version/assignment behavior before implementation.
