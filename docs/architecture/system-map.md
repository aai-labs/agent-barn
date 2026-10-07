# System Map

## Read when

Read before introducing a domain, moving ownership between domains, or changing a flow that crosses API, UI, runtime, or deployment boundaries.

## Source map

Agent Barn is a monorepo with four operational areas:

| Area           | Responsibility                                                                                         | Authoritative sources                                                        |
| -------------- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| API            | Product, telemetry, communications, and Agent Memory HTTP contracts; authorization; orchestration; persistence; runtime control | `../../api/api_app.py`, `../../api/ingest_app.py`, `../../api/communications_app.py`, `../../api/memory_app.py`, `../../api/domains/`, `../../api/infrastructure/` |
| UI             | Authenticated organization-scoped product interface                                                    | `../../ui/src/app/`, `../../ui/src/features/`, `../../ui/src/shared/`                          |
| Agent runtimes | Execute rendered agent configuration and report activity                                               | `../../api/domains/agents/builders/`, `../../hermes-base/`, `../../openclaw-base/`             |
| Deployment     | Build and deploy databases, LiteLLM, API, UI, Hindsight, and runtime images                                       | `../../helm/`, `../../helmfile.yaml.gotmpl`, `../../.github/workflows/`                        |

Product routes are registered in `../../api/api_app.py` beneath `/api/v1`. Runtime telemetry is isolated in `../../api/ingest_app.py` beneath `/ingest/v1`. Provider ingress, outbound provider delivery, and the runtime-neutral delivery protocol are isolated in `../../api/communications_app.py` beneath `/communications/v1`. Agent-authenticated memory requests are isolated in `../../api/memory_app.py` beneath `/memory/v1`. The UI normally reaches only product routes through `../../ui/src/shared/api`.

## Domain relationships

```text
Organization
├── Membership ── User/Auth
├── Template lineage ── Template versions ── required Skills
├── Domain Events ── Outbox Messages ── Event Deliveries
└── Agent
    ├── pinned Template version
    ├── assigned Skills
    ├── Agent Secrets ── Integrations
    ├── Agent Memory opt-in ── Memory Grants
    ├── Communication Connections ── Platform Plugins
    │   └── Communication Deliveries ── Communications Gateway
    ├── Agent Webhooks ── Webhook Invocations
    ├── Runtime resources ── Kubernetes
    ├── Conversation Messages ← Communications Gateway
    ├── Tool Calls ← Ingest
    ├── Resource usage ← Prometheus ← healthz /metrics
    └── LiteLLM key ── Costs
```

The Agent domain owns lifecycle, templates, skills, runtime builders, Kubernetes resources, LiteLLM keys, and runtime credentials. The Communications domain independently owns provider credentials, Platform Plugins, Communication Connections, provider sessions, canonical messages, and durable delivery. The Agent Webhooks domain owns signed machine ingress and durable Webhook Invocations; an Agent Webhook is not a Platform or Communication Connection. Cross-domain orchestration belongs in services rather than routes or repositories.

The Agent Memory domain owns the persisted opt-in and Organization-managed Memory Grants, with atomic audit events. These product APIs are registered in `api_app.py`; the separate memory process enforces runtime credentials and proxies to Hindsight, and opted-in runtimes recall and retain through their pinned Hindsight plugins alongside native memory. See [`Agent Memory`](../features/agent-memory.md) and its [delivery log](../features/agent-memory/CHANGELOG.md).

## Dependency direction

- API requests flow through routes → services → repositories → PostgreSQL delegate.
- Services and Platform Plugins may call infrastructure adapters such as Kubernetes, provider HTTP clients, LiteLLM, OpenRouter, email, and crypto.
- UI routes compose feature components; feature hooks use the shared API client and centralized query-key patterns.
- Agent startup renders a pinned template, combines skills and integration context, builds runtime resources, and applies them through the Kubernetes client.
- Runtime telemetry flows through Ingest into Tool Call persistence.
- Memory requests flow through the memory gateway into the authenticated Hindsight backend, with banks and tags derived from Agent identity and current grants.
- Platform ingress flows through a Connection's shipped Platform Plugin into durable inbound delivery; runtime replies return through the same Connection and plugin.
- Signed Agent Webhook ingress creates a Webhook Invocation and immediately submits a native one-shot Agent Trigger Job. The runtime delivers its result through the selected runtime-owned Connection without creating a Communication Delivery or passing through the Communications Gateway.
- Domain-specific repository operations that produce Domain Events own one explicit SQLModel transaction for business state, the event Outbox Message, and intended Event Deliveries.
- Product analytics consumes selected Domain Events through the `product_analytics.posthog` Event Handler and posts them to PostHog through the PostHog client. Services make no analytics calls. See [`../features/product-analytics.md`](../features/product-analytics.md).
- Costs are queried from LiteLLM and joined to agents by LiteLLM key identity; they are not derived from conversation or tool-call records.
- Agent Resource Usage is read from Prometheus, not stored. Each Agent reports its own container's CPU and memory, and the `resource_usage` domain queries them by `app` and `org_id`; see [`../features/resource-usage.md`](../features/resource-usage.md).

## Cross-cutting invariants

- Organization is the tenant-scoping axis for user-visible data.
- API DTOs and database models remain distinct types even when they share a domain `models.py` file.
- Agent runtime configuration is assembled from the agent's pinned template version, explicit skill assignments, eligible integration skills, and encrypted credentials at start time.
- Runtime and platform are separate concepts: Hermes/OpenClaw execute Agents; Slack/Telegram/Discord are supplied by shipped Platform Plugins and never select a runtime.
- Domain Events are internal, tenant-aware business facts; they are separate from runtime Telemetry Events and are persisted through transport-neutral PostgreSQL outbox tables.
- Schema changes are represented by Alembic migrations and exercised against PostgreSQL in API integration tests.
- API and UI deployment versions are independent; `../../AGENTS.md` owns the release-version rules.

## Change impact

A new domain normally requires API registration, DI-compatible layering, tests, UI schema/query integration where exposed, this system map, and the task route in `../INDEX.md`. Internal event-producing changes require the Domain Events feature guide, a registered event schema, payload safety checks, and PostgreSQL transaction coverage. A change crossing organization, agent, template, or skill boundaries should be checked for tenant isolation and for version/assignment behavior before implementation.
