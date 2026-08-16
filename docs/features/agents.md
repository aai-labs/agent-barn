# Agents

## Read when

Read before changing agent creation, Agent Access Roles, explicit Agent Access assignments, Agent General Access, lifecycle, runtime or platform selection, template pinning, model selection, skill assignment, credentials, logs, health, or Kubernetes resources.

## Role in the system

An Agent is the central operational aggregate. It connects organization tenancy, a pinned template version, skills, platform credentials, provider integrations, a runtime deployment, ingest telemetry, and LiteLLM identity.

## Invariants

- Every agent belongs to one organization and pins an exact Template version visible to that organization. The organization owns the Agent; creator identity is immutable provenance rather than ownership.
- Human Agent creation atomically records creator provenance and explicit Agent Owner access for the creator.
- Organization Owner/Admin have implicit Agent Owner authority over every Agent. An Organization Member requires explicit Agent Access, applicable Agent General Access, or both; inaccessible and cross-Organization Agents are concealed with 404.
- The locked Agent Viewer role grants read, activity, and cost access; Agent Editor adds configuration, lifecycle, Skill assignment, and credential management; Agent Owner adds deletion and access management. Start and stop share the single `agent.lifecycle.manage` Permission because lifecycle authority is granted as one capability; current Agent state determines which transition is available.
- Any effective role containing access-management Permission may replace the Agent's full share settings: Agent General Access plus the complete explicit Agent Access assignment list. Creator provenance is immutable but is not a separate authorization source.
- Explicit Agent Access is granted only to accepted Organization Members in the same Organization. Pending invitees and cross-Organization users are ineligible; removing a Membership cascades its access rows.
- Agent General Access is an Agent-level setting: Restricted or All Organization Members with one Agent Access Role. It applies only to accepted Memberships and is additive with explicit Agent Access; removing one source leaves the other source intact.
- Agent read DTOs expose current effective Agent-related Permission keys. The UI uses those keys for lifecycle, configuration, secret, activity, cost, and deletion controls rather than deriving Agent authority from either role family; mutations independently reauthorize and validate current state. AF-150 does not expose access-management UI.
- Runtime and platform are separate. Hermes supports Slack, Telegram, and Discord; OpenClaw supports Slack, Teams, Telegram, and Discord.
- Persisted lifecycle states are `STOPPED`, `RUNNING`, and `ERROR`.
- Slack agents require bot and app tokens. Teams agents require app ID, app password, and tenant ID. Telegram and Discord agents require a bot token. Discord guild access is allowlisted by default and direct messages are disabled by default.
- Agents respond in shared channels and groups only to messages that explicitly mention them, on every supported platform. Slack additionally requires that mention on every message rather than inheriting it from earlier thread participation; Teams and Telegram expose no equivalent control. Direct messages are exempt. Gating is generated at start; see [`../architecture/runtime-and-deployment.md`](../architecture/runtime-and-deployment.md).
- Each active Slack or Discord agent must use a distinct bot token within its platform (enforced globally); creating or updating with a duplicate returns 409. Deleting an agent releases its token for reuse.
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
create Discord agent ───────────────→ STOPPED
STOPPED or ERROR ───────── start ───→ RUNNING or ERROR
RUNNING ────────────────── stop ────→ STOPPED
any non-deleted state ──── delete ──→ soft-deleted
```

Starting an already running agent and stopping an agent that is not running are conflicts. Start renders the pinned template anew, creates a fresh ingest key, rebuilds runtime resources, and clears a previous error on success.

## Primary flows

### Create

Creation requires `agent.create`, resolves the requested template version or the latest version, validates required skills and provider credentials, and atomically persists the Agent with creator provenance and explicit Agent Owner access before platform configuration. It then persists encrypted platform/integration configuration, assigns skills, and creates a per-agent LiteLLM key when configured. Bot token uniqueness is validated against active Agents on the same platform before persisting Slack or Discord credentials. New Agents default Agent General Access to Restricted, so no other Member receives access automatically. Teams and Telegram creation continues into start; Slack and Discord creation remain stopped.

### Update

Update is allowed only while not running. It can change runtime-relevant configuration, repin to an existing template version, add/remove allowed skills, and upsert/remove Agent Secrets. Repinning requires both template_key and version and revalidates required skills.

### Tuning and configuration overrides

The Agent configuration drawer is the per-Agent tuning surface. While an Agent is stopped and the caller has `agent.update`, it can override the Agent name, Configured Model, Command Approval Mode, platform routing (Slack channels/DMs, Teams endpoint, Telegram chats, or Discord guilds), pinned Template Version, and explicit Skill assignments. Secret and credential changes additionally require `agent.secret.manage`; secret values remain encrypted and are never returned.

Template Markdown is not edited as an unversioned per-Agent override. Selecting a different Template Version is an explicit repin of that Agent, and the resulting required-skill and provider-credential checks run before the change is accepted. Platform Template publishing and Organization Template Updates never move existing Agent pins automatically. Running Agents reject all configuration overrides, so stop the Agent before applying tuning changes.

### Start

Start renders the pinned template, decrypts credentials, selects Hermes/OpenClaw builders, combines explicit skills with provider-derived built-ins, appends integration context and runtime behaviour policy, creates a fresh ingest identity, and recreates Kubernetes configuration/deployment resources. A successful transition to `RUNNING` emits `agent.started`; its email handler notifies the Agent Creator and users with Agent Owner access, de-duplicated by email.

### Stop and delete

Stop snapshots logs before removing active runtime resources and marking the agent stopped. A successful transition to `STOPPED` emits `agent.stopped`; its email handler notifies the Agent Creator and users with Agent Owner access, de-duplicated by email. Delete removes resources, soft-deletes the row, and preserves the record for history and cost attribution. Deletion also clears the Slack bot token hash, releasing the token for reuse by another agent.

### Manage access

Share-management endpoints expose locked Agent Access Roles and one canonical Agent share snapshot. `GET /agents/{agent_id}/share` returns Agent General Access plus explicit Agent Access assignments, and `PUT /agents/{agent_id}/share` replaces both in one transaction. Implicit Organization Owner/Admin authority is not a revocable assignment. Share changes take effect on the next request; missing, cross-Organization, or inaccessible resources retain the documented 404 concealment behavior. Custom Agent Access Roles are added by AF-216, and access-management UI is added by AF-217.

## Source map

| Concern                                    | Authoritative source                                                                                         |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| Persistence, enums, request/read contracts | `../../api/domains/agents/models.py`                                                                               |
| Lifecycle and cross-domain orchestration   | `../../api/domains/agents/service.py`                                                                              |
| Tenant/access-scoped persistence           | `../../api/domains/agents/repository.py`                                                                           |
| Agent visibility and effective actions     | `../../api/domains/agents/authorization.py`                                                                        |
| Agent Access workflows                     | `../../api/domains/agents/access_service.py`                                                                        |
| HTTP routes                                | `../../api/domains/agents/routes.py`, `../../api/domains/agents/slack_routes.py`, `../../api/domains/agents/webhook_routes.py` |
| Runtime resources                          | `../../api/domains/agents/builders/`                                                                               |
| Integration and skill artifacts            | `../../api/domains/agents/aai_cli_artifacts.py`, `../../api/domains/agents/aai_cli_skills/`                                                 |
| UI contracts and hooks                     | `../../ui/src/features/agents/schemas.ts`, `../../ui/src/features/agents/hooks/`                                         |
| UI components                              | `../../ui/src/features/agents/components/`                                                                         |
| Integration coverage                       | `../../api/tests/integration/test_agents.py`, `../../api/tests/integration/test_agent_rbac.py`, `../../api/tests/integration/test_agent_general_access.py`, `../../api/tests/integration/test_agent_logs.py` |

## Related decisions

- [`2026-07-21-separate-organization-and-agent-access-roles.md`](../adr/2026-07-21-separate-organization-and-agent-access-roles.md)
- [`2026-07-21-additive-agent-general-access.md`](../adr/2026-07-21-additive-agent-general-access.md)

## Change impact

Lifecycle, visibility, Agent Access Role, explicit Agent Access assignment, or Agent General Access changes affect Agent API contracts, authorization predicates, Membership deletion behavior, UI schemas and controls, and Agent integration tests. Runtime changes additionally affect both runtime builders, Kubernetes cleanup, and logs/health. Template/skill changes also require checking creation, repinning, update validation, and template/skill integration tests. Platform changes require checking Slack, Teams, Telegram, and Discord credential handling separately.
