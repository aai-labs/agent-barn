# Agents

## Read when

Read before changing agent creation, Agent Access Roles, explicit Agent Access assignments, Agent General Access, lifecycle, runtime or platform selection, template pinning, Agent Template Overrides, model selection, skill assignment, credentials, logs, health, or Kubernetes resources.

## Role in the system

An Agent is the central execution aggregate. It connects organization tenancy, an exact active shared Template or Agent Template Override version, Skills, tool Integrations, one Runtime deployment, telemetry, and LiteLLM identity. External chat transport is a separate Agent-subordinate Communications aggregate.

## Invariants

- Every Agent belongs to one Organization and pins an exact active shared Template Version or Agent Template Override Version. The Organization owns the Agent; creator identity is immutable provenance rather than ownership.
- Human Agent creation atomically records creator provenance and explicit Agent Owner access for the creator.
- Organization Owner/Admin have implicit Agent Owner authority over every Agent. An Organization Member requires explicit Agent Access, applicable Agent General Access, or both; inaccessible and cross-Organization Agents are concealed with 404.
- The locked Agent Viewer role grants read, activity, and cost access; Agent Editor adds configuration, lifecycle, Skill assignment, and credential management; Agent Owner adds deletion and access management. Start and stop share the single `agent.lifecycle.manage` Permission because lifecycle authority is granted as one capability; current Agent state determines which transition is available.
- Any effective role containing access-management Permission may replace the Agent's full share settings: Agent General Access plus the complete explicit Agent Access assignment list. Creator provenance is immutable but is not a separate authorization source.
- Explicit Agent Access is granted only to accepted Organization Members in the same Organization. Pending invitees and cross-Organization users are ineligible; removing a Membership cascades its access rows.
- Agent General Access is an Agent-level setting: Restricted or All Organization Members with one Agent Access Role. It applies only to accepted Memberships and is additive with explicit Agent Access; removing one source leaves the other source intact.
- Agent read DTOs expose current effective Agent-related Permission keys. The UI uses those keys for lifecycle, configuration, secret, activity, cost, and deletion controls rather than deriving Agent authority from either role family; mutations independently reauthorize and validate current state. AF-150 does not expose access-management UI.
- Runtime and Platform are independent. Hermes and OpenClaw both consume the same runtime-neutral Communications protocol. An Agent may own zero or many Communication Connections, including multiple Connections to the same Platform.
- Command approval is currently Hermes-only: the persisted `approval_mode` field maps onto the Hermes runtime's approval policy. OpenClaw has no user-configurable command-approval control, so create/update reject an explicit non-default `approval_mode` for an OpenClaw Agent (HTTP 400) rather than silently ignoring it, and reads report the effective `AUTO` default for OpenClaw regardless of the stored value. OpenClaw command approval is deferred to a future task.
- Persisted lifecycle states are `STOPPED`, `RUNNING`, and `ERROR`.
- An Agent's model is either inherited or overridden. An empty `model` means the Agent follows its Organization's default runtime model, resolved at every start; a non-empty `model` is an explicit override that no default change touches. Agent read DTOs expose `model_source` and the resolved `effective_model` so no client re-derives this. Sending `model: null` on update clears an override and returns the Agent to the default. See [`agent-settings.md`](agent-settings.md).
- The start-time model allowlist re-check applies only to Agents carrying an explicit override. An inheriting Agent runs Organization policy: its Organization's own default is held inside the allowlist by invariant, and a platform default it may instead be following is outside any Organization's control.
- Slack agents require bot and app tokens. Teams agents require app ID, app password, and tenant ID. Telegram and Discord agents require a bot token. Discord bots must enable Message Content Intent; bots using role-based access must also enable Server Members Intent. Discord guild access is allowlisted by default and direct messages are disabled by default.
- Agents respond in shared channels and groups only to messages that explicitly mention them, on every supported platform. Slack additionally requires that mention on every message rather than inheriting it from earlier thread participation; Teams and Telegram expose no equivalent control. Direct messages are exempt. Gating is generated at start; see [`../architecture/runtime-and-deployment.md`](../architecture/runtime-and-deployment.md).
- Each active Slack or Discord agent must use a distinct bot token within its platform (enforced globally); creating or updating with a duplicate returns 409. Deleting an agent releases its token for reuse.
- Platform is not changed through agent update. Runtime/platform compatibility is schema-validated.
- Per-Agent LiteLLM keys are encrypted at rest. Creation performs deterministic validation before allocating a key; if creation fails after allocation, the unowned key is deleted, and a failed deletion triggers a best-effort block as a safety fallback. Deleting an existing Agent soft-deletes it and blocks its key rather than deleting it, preserving the LiteLLM identity needed for historical spend attribution.
- Communication Connection settings and credentials are validated by the selected shipped Platform Plugin, encrypted independently of Agent Secrets, and omitted from read responses. Global plugin credential-identity constraints prevent two active Connections from owning the same bot/application identity where required.
- Communication health is independent of lifecycle: a provider session may be pending, connected, degraded, or errored while the Agent remains running. Retiring a Connection preserves its canonical Conversation Messages.
- The API rejects direct configuration updates while an Agent is running, but running Agent read DTOs still expose the caller's configuration and secret permissions so the canonical UI can offer section-specific apply actions. Runtime configuration changes use `Apply & Restart`; Template selection uses `Apply` while stopped or `Apply & Restart` while running, with the latter stopping the Agent, selecting the published version, and starting it again. For stopped Agents, `Apply` changes the active pin and leaves the Agent stopped until the user starts it from the Agent detail page.
- Template-required skills are validated as explicit assignments during agent create, update, and repin, and cannot be removed while currently required.
- Each assigned skill is pinned to an exact version at apply time (mirroring template pins): `agent_skill.pinned_version`. Publishing a newer skill version never moves an existing pin, and an agent recovers from a bad version by re-pinning to an older one. Start mounts each assigned skill's pinned-version files; a version pinned by any agent is protected from skill version deletion.
- Provider requirements for assigned skills are validated during agent create/update against the agent's resulting Agent Secrets. During Agent creation, the service live-validates the exact submitted manual and shared credentials before allocating a LiteLLM key or persisting the Agent; providers without a live validator still receive schema validation and remain eligible for on-demand validation. Later edits to skill metadata are not revalidated at Agent start.
- Agents are soft-deleted; deletion also removes runtime resources, retires all owned Communication Connections (releasing their provider credential identities), and attempts to block the LiteLLM key.
- Secret values are encrypted at rest and omitted from read DTOs. Google Workspace credentials are validated as one service-scoped OAuth payload and materialized through the gog CLI; retired per-service Google providers are not supported.

## State model

```text
create Agent ───────────────────────→ STOPPED
STOPPED or ERROR ───────── start ───→ RUNNING or ERROR
RUNNING ────────────────── stop ────→ STOPPED
any non-deleted state ──── delete ──→ soft-deleted
```

Starting an already running agent and stopping an agent that is not running are conflicts. Start renders the pinned template anew, creates a fresh ingest key, rebuilds runtime resources, and clears a previous error on success.

## Primary flows

### Create

Creation requires `agent.create`, resolves the requested Template Version or latest version, validates required Skills and tool-provider credentials, live-validates supported provider credentials from the exact request, and atomically persists the Agent with creator provenance and explicit Agent Owner access. It persists Agent Secrets, assigns Skills, and creates a per-Agent LiteLLM key when configured only after deterministic and live preflight validation. New Agents are headless and `STOPPED`; Communication Connections are added independently after creation. Agent General Access defaults to Restricted, so no other Member receives access automatically.

### Update

Update is allowed only while not running. It can change runtime-relevant configuration, repin to an existing template version, add/remove allowed skills, and upsert/remove Agent Secrets. The configuration UI stops a running Agent before submitting these updates and starts it again after a successful or failed update so the lifecycle remains explicit. Repinning requires both template_key and version and revalidates required skills.

### Tuning and configuration overrides

The canonical Agent configuration page is a settings-style surface with Profile first, followed by Template selection, Communication Connections, Skills, Keys & Integrations, Agent-owned overrides, and the Danger zone. Profile combines editable identity/runtime preferences with read-only runtime and deployment facts. Model is a choice between following the Organization's default and pinning a specific model; reads name the source and resolved value. Agent configuration changes use `Apply & Restart` for running Agents or `Apply` for stopped Agents. Communication Connections have independent schema-driven create/edit/enable/disable/retire workflows and may change without restarting a running Agent. Connection mutation requires `agent.update`; credential creation, replacement, or retirement additionally requires `agent.secret.manage`. Secret values remain encrypted and are never returned.

The AF-253 Agent Template Override contract is a dedicated section of the canonical configuration page. It adds read-only history, one Agent-owned draft, explicit publish and version selection, immutable snapshots, source-labeled updates, rollback without draft mutation, optimistic concurrency, and Restart-only activation for running Agents. Published overrides also appear in the shared Template selection picker, where applying one uses the same `Apply & Restart` path. Platform Template publishing and Organization Template Updates never move existing Agent pins automatically.

### Start

Start renders the pinned Template, decrypts Agent Secrets, selects Hermes/OpenClaw builders, combines explicit Skills with provider-derived built-ins, materializes aai-cli integrations and Google Workspace's gog artifacts, appends Integration context and runtime behaviour policy, creates fresh Ingest and Communications protocol identities, and recreates Kubernetes resources. Communication Connection credentials are never materialized into the runtime. A successful transition to `RUNNING` emits `agent.started`; its email handler notifies the Agent Creator and users with Agent Owner access, de-duplicated by email.

### Stop and delete

Stop snapshots logs before removing active runtime resources and marking the Agent stopped. A successful transition to `STOPPED` emits `agent.stopped`; its email handler notifies the Agent Creator and users with Agent Owner access, de-duplicated by email. Delete removes runtime resources, retires all owned Communication Connections (cancelling pending deliveries and releasing provider credential identities), soft-deletes the Agent, and preserves the record for history and cost attribution. Individual Communication Connection retirement remains an independent Communications workflow.

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
| HTTP routes                                | `../../api/domains/agents/routes.py` |
| Communication Connections and Plugins     | `../../api/domains/communications/` |
| Runtime resources                          | `../../api/domains/agents/builders/`                                                                               |
| Integration and skill artifacts            | `../../api/domains/agents/aai_cli_artifacts.py`, `../../api/domains/agents/aai_cli_skills/`, `../../api/domains/agents/gog_artifacts.py`                                                 |
| UI contracts and hooks                     | `../../ui/src/features/agents/schemas.ts`, `../../ui/src/features/agents/hooks/`                                         |
| UI components                              | `../../ui/src/features/agents/components/`                                                                         |
| Model inheritance and Organization defaults | `../../api/domains/agent_settings/`, [`agent-settings.md`](agent-settings.md) |
| Integration coverage                       | `../../api/tests/integration/test_agents.py`, `../../api/tests/integration/test_agent_rbac.py`, `../../api/tests/integration/test_agent_general_access.py`, `../../api/tests/integration/test_agent_logs.py` |

## Related decisions

- [`2026-07-21-separate-organization-and-agent-access-roles.md`](../adr/2026-07-21-separate-organization-and-agent-access-roles.md)
- [`2026-07-21-additive-agent-general-access.md`](../adr/2026-07-21-additive-agent-general-access.md)
- [`2026-08-09-agent-scoped-template-overrides.md`](../adr/2026-08-09-agent-scoped-template-overrides.md)
- [`2026-08-19-organization-scoped-agent-settings.md`](../adr/2026-08-19-organization-scoped-agent-settings.md)
- [`2026-08-22-agent-barn-owned-communications-gateway.md`](../adr/2026-08-22-agent-barn-owned-communications-gateway.md)

## Change impact

Lifecycle, visibility, Agent Access Role, explicit Agent Access assignment, or Agent General Access changes affect Agent API contracts, authorization predicates, Membership deletion behavior, UI schemas and controls, and Agent integration tests. Runtime changes additionally affect both runtime builders, Kubernetes cleanup, logs/health, and the runtime-neutral Communications protocol. Template/Skill changes require checking creation, repinning, update validation, and integration tests. Platform changes belong to the Communications domain and must not introduce Agent lifecycle or runtime-builder branches.
