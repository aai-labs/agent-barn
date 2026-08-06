# Runtime and Deployment Architecture

## Read when

Read before changing Hermes/OpenClaw behavior, agent Kubernetes resources, runtime images, telemetry configuration, Helm charts, deployment workflows, or service versions.

## Agent runtime assembly

Starting an agent is an API-orchestrated deployment flow:

1. Load the organization-owned agent and its pinned template version.
2. Render template Markdown with the agent identity.
3. Decrypt platform and provider credentials.
4. Select runtime-specific configuration and deployment builders.
5. Combine explicitly assigned skills with eligible built-in provider skills.
6. Append tool pointers and integration policy to rendered Markdown.
7. Generate a fresh ingest key and runtime environment.
8. Build ConfigMap, Secret, PVC, Service, and Deployment resources.
9. Apply resources through the Kubernetes client and mark the agent running.

A failed Slack or Telegram credential check or Kubernetes start can place the agent in `ERROR`; successful start clears the prior error.

## Runtime/platform matrix

| Runtime  | Slack | Teams | Telegram | Runtime configuration                        |
| -------- | ----: | ----: | -------: | -------------------------------------------- |
| Hermes   |   Yes |    No |      Yes | Hermes config and Hermes deployment builders |
| OpenClaw |   Yes |   Yes |      Yes | OpenClaw overlay and deployment builders     |

Runtime is persisted as `agent_type`; platform is persisted separately. Both runtimes receive rendered template files, skills, integrations, model/LiteLLM settings, and ingest credentials, but their filesystem and configuration shapes differ.

## Mention gating

In a shared channel or group an agent responds only to messages that explicitly mention it. Every agent owns its own bot identity and therefore receives every message in rooms it belongs to, so mention gating is the only thing that keeps an untagged agent from acting on a message addressed to another agent. Gating requires a fresh mention per message: participating earlier in a thread does not entitle an agent to later messages. Direct messages are exempt.

Builders set this per runtime and platform:

| Runtime  | Platform | Generated configuration                                                                       |
| -------- | -------- | --------------------------------------------------------------------------------------------- |
| Hermes   | Slack    | `slack.require_mention` and `slack.strict_mention`                                              |
| Hermes   | Telegram | `telegram.require_mention` and `telegram.exclusive_bot_mentions`                                |
| OpenClaw | Slack    | `channels.slack.requireMention`, `channels.slack.thread.requireExplicitMention`, and per-channel `requireMention` |
| OpenClaw | Telegram | per-group `channels.telegram.groups.<chat_id>.requireMention`                                   |

Two residual gaps are runtime limitations rather than configuration choices. Hermes Telegram treats a direct reply to the agent's own message as a trigger and exposes no switch to disable it; OpenClaw Telegram behaves the same way. Both remain addressed to a single agent, so neither reopens the cross-agent case. OpenClaw Telegram also emits no `groups` map when the group policy is open, leaving gating to the runtime default.

Runtime configuration is generated at agent start, so a running agent keeps the gating it was started with until it is stopped and started again.

## Telemetry and costs

Agent runtimes report messages and tool-call state to the separate Ingest API using the per-start ingest key. Ingest authentication currently remains valid after stop because status is not checked and the stored key is not cleared. Costs follow a separate path: the API queries LiteLLM and attributes spend through each agent's LiteLLM key identity.

## Service deployment

`../../helmfile.yaml.gotmpl` orders PostgreSQL releases, LiteLLM, API, UI, and the monitoring stack. API deployment mounts Kubernetes access so the service can manage agent resources. An API Helm hook runs Alembic before installation or upgrade, and health probes use `/api/v1/health`.

The API image also runs Domain Event delivery workloads with different commands: a Dramatiq worker deployment processes committed Event Delivery IDs from Redis, and a CronJob runs the one-shot Event Delivery reconciler. Product and Ingest API health probes remain PostgreSQL-only; worker readiness checks Redis connectivity through the delivery transport adapter.

The deploy workflow builds API and UI images under moving environment tags, passes those tags into Helmfile as `API_IMAGE_TAG` and `UI_IMAGE_TAG`, and applies Helmfile. The current convention is `latest` on `main` and `latest-staging` on the `staging` branch. Manual and bundled release flows also pass explicit API/UI tags; chart metadata is not used as the source of truth for API/UI images.

Every release's namespace and `needs:` entries are templated on a `NAMESPACE` env var (default `agent-farm`), which is how the `staging` branch deploys a fully separate stack into `agent-farm-staging` instead of prod's `agent-farm`. See [`../guidelines/operations.md`](../guidelines/operations.md#staging-environment) for the operator runbook and [`../adr/2026-07-13-staging-environment-namespace-isolation.md`](../adr/2026-07-13-staging-environment-namespace-isolation.md) for why namespace isolation was chosen over GitHub Environments or a second cluster.

## Observability

`../../helm/monitoring/` deploys plain namespace-scoped Prometheus, Grafana, and Alertmanager charts into the release namespace — no operator, no CRDs, and no cluster-scoped RBAC, because the shared cluster only grants this project a namespace (the chart renders no RBAC at all: Prometheus and kube-state-metrics run under the tenant deploy ServiceAccount `<namespace>-user`, which already holds namespaced read; Grafana — the only ingress-exposed pod — runs with no API token mounted). Scrape topology: the API exposes `/metrics` on both processes (main `:8000` with probe gauges for database, agents-in-ERROR, and the OpenRouter key's remaining credit limit (`GET /key` with the inference key; `+Inf` when the key has no limit); ingest `:8001` with the tool-call counter), LiteLLM exposes `/metrics` on `:4000` via its `prometheus` callback, and every agent's healthz server serves `/metrics` on `:8081`, discovered through an own-namespace scrape config selecting the stable `agentfarm.io/component: agent` Service label; the Service's `app`/`agent-name`/`org-name` labels are relabeled onto every scraped series so an agent keeps one identity across all its pod generations. Alerting is declarative: alert rules in the chart values → Alertmanager → Slack `#alerts` webhook (injected from `SLACK_ALERTS_WEBHOOK_URL` into a Secret referenced via `slack_api_url_file`, never committed). Grafana is dashboards-only, provisioned from ConfigMaps in the chart and exposed via traefik ingress at `GRAFANA_HOST`.

## Kubernetes client constraint

Kubernetes `stream()` and `portforward()` temporarily monkey-patch `ApiClient.request` while establishing WebSocket connections. They use a dedicated `CoreV1Api` and `ApiClient` so concurrent REST operations cannot hit the patched handler; keep streaming and ordinary CRUD clients isolated.

## Source map

| Concern                         | Source                                                                          |
| ------------------------------- | ------------------------------------------------------------------------------- |
| Runtime orchestration           | `../../api/domains/agents/service.py`                                                 |
| Ingest process and routing      | `../../api/ingest_app.py`, `../../api/ingest_main.py`, `../../api/start.sh`                       |
| Domain Event delivery workers   | `../../api/worker_app.py`, `../../api/domains/events/worker.py`, `../../api/domains/events/reconciliation.py`, `../../helm/agentfarm-api/templates/event-delivery-worker-deployment.yaml`, `../../helm/agentfarm-api/templates/event-delivery-reconciliation-cronjob.yaml` |
| Shared Kubernetes builders      | `../../api/domains/agents/builders/common.py`                                         |
| Hermes builders                 | `../../api/domains/agents/builders/hermes.py`, `../../hermes-base/`                         |
| OpenClaw builders               | `../../api/domains/agents/builders/openclaw.py`, `../../openclaw-base/`                     |
| Skill and integration artifacts | `../../api/domains/agents/aai_cli_artifacts.py`, `../../api/domains/agents/aai_cli_skills/` |
| Telegram client                 | `../../api/infrastructure/telegram/`                                                  |
| Kubernetes client               | `../../api/infrastructure/kubernetes/`                                                |
| Charts and release ordering     | `../../helm/`, `../../helmfile.yaml.gotmpl`                                                 |
| Deployment workflow             | `../../.github/workflows/deploy.yml`                                                  |
| Monitoring stack                | `../../helm/monitoring/`                                                               |
| API metrics                     | `../../api/core/metrics.py`                                                            |

## Change impact

Runtime changes must be checked against both platforms, builders, images/base configuration, agent lifecycle tests, telemetry, and persisted configuration contracts. For staging/main GitHub deploys, service-code changes automatically deploy under environment-derived API/UI image tags; chart template/value changes still require the chart `version` bump according to `../../AGENTS.md`. Manual or bundled releases also use explicit API/UI image tags rather than chart metadata.
