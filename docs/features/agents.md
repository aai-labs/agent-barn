# Agents

## Read when

Read before changing agent creation, Agent Access Roles, explicit Agent Access assignments, Agent General Access, lifecycle, runtime or platform selection, template pinning, Agent Template Overrides, model selection, skill assignment, credentials, logs, health, Agent Restore Points, memory groups (shared memory pools) or memory viewing/curation/sharing, or Kubernetes resources.

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
- The Dashboard Web Chat composer accepts new messages only while the Agent is `RUNNING` and its health status is `ok` (shown as Working). A thread remains visibly awaiting a reply while its latest durable inbound Communication Delivery is `PENDING` or `PROCESSING`, so the working indicator survives tab navigation and page remounts until an outbound reply arrives or the user stops generation. Stop is durable and suppresses late replies for both runtimes; neither pinned runtime currently exposes a proven abort handle for this chat-completions path, so the product does not promise compute interruption.
- Command approval is currently Hermes-only: the persisted `approval_mode` field maps onto the Hermes runtime's approval policy. OpenClaw has no user-configurable command-approval control, so create/update reject an explicit non-default `approval_mode` for an OpenClaw Agent (HTTP 400) rather than silently ignoring it, and reads report the effective `AUTO` default for OpenClaw regardless of the stored value. OpenClaw command approval is deferred to a future task.
- Answering a Hermes approval prompt with `always` is permanent: the pattern is retained across Agent restarts and is not re-prompted. It covers the whole category of command, not the one command shown. Manual mode ignores these grants and asks for every flagged command, offering only `once` and `deny`; the grants return when the Agent leaves manual mode, and removing one is permanent. Scheduled and heartbeat runs have no one to prompt, so a dangerous command reached from cron or the heartbeat is denied rather than parked; a `BOOT.md` command is parked until it times out, so startup work should avoid flagged commands. See [`../architecture/runtime-and-deployment.md`](../architecture/runtime-and-deployment.md).
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
- Agent Restore Points capture and restore only while the Agent is `STOPPED`, and only one capture or restore may be in flight per Agent — enforced by a database constraint, not only a service check. The per-Agent retention cap counts manual restore points that still hold a volume: Pre-Restore Restore Points and failed captures do not consume it, so an Agent at the cap can still roll back and a run of failures cannot lock it out of capturing.
- A restore point archive never contains credential material or state the runtime regenerates on boot, so it is not a byte-exact image of the volume. Reads authorize on `activity.read`; capture, restore, and delete on `agent.lifecycle.manage`. No restore-point-specific Permission exists.

## State model

```text
create Agent ───────────────────────→ STOPPED
STOPPED or ERROR ───────── start ───→ RUNNING or ERROR
RUNNING ────────────────── stop ────→ STOPPED
any non-deleted state ──── delete ──→ soft-deleted
```

A capture or restore of an Agent Restore Point also blocks start and delete while it runs, because the Agent's volume is ReadWriteOnce and the Job holds it.

Starting an already running agent and stopping an agent that is not running are conflicts. Start renders the pinned template anew, creates a fresh ingest key, rebuilds runtime resources, and clears a previous error on success.

## Primary flows

### Create

Creation requires `agent.create`, resolves the requested Template Version or latest version, validates required Skills and tool-provider credentials, live-validates supported provider credentials from the exact request, and atomically persists the Agent with creator provenance and explicit Agent Owner access. It persists Agent Secrets, assigns Skills, and creates a per-Agent LiteLLM key when configured only after deterministic and live preflight validation. New Agents are headless and `STOPPED`; Communication Connections are added independently after creation. Agent General Access defaults to Restricted, so no other Member receives access automatically.

### Suggested names

The hiring dialog suggests `<first name> the <template name>`. It cycles initials A–Z using the
Organization's total persisted Agent count modulo 26, including soft-deleted Agents and manually
named Agents. Each suggestion randomly chooses a distinct spelling from the supplied names for
that initial. Existing Agents contribute to the count and retain their names. Deleting an Agent
does not rewind the sequence. No separate counter or name uniqueness constraint is maintained.

`GET /organizations/{organization_id}/agents/name-suggestion` requires `agent.create` and returns
only `first_name`; it does not reserve or persist a name. Concurrent dialogs may repeat names,
and creation preserves the submitted name even when another creation has changed the count.
The create API still requires `name`. Failed creation does not advance the count; failure to
start an already-created Agent does.

Before Template selection, and for the `General Purpose` display name, the suffix is `Assistant`.
Other Template display names are used verbatim, truncated only when needed to fit the 255-character
Agent name limit. Template changes update the suggestion until the user edits the name manually.
The dialog retains its first name throughout the opening, offers manual entry and retrieval retry
on failure, and has no shuffle control. Reopening fetches a fresh suggestion.

### Update

Update is allowed only while not running. It can change runtime-relevant configuration, repin to an existing template version, add/remove allowed skills, and upsert/remove Agent Secrets. The configuration UI stops a running Agent before submitting these updates and starts it again after a successful or failed update so the lifecycle remains explicit. Repinning requires both template_key and version and revalidates required skills.

### Tuning and configuration overrides

The canonical Agent configuration page is a settings-style surface with Profile first, followed by Template selection, Communication Connections, Skills, Keys & Integrations, Agent-owned overrides, and the Danger zone. Profile combines editable identity/runtime preferences with read-only runtime and deployment facts. Model is a choice between following the Organization's default and pinning a specific model; reads name the source and resolved value. The Skills section keeps its assignment editor visible for users with `agent.update`: selected Skills appear first in an “In use” card grid, and available Skills appear below in the Add skills grid. Selected cards carry an “In use” badge; the available catalogue has debounced API-backed search and progressive page loading. Every card opens the Agent-scoped detail view; in-use cards retain version pinning and Remove controls, while available cards expose a primary Add action. Removing a skill requires confirmation before it is staged. Add/Remove/repin changes enable `Apply` or `Apply & Restart` only when there is a valid pending change. Agent configuration changes use `Apply & Restart` for running Agents or `Apply` for stopped Agents. Communication Connections have independent schema-driven create/edit/enable/disable/retire workflows and may change without restarting a running Agent. Connection mutation requires `agent.update`; credential creation, replacement, or retirement additionally requires `agent.secret.manage`. Secret values remain encrypted and are never returned.

The AF-253 Agent Template Override contract is a dedicated section of the canonical configuration page. It adds read-only history, one Agent-owned draft, explicit publish and version selection, immutable snapshots, source-labeled updates, rollback without draft mutation, optimistic concurrency, and Restart-only activation for running Agents. Published overrides also appear in the shared Template selection picker, where applying one uses the same `Apply & Restart` path. Platform Template publishing and Organization Template Updates never move existing Agent pins automatically.

### Start

Start renders the pinned Template, decrypts Agent Secrets, selects Hermes/OpenClaw builders, combines explicit Skills with provider-derived built-ins, materializes aai-cli integrations and Google Workspace's gog artifacts, appends Integration context and runtime behaviour policy, creates fresh Ingest and Communications protocol identities, and recreates Kubernetes resources. Communication Connection credentials are never materialized into the runtime. A successful transition to `RUNNING` emits `agent.started`; its email handler notifies the Agent Creator and users with Agent Owner access, de-duplicated by email.

### Stop and delete

Stop snapshots logs before removing active runtime resources and marking the Agent stopped. A successful transition to `STOPPED` emits `agent.stopped`; its email handler notifies the Agent Creator and users with Agent Owner access, de-duplicated by email. Delete removes runtime resources, retires all owned Communication Connections (cancelling pending deliveries and releasing provider credential identities), soft-deletes the Agent, and preserves the record for history and cost attribution. Individual Communication Connection retirement remains an independent Communications workflow.

### Capture and restore

An Agent Restore Point captures the Agent's persistent volume into its own volume, run by a Kubernetes Job that mounts both. Capture and restore each require a `STOPPED` Agent: the volume is ReadWriteOnce, so the Job cannot hold it while the Agent pod does. An Agent that has never started has no volume yet and is refused with a distinct message from the legitimate case of an Agent whose volume holds only regenerated state, which captures zero files and is still ready.

The archive excludes credential material — for Hermes the plaintext provider-token store and its decryption key under `.config/aai-cli` — every file the runtime's start script rewrites on boot, and the durable message spool, whose restoration would re-send or drop queued messages. It retains each runtime's agent-owned `USER.md`, which lives in different places per runtime.

Restore first captures the current volume as a Pre-Restore Restore Point, then validates the chosen archive, wipes the target and extracts, all inside one Job so the safety net is on disk before anything is destroyed. A corrupt or unsafe archive is rejected before the wipe, leaving the volume untouched. Restored files are given the ownership the volume already had, because OpenClaw's ownership repair on boot is not recursive. A restore is never retried automatically, because a second attempt would capture the already-wiped volume over the good backup. When a restore fails, the failed phase decides the outcome: if the safety net never finished, the Agent volume was never touched and the chosen restore point stays ready; if it did finish, the Pre-Restore Restore Point stays ready as the rollback path. When the phase cannot be established — which includes every restore killed by its time limit, since Kubernetes deletes the Job's pod and its logs with it — neither volume is released: the Pre-Restore Restore Point is marked failed but keeps its volume, so it can be inspected or deleted rather than lost.

Two consequences are worth stating plainly. The runtime's own session history lives on the volume and rolls back with it, while Agent Barn's conversation record does not — after a restore the product's history is ahead of the runtime's, which is correct because the product record is the audit trail. And deleting an Agent destroys its restore points irreversibly even though the Agent row itself is only soft-deleted, so deletion is the one path this feature cannot undo.

### Manage access

Share-management endpoints expose locked Agent Access Roles and one canonical Agent share snapshot. `GET /agents/{agent_id}/share` returns Agent General Access plus explicit Agent Access assignments, and `PUT /agents/{agent_id}/share` replaces both in one transaction. Implicit Organization Owner/Admin authority is not a revocable assignment. Share changes take effect on the next request; missing, cross-Organization, or inaccessible resources retain the documented 404 concealment behavior. Custom Agent Access Roles are added by AF-216, and access-management UI is added by AF-217.

### Memory groups (shared pools)

Memory is **opt-in through memory groups**. A group is a shared memory pool: every Agent in a group uses one Honcho workspace, `af-pool-<group id>`, so members see what the others have learned. `agent.memory_group_id` (nullable FK, `SET NULL` on group delete) records an Agent's group; an Agent in no group has no shared memory, and `memory_active` requires both Honcho deployed and the Agent in a group. Adding an Agent to a group is the opt-in and removing it is the opt-out — the change reaches the Agent on its next start, and opting out only revokes access, leaving the Agent's past contributions in the pool. Members keep **distinct Honcho peers**, so contributions stay attributable to the Agent that made them. Group management (create/rename/delete, assign Agents) is org-scoped and gated on `memory_group.manage`; see [`../adr/2026-09-21-shared-memory-pools-via-groups.md`](../adr/2026-09-21-shared-memory-pools-via-groups.md).

### View and curate memory

Memory is a tab on the Agent detail page, alongside conversations, tool calls, logs, and work. `GET /agents/{agent_id}/memory` lists conclusions from the Agent's pool, paginated, each item carrying the (observer, observed) peer pair it belongs to — memory is stored per pair, so every member holds a separate view of each person it talks to plus a model of itself. A `scope` param picks the view: `pool` (default) shows what the whole group knows — every member's conclusions, so the Agent sees what the others learned — while `mine` narrows to this Agent as observer, its own contributions. `GET /agents/{agent_id}/memory/search?q=` searches the pool semantically; Honcho stores those vectors per pair and rejects a query that does not name both peers, so a search fans out across peers and merges, capped because the fan-out is quadratic in peer count. Both need `agent.memory.read`, and both return 409 if the Agent is in no group (there is no pool to read).

`DELETE /agents/{agent_id}/memory/{memory_id}` forgets one item and `PUT` replaces its content; both need `agent.memory.manage`, because changing what the pool knows changes how every member behaves. Honcho has no update endpoint, so a correction is a delete followed by a create: the item gets a new id, and the replacement is always `explicit` since a level cannot be set on create — a corrected inference stops being labelled an inference. `owner` is not a user but the peer for messages that arrived with no sender identity.

Curation acts on the shared pool, not a per-Agent store, so a forget or correct by one member removes or rewrites the fact for the whole group. Deleting an Agent never erases the pool: `delete_workspace` refuses a pool workspace, so one member's teardown can never nuke memory the others still rely on. Erasing a pool is done deliberately by deleting the *group*, which also drops its members via the FK.

### Share memory across pools

Sharing *within* a group is automatic through the shared workspace; these paths cross the boundary *between* pools. Distinct pools are separate Honcho workspaces (`workspace_name` participates in nearly every composite foreign key, so isolation is a schema property), so crossing it always means copying into the destination — the destination keeps its copy even if the source later forgets it.

The primary, group-native path is `POST /organizations/{organization_id}/memory-groups/{source_group_id}/shared-items` `{ memory_id, target_group_ids }`: it reads one conclusion from the source pool and copies it into each target pool. It is gated on `memory_group.manage` (a group operation), org-scoped (source and every target must be in the caller's org), rejects a group sharing with itself (400) and a memory that is not in the source pool (404). The copy is written onto the destination pool's neutral `owner` peer — knowledge handed to the whole pool, not attributed to one member — and recalled pool-wide like any other pooled memory. Origin is tracked in `shared_pool_memory_fact` (kept in the agents domain so the memory read path joins it without a cross-domain cycle) and returned as `sharedFromGroupId`; the client resolves the group name, so the item reads "Shared from <group>". The memory tab exposes this as a per-item "Share to group" action, visible to a group manager. Deleting the source group nulls the id (badge falls back to a neutral "Shared in"); deleting the target group drops the row with its pool.

The older Agent-keyed paths remain for seeding a specific Agent's pool: `POST /agents/{agent_id}/memory/shared-facts` promotes typed content into destination Agents' pools (tracked in `shared_memory_fact`, read as "Shared by <agent>"), and `POST /agents/{agent_id}/memory/carry-over` copies a source Agent's whole pool into other Agents' pools, bounded to a rescue-sized batch. Both require the source and every destination to be in a group (409 otherwise). A shared fact's source Agent is audit context only (`agent.read`); carry-over reads the source's memory (`agent.memory.read`); every destination needs `agent.memory.manage`, and must be an active (non-deleted) Agent.

## Source map

| Concern                                     | Authoritative source                                                                                                                                                                                         |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Persistence, enums, request/read contracts  | `../../api/domains/agents/models.py`                                                                                                                                                                         |
| Lifecycle and cross-domain orchestration    | `../../api/domains/agents/service.py`                                                                                                                                                                        |
| Tenant/access-scoped persistence            | `../../api/domains/agents/repository.py`                                                                                                                                                                     |
| Agent visibility and effective actions      | `../../api/domains/agents/authorization.py`                                                                                                                                                                  |
| Agent Access workflows                      | `../../api/domains/agents/access_service.py`                                                                                                                                                                 |
| Restore point capture, restore, and reconciliation | `../../api/domains/restore_points/`                                                                                                                                   |
| Restore point Job entrypoint and exclusion sets | `../../api/domains/agents/restore_point_job.py`                                                                                                                          |
| HTTP routes                                 | `../../api/domains/agents/routes.py`                                                                                                                                                                         |
| Communication Connections and Plugins       | `../../api/domains/communications/`                                                                                                                                                                          |
| Runtime resources                           | `../../api/domains/agents/builders/`                                                                                                                                                                         |
| Memory viewing, curation, and sharing       | `../../api/domains/agents/memory_sharing.py`                                                                                                                                                                |
| Memory groups (shared pools) domain         | `../../api/domains/memory_groups/`                                                                                                                                                                          |
| Pool workspace naming and delete-safety     | `../../api/infrastructure/honcho/client.py`                                                                                                                                                                 |
| Integration and skill artifacts             | `../../api/domains/agents/aai_cli_artifacts.py`, `../../api/domains/agents/aai_cli_skills/bundled/skills/`, `../../api/domains/agents/gog_artifacts.py`                                                      |
| UI contracts and hooks                      | `../../ui/src/features/agents/schemas.ts`, `../../ui/src/features/agents/hooks/`                                                                                                                             |
| UI components                               | `../../ui/src/features/agents/components/`                                                                                                                                                                   |
| Model inheritance and Organization defaults | `../../api/domains/agent_settings/`, [`agent-settings.md`](agent-settings.md)                                                                                                                                |
| Integration coverage                        | `../../api/tests/integration/test_agents.py`, `../../api/tests/integration/test_agent_rbac.py`, `../../api/tests/integration/test_agent_general_access.py`, `../../api/tests/integration/test_agent_logs.py` |

## Related decisions

- [`2026-07-21-separate-organization-and-agent-access-roles.md`](../adr/2026-07-21-separate-organization-and-agent-access-roles.md)
- [`2026-07-21-additive-agent-general-access.md`](../adr/2026-07-21-additive-agent-general-access.md)
- [`2026-08-09-agent-scoped-template-overrides.md`](../adr/2026-08-09-agent-scoped-template-overrides.md)
- [`2026-08-19-organization-scoped-agent-settings.md`](../adr/2026-08-19-organization-scoped-agent-settings.md)
- [`2026-08-22-agent-barn-owned-communications-gateway.md`](../adr/2026-08-22-agent-barn-owned-communications-gateway.md)
- [`2026-09-21-shared-memory-pools-via-groups.md`](../adr/2026-09-21-shared-memory-pools-via-groups.md) (supersedes [`2026-09-03-honcho-backed-agent-memory.md`](../adr/2026-09-03-honcho-backed-agent-memory.md))
- [`2026-09-10-restore-points-use-tar-jobs-not-csi-snapshots.md`](../adr/2026-09-10-restore-points-use-tar-jobs-not-csi-snapshots.md)

## Change impact

Lifecycle, visibility, Agent Access Role, explicit Agent Access assignment, or Agent General Access changes affect Agent API contracts, authorization predicates, Membership deletion behavior, UI schemas and controls, and Agent integration tests. Runtime changes additionally affect both runtime builders, Kubernetes cleanup, logs/health, and the runtime-neutral Communications protocol. Template/Skill changes require checking creation, repinning, update validation, and integration tests. Platform changes belong to the Communications domain and must not introduce Agent lifecycle or runtime-builder branches.
