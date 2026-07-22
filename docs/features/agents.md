# Agents

## Read when

Read before changing agent creation, lifecycle, runtime or platform selection, template pinning, model selection, skill assignment, credentials, logs, health, or Kubernetes resources.

## Role in the system

An Agent is the central operational aggregate. It connects organization tenancy, a pinned template version, skills, platform credentials, provider integrations, a runtime deployment, ingest telemetry, and LiteLLM identity.

## Invariants

- Every agent belongs to one organization and pins an exact `(template_slug, template_version)` in that organization.
- Runtime and platform are separate. Hermes supports Slack and Telegram; OpenClaw supports Slack, Teams, and Telegram.
- Persisted lifecycle states are `STOPPED`, `RUNNING`, and `ERROR`.
- Slack agents require bot and app tokens. Teams agents require app ID, app password, and tenant ID. Telegram agents require a bot token.
- Platform is not changed through agent update. Runtime/platform compatibility is schema-validated.
- Running agents reject configuration updates.
- Template-required skills are validated as explicit assignments during agent create, update, and repin, and cannot be removed while currently required.
- Provider requirements for assigned skills are validated during agent create/update against the agent's resulting Agent Secrets. Later edits to skill metadata are not revalidated at agent start.
- Agents are soft-deleted; deletion also removes runtime resources and attempts to block the LiteLLM key.
- Secret values are encrypted at rest and omitted from read DTOs.

## State model

```text
create Slack agent ─────────────────→ STOPPED
create Teams agent ──── auto-start ─→ RUNNING or ERROR
create Telegram agent ─ auto-start ─→ RUNNING or ERROR
STOPPED or ERROR ───────── start ───→ RUNNING or ERROR
RUNNING ────────────────── stop ────→ STOPPED
any non-deleted state ──── delete ──→ soft-deleted
```

Starting an already running agent and stopping an agent that is not running are conflicts. Start renders the pinned template anew, creates a fresh ingest key, rebuilds runtime resources, and clears a previous error on success.

## Primary flows

### Create

Creation resolves the requested template version or the latest version, validates required skills and provider credentials, persists encrypted platform/integration configuration, assigns skills, and creates a per-agent LiteLLM key when configured. Teams and Telegram creation continues into start; Slack creation remains stopped.

### Update

Update is allowed only while not running. It can change runtime-relevant configuration, repin to an existing template version, add/remove allowed skills, and upsert/remove Agent Secrets. Repinning requires both slug and version and revalidates required skills.

### Start

Start renders the pinned template, decrypts credentials, selects Hermes/OpenClaw builders, combines explicit skills with provider-derived built-ins, appends integration context, creates a fresh ingest identity, and recreates Kubernetes configuration/deployment resources.

### Stop and delete

Stop snapshots logs before removing active runtime resources and marking the agent stopped. Delete removes resources, soft-deletes the row, and preserves the record for history and cost attribution.

## Source map

| Concern                                    | Authoritative source                                                                                         |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| Persistence, enums, request/read contracts | `../../api/domains/agents/models.py`                                                                               |
| Lifecycle and cross-domain orchestration   | `../../api/domains/agents/service.py`                                                                              |
| Tenant-scoped persistence                  | `../../api/domains/agents/repository.py`                                                                           |
| HTTP routes                                | `../../api/domains/agents/routes.py`, `../../api/domains/agents/slack_routes.py`, `../../api/domains/agents/webhook_routes.py` |
| Runtime resources                          | `../../api/domains/agents/builders/`                                                                               |
| Integration and skill artifacts            | `../../api/domains/agents/aai_cli_artifacts.py`, `../../api/domains/agents/aai_cli_skills/`                                                 |
| UI contracts and hooks                     | `../../ui/src/features/agents/schemas.ts`, `../../ui/src/features/agents/hooks/`                                         |
| UI components                              | `../../ui/src/features/agents/components/`                                                                         |
| Integration coverage                       | `../../api/tests/integration/test_agents.py`, `../../api/tests/integration/test_agent_logs.py`                           |

## Change impact

Lifecycle or runtime changes affect agent API contracts, both runtime builders, Kubernetes cleanup, logs/health, UI schemas and controls, and agent integration tests. Template/skill changes also require checking creation, repinning, update validation, and template/skill integration tests. Platform changes require checking Slack, Teams, and Telegram credential handling separately.
