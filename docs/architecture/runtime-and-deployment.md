# Runtime and Deployment Architecture

## Read when

Read before changing Hermes/OpenClaw behavior, agent Kubernetes resources, runtime images, telemetry configuration, Helm charts, deployment workflows, or service versions.

## Agent runtime assembly

Starting an agent is an API-orchestrated deployment flow:

1. Load the organization-owned agent and its pinned template version.
2. Render template Markdown with the agent identity.
3. Decrypt Agent Secrets used by tool Integrations; Communication Connection credentials stay in the Communications service.
4. Select Hermes or OpenClaw runtime builders.
5. Combine explicitly assigned skills with eligible built-in provider skills.
6. Append tool pointers, integration policy, and unconditional runtime behaviour policies to rendered Markdown.
7. Generate fresh Ingest and Communications protocol credentials.
8. Build ConfigMap, Secret, PVC, Service, and Deployment resources, including the runtime-neutral communications adapter.
9. Apply resources through the Kubernetes client and mark the Agent running.

Runtime behaviour policies are appended to `AGENTS.md` rather than stored in a template, because both runtimes auto-load `AGENTS.md` into the startup system prompt. They are unconditional and carry no role-specific wording, so custom and forked templates inherit them and the role-scope policy defers to whatever role the agent's own template defines.

A Kubernetes/runtime start failure can place the Agent in `ERROR`; successful start clears the prior lifecycle error. Connection validation and provider-session failures instead update that Communication Connection's observed health and do not change Agent lifecycle.

## Runtime-neutral communications

Both Hermes and OpenClaw consume the same versioned Communications protocol. A sidecar-style runtime adapter claims inbound Communication Deliveries, invokes the runtime's local chat-completions endpoint with a Connection-scoped session key, submits the reply against the source delivery, and completes the delivery. Runtimes never receive provider tokens and contain no Slack, Telegram, or Discord transport configuration.

Runtime is persisted as `agent_type`. Platform is not an Agent field: an Agent may be headless or own any number of Communication Connections independently of whether Hermes or OpenClaw executes it.

## Platform Plugin boundary

Agent Barn ships a code-owned Platform Plugin registry. Each plugin owns typed settings and credential schemas, external validation, credential uniqueness/fingerprinting, inbound normalization/admission, provider-session behavior, outbound sending, and optional processing-feedback hooks. Slack uses supervised Socket Mode, Telegram uses supervised polling, and Discord uses a supervised Gateway session.

Adding a shipped platform adds one plugin and provider client plus focused tests. The generic Connection persistence, CRUD routes, schema-driven UI, durable delivery pipeline, runtime protocol, and Agent builders do not gain platform branches. Plugins are trusted release artifacts, not dynamically installed packages.

Connection credentials are encrypted and never returned by read APIs. Communication Connection CRUD is subordinate to Agent visibility and Permissions. Connection revision changes cause the gateway supervisor to reconcile the provider session without restarting the Agent.

## Mention gating

Shared-room admission is a Platform Plugin concern. Plugin settings define open/allowlist group and direct-message policies plus provider-specific restrictions. Discord supports explicit mention gating and guild/channel/user/role constraints. Slack channel messages require a direct bot mention and expose a schema-driven thread policy: `every_message` requires a mention on every thread reply, while `start_only` admits unmentioned replies only after a matching Connection-scoped thread has persisted Agent state. Slack captures the bot user identity at ingress, ignores duplicate `app_mention` events in favor of `message` events, and applies DM/allowlist checks before mention admission. Durable ownership is supplied to plugins through the Communications admission seam; it is never process-local. Updating these settings increments the Connection revision and reconciles its gateway session; it does not rebuild the runtime.

## Processing feedback

Processing feedback is a best-effort Platform Plugin capability, separate from durable Communication Delivery state. Communications invokes the provider-neutral lifecycle seam after an inbound delivery is accepted, when runtime processing is claimed, and after terminal success or failure is known. Slack reacts with 👀 on acceptance, shows `assistant.threads.setStatus` while the runtime works, and replaces the acknowledgement with ✅ only after outbound provider delivery succeeds or ❌ after terminal failure. Slack status and reaction calls are idempotent and safe to retry; failures are bounded warnings and never change delivery retry or completion state. Plugins without this capability no-op.

## Connection failure recovery

The gateway supervisor isolates provider ingress per enabled Connection and coordinates replicas with database leases. Setup and session failures set Connection health to `ERROR` and retry without altering Agent lifecycle; unsupported supervised ingress can remain `DEGRADED`. Webhook Connections are marked connected after configuration is loaded, while authenticated provider requests remain independently validated.

## Telemetry and costs

Agent runtimes report messages and tool-call state to the separate Ingest API using the per-start ingest key. Ingest authentication currently remains valid after stop because status is not checked and the stored key is not cleared. Costs follow a separate path: the API queries LiteLLM and attributes spend through each agent's LiteLLM key identity.

## Service deployment

`../../helmfile.yaml.gotmpl` orders PostgreSQL releases, LiteLLM, API, UI, and the monitoring stack. The API chart deploys separate product, Ingest, and Communications processes; the Communications Service is reachable internally by runtimes and exposes only the provider-webhook prefix through ingress. API deployment mounts Kubernetes access so the product service can manage Agent resources. An API Helm hook runs Alembic before installation or upgrade.

The API image also runs Domain Event delivery workloads with different commands: a Dramatiq worker deployment processes committed Event Delivery IDs from Redis, and a CronJob runs the one-shot Event Delivery reconciler. Communications uses PostgreSQL-backed leases and durable Communication Deliveries, distinct from Domain Event delivery.

The deploy workflow builds API and UI images under moving environment tags, passes those tags into Helmfile as `API_IMAGE_TAG` and `UI_IMAGE_TAG`, and applies Helmfile. The current convention is `latest` on `main` and `latest-staging` on the `staging` branch. Component change detection compares the current commit with the latest successful deploy run for that branch; failed runs therefore leave their entire source range pending for the next attempt. Manual dispatches and missing or non-ancestor baselines rebuild all components. Manual and bundled release flows also pass explicit API/UI tags; chart metadata is not used as the source of truth for API/UI images.

Every release's namespace and `needs:` entries are templated on a `NAMESPACE` env var (default `agent-farm`), which is how the `staging` branch deploys a fully separate stack into `agent-farm-staging` instead of prod's `agent-farm`. See [`../guidelines/operations.md`](../guidelines/operations.md#staging-environment) for the operator runbook and [`../adr/2026-07-13-staging-environment-namespace-isolation.md`](../adr/2026-07-13-staging-environment-namespace-isolation.md) for why namespace isolation was chosen over GitHub Environments or a second cluster.

## Observability

`../../helm/monitoring/` deploys namespace-scoped Prometheus, Grafana, and Alertmanager charts. The product API exposes platform probes on `:8000`, Ingest exposes telemetry metrics on `:8001`, and Communications exposes HTTP metrics on `:8002`; LiteLLM and Agent health services retain their existing scrape targets. Alert rules route through Alertmanager, and Grafana dashboards are provisioned from chart ConfigMaps.

## Kubernetes client constraint

Kubernetes `stream()` and `portforward()` temporarily monkey-patch `ApiClient.request` while establishing WebSocket connections. They use a dedicated `CoreV1Api` and `ApiClient` so concurrent REST operations cannot hit the patched handler; keep streaming and ordinary CRUD clients isolated.

## Source map

| Concern                         | Source                                                                          |
| ------------------------------- | ------------------------------------------------------------------------------- |
| Runtime orchestration           | `../../api/domains/agents/service.py`                                                 |
| Ingest process and routing      | `../../api/ingest_app.py`, `../../api/ingest_main.py`, `../../api/start.sh`                       |
| Communications process and routing | `../../api/communications_app.py`, `../../api/communications_main.py`, `../../api/domains/communications/` |
| Domain Event delivery workers   | `../../api/worker_app.py`, `../../api/domains/events/worker.py`, `../../api/domains/events/reconciliation.py`, `../../helm/agentbarn-api/templates/event-delivery-worker-deployment.yaml`, `../../helm/agentbarn-api/templates/event-delivery-reconciliation-cronjob.yaml` |
| Shared Kubernetes builders      | `../../api/domains/agents/builders/common.py`                                         |
| Hermes builders                 | `../../api/domains/agents/builders/hermes.py`, `../../hermes-base/`                         |
| OpenClaw builders               | `../../api/domains/agents/builders/openclaw.py`, `../../openclaw-base/`                     |
| Skill and integration artifacts | `../../api/domains/agents/aai_cli_artifacts.py`, `../../api/domains/agents/aai_cli_skills/` |
| Provider clients                | `../../api/infrastructure/slack/`, `../../api/infrastructure/telegram/`, `../../api/infrastructure/discord/` |
| Kubernetes client               | `../../api/infrastructure/kubernetes/`                                                |
| Charts and release ordering     | `../../helm/`, `../../helmfile.yaml.gotmpl`                                                 |
| Deployment workflow             | `../../.github/workflows/deploy.yml`                                                  |
| Monitoring stack                | `../../helm/monitoring/`                                                               |
| API metrics                     | `../../api/core/metrics.py`                                                            |

## Change impact

Runtime changes must be checked against both runtime builders, images/base configuration, Agent lifecycle tests, telemetry, and the versioned Communications protocol. Platform changes belong at the Platform Plugin seam and require plugin, gateway, Connection CRUD/schema, and delivery tests rather than runtime branches. Chart template/value changes require the chart `version` bump according to `../../AGENTS.md`.
