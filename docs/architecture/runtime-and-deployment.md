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

## Telemetry and costs

Agent runtimes report messages and tool-call state to the separate Ingest API using the per-start ingest key. Ingest authentication currently remains valid after stop because status is not checked and the stored key is not cleared. Costs follow a separate path: the API queries LiteLLM and attributes spend through each agent's LiteLLM key identity.

## Service deployment

`../../helmfile.yaml.gotmpl` orders PostgreSQL releases, LiteLLM, API, and UI. API deployment mounts Kubernetes access so the service can manage agent resources. An API Helm hook runs Alembic before installation or upgrade, and health probes use `/api/v1/health`.

The deploy workflow reads API and UI image tags from each chart's `appVersion`, builds versioned images, and applies Helmfile. `../../AGENTS.md` is authoritative for independent API/UI `appVersion` and chart `version` rules.

## Kubernetes client constraint

Kubernetes `stream()` and `portforward()` temporarily monkey-patch `ApiClient.request` while establishing WebSocket connections. They use a dedicated `CoreV1Api` and `ApiClient` so concurrent REST operations cannot hit the patched handler; keep streaming and ordinary CRUD clients isolated.

## Source map

| Concern                         | Source                                                                          |
| ------------------------------- | ------------------------------------------------------------------------------- |
| Runtime orchestration           | `../../api/domains/agents/service.py`                                                 |
| Ingest process and routing      | `../../api/ingest_app.py`, `../../api/ingest_main.py`, `../../api/start.sh`                       |
| Shared Kubernetes builders      | `../../api/domains/agents/builders/common.py`                                         |
| Hermes builders                 | `../../api/domains/agents/builders/hermes.py`, `../../hermes-base/`                         |
| OpenClaw builders               | `../../api/domains/agents/builders/openclaw.py`, `../../openclaw-base/`                     |
| Skill and integration artifacts | `../../api/domains/agents/aai_cli_artifacts.py`, `../../api/domains/agents/aai_cli_skills/` |
| Telegram client                 | `../../api/infrastructure/telegram/`                                                  |
| Kubernetes client               | `../../api/infrastructure/kubernetes/`                                                |
| Charts and release ordering     | `../../helm/`, `../../helmfile.yaml.gotmpl`                                                 |
| Deployment workflow             | `../../.github/workflows/deploy.yml`                                                  |

## Change impact

Runtime changes must be checked against both platforms, builders, images/base configuration, agent lifecycle tests, telemetry, and persisted configuration contracts. Service-code changes require the affected chart `appVersion` bump; chart template/value changes require the chart `version` bump according to `../../AGENTS.md`.
