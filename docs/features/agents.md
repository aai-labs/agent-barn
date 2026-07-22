# Agents

## Read when

Read before changing agent creation, Agent Access Roles, explicit Agent Access assignments, Agent General Access, lifecycle, runtime or platform selection, template pinning, model selection, skill assignment, credentials, logs, health, or Kubernetes resources.

## Role in the system

An Agent is the central operational aggregate. It connects organization tenancy, a pinned template version, skills, platform credentials, provider integrations, a runtime deployment, ingest telemetry, and LiteLLM identity.

## Invariants

- Every agent belongs to one organization and pins an exact `(template_slug, template_version)` in that organization. The organization owns the Agent; creator identity is immutable provenance rather than ownership.
- Human Agent creation atomically records creator provenance and explicit Agent Owner access for the creator. A membership-less superuser has implicit Agent Owner authority in explicit Organization context and does not receive an access row.
- Organization Owner/Admin and superuser in explicit Organization context have implicit Agent Owner authority over every Agent. An Organization Member requires explicit Agent Access, applicable Agent General Access, or both; inaccessible and cross-Organization Agents are concealed with 404.
- The locked Agent Viewer role grants read, activity, and cost access; Agent Editor adds configuration, lifecycle, Skill assignment, and credential management; Agent Owner adds deletion and access management. Start and stop share the single `agent.lifecycle.manage` Permission because lifecycle authority is granted as one capability; current Agent state determines which transition is available.
- Any explicit role containing access-management Permission may grant, change, or revoke explicit access onward and read, set, change, or remove Agent General Access. Creator provenance is immutable but is not a separate authorization source.
- Explicit Agent Access is granted only to accepted Organization Members in the same Organization. Pending invitees and cross-Organization users are ineligible; removing a Membership cascades its access rows.
- Agent General Access is an Agent-level setting: Restricted or All Organization Members with one Agent Access Role. It applies only to accepted Memberships and is additive with explicit Agent Access; removing one source leaves the other source intact.
- Agent read DTOs expose current effective Agent-related Permission keys. The UI uses those keys for lifecycle, configuration, secret, activity, cost, and deletion controls rather than deriving Agent authority from either role family; mutations independently reauthorize and validate current state. AF-150 does not expose access-management UI.
- Runtime and platform are separate. Hermes supports Slack only; OpenClaw supports Slack and Teams.
- Persisted lifecycle states are `STOPPED`, `RUNNING`, and `ERROR`.
- Slack agents require bot and app tokens. Teams agents require app ID, app password, and tenant ID.
- Platform is not changed through agent update. Runtime/platform compatibility is schema-validated.
- Running agents reject configuration updates.
- Template-required skills are validated as explicit assignments during agent create, update, and repin, and cannot be removed while currently required.
- Provider requirements for assigned skills are validated during agent create/update against the agent's resulting Agent Secrets. Later edits to skill metadata are not revalidated at agent start.
- Agents are soft-deleted; deletion also removes runtime resources and attempts to block the LiteLLM key.
- Secret values are encrypted at rest and omitted from read DTOs.

## State model

```text
create Slack agent ───────────────→ STOPPED
create Teams agent ── auto-start ─→ RUNNING or ERROR
STOPPED or ERROR ─────── start ───→ RUNNING or ERROR
RUNNING ──────────────── stop ────→ STOPPED
any non-deleted state ── delete ──→ soft-deleted
```

Starting an already running agent and stopping an agent that is not running are conflicts. Start renders the pinned template anew, creates a fresh ingest key, rebuilds runtime resources, and clears a previous error on success.

## Primary flows

### Create

Creation requires `agent.create`, resolves the requested template version or the latest version, validates required skills and provider credentials, and atomically persists the Agent with creator provenance and explicit Agent Owner access before platform configuration. It then persists encrypted platform/integration configuration, assigns skills, and creates a per-agent LiteLLM key when configured. New Agents default Agent General Access to Restricted, so no other Member receives access automatically. Teams creation continues into start; Slack creation remains stopped.

### Update

Update is allowed only while not running. It can change runtime-relevant configuration, repin to an existing template version, add/remove allowed skills, and upsert/remove Agent Secrets. Repinning requires both slug and version and revalidates required skills.

### Start

Start renders the pinned template, decrypts credentials, selects Hermes/OpenClaw builders, combines explicit skills with provider-derived built-ins, appends integration context, creates a fresh ingest identity, and recreates Kubernetes configuration/deployment resources.

### Stop and delete

Stop snapshots logs before removing active runtime resources and marking the agent stopped. Delete removes resources, soft-deletes the row, and preserves the record for history and cost attribution.

### Manage access

Access-management endpoints list explicit assignments and locked Agent Access Roles, grant a selected explicit role, change an assignment's role, revoke an assignment, and read/set/change/remove Agent General Access. Implicit Organization Owner/Admin authority is not a revocable assignment. Access changes take effect on the next request; missing, cross-Organization, or inaccessible resources retain the documented 404 concealment behavior. Custom Agent Access Roles are added by AF-216, and access-management UI is added by AF-217.

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

Lifecycle, visibility, Agent Access Role, explicit Agent Access assignment, or Agent General Access changes affect Agent API contracts, authorization predicates, Membership deletion behavior, UI schemas and controls, and Agent integration tests. Runtime changes additionally affect both runtime builders, Kubernetes cleanup, and logs/health. Template/skill changes also require checking creation, repinning, update validation, and template/skill integration tests. Platform changes require checking Slack and Teams credential handling separately.
