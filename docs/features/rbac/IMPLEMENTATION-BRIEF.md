# Permission-backed RBAC and Agent Access Roles

Status: Implemented by AF-150; extended by AF-231
Source: [AF-150](https://aai-labs.atlassian.net/browse/AF-150), [AF-231](https://aai-labs.atlassian.net/browse/AF-231)

## Purpose

Read this brief before changing Organization authorization, Agent visibility or operations, Agent Access Role seeding, Agent General Access, or RBAC migrations. It records the delivered contract; [`CHANGELOG.md`](CHANGELOG.md) retains the implementation history.

Related context:

- [`../../../CONTEXT.md`](../../../CONTEXT.md) defines canonical terms.
- [`../../adr/2026-07-21-separate-organization-and-agent-access-roles.md`](../../adr/2026-07-21-separate-organization-and-agent-access-roles.md) explains the role-family decision.
- [`../../adr/2026-07-21-additive-agent-general-access.md`](../../adr/2026-07-21-additive-agent-general-access.md) explains the Agent General Access persistence decision.
- [`../identity-and-organizations.md`](../identity-and-organizations.md) defines Organization governance.
- [`../agents.md`](../agents.md) defines the Agent aggregate.
- [`../../guidelines/code.md`](../../guidelines/code.md), [`../../guidelines/webapp.md`](../../guidelines/webapp.md), [`../../guidelines/testing.md`](../../guidelines/testing.md), and [`../../guidelines/epics.md`](../../guidelines/epics.md) govern implementation and verification.

## Authorization model

Authorization combines three independent sources:

1. **Platform authority** — a Platform Administrator may act through platform routes only.
2. **Organization authority** — each Membership has exactly one fixed Organization Role: Owner, Admin, or Member.
3. **Agent authority** — Organization Owner/Admin have implicit Agent Owner authority; an accepted Organization Member may receive additive authority from explicit Agent Access, Agent General Access, or both.

Permissions are allow-only and missing capabilities deny by default. Organization authorization resolves the Membership's current persisted Organization Role against an immutable code-owned Permission mapping. Agent authorization resolves current database-backed explicit Agent Access, Agent General Access, and Agent Access Role grants. Grants are not embedded in tokens.

### Platform Agent Memory settings

See [Agent Memory](../agent-memory.md#platform-memory-processing-model) for the
Platform Admin settings and separate backend-service credential contract.
Organization roles confer no authority on these Platform routes.

The Platform Playbook Extraction model (`/platform/settings/playbooks`) follows the
same rule; see [Playbooks](../playbooks.md#model-and-billing).

### Organization Roles

| Role                | Authority                                                                                                                          |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Organization Owner  | Unique recovery authority; all normal Organization operations plus deletion, ownership transfer, and control of Admin Memberships. |
| Organization Admin  | Normal Organization and Membership administration, but no Owner recovery operations or control of other Admins.                    |
| Organization Member | May create Agents and use shared Templates and Skills, but cannot administer the Organization or shared definitions.               |

These roles are a closed enum persisted directly on Membership. They cannot be created, edited, renamed, or deleted, and their immutable Permission mapping is defined with the authorization policy in code. Organization Role permissions govern Organization capabilities; they do not grant operations on assigned Agents.

### Agent Access Roles

Every Organization can use these locked defaults:

| Role         | Permissions                                                                                       |
| ------------ | ------------------------------------------------------------------------------------------------- |
| Agent Viewer | Read Agent metadata, conversations, tool calls, activity, logs, and Agent-specific costs.         |
| Agent Editor | Viewer capabilities plus configuration, lifecycle, Skill assignment, and Agent Secret management. |
| Agent Owner  | Editor capabilities plus Agent deletion, access management, and Agent Memory management.          |

AF-216 adds Organization-defined custom Agent Access Roles using the same Agent Permission catalogue. AF-150 seeds only the locked defaults and implements role-bearing assignments.

An Agent operation is allowed when the actor has the corresponding Permission through implicit Agent Owner authority, explicit Agent Access, or Agent General Access, and the Agent lifecycle permits the operation. Start and stop use one `agent.lifecycle.manage` Permission; current Agent state selects the valid transition. Capturing, restoring, and deleting an Agent Restore Point reuse that same Permission, because each is a lifecycle operation on a stopped Agent; reading restore points uses `activity.read`, alongside conversations, tool calls, logs, health, and container CPU and memory (Resource usage). The Agents overview lists the Agents the caller can read and judges each figure per Agent: spend needs `cost.read` on that Agent and usage needs `activity.read`, and a withheld figure is null while the row stays. No restore-point-specific Permission exists — an Agent Editor who may stop an Agent and repin its template may also roll its volume back, and gating restore behind Agent Owner would let an Editor break an Agent without being able to fix it. Agent role names are not authorization checks.

Choosing an Agent's [Agent Size](../agent-sizes.md#organization-choice) uses the Organization Permission `agent.size.manage`, held only by Organization Owners and Admins; no Agent Access Role carries it, so an Agent's creator or explicit Agent Owner who is a Member cannot choose, since a bigger size spends the Organization's shared capacity. Restarting an Agent whose size is pending applies it, and needs only `agent.lifecycle.manage`: a start applies the size already chosen, so it is not a size decision. The size route still resolves the Agent through `AgentAuthorization.require_action` first (`404` when concealed, `403` when visible without the grant) and then checks the Organization grant; `allowed_actions` lists it for Owners and Admins. Which sizes may be chosen is the Platform Administrator's, per Organization, and reading that list needs only `organization.read`. A Platform Administrator may also set one Agent's size through `PUT /platform/agents/{agent_id}/agent-size`, and restart any Agent (or start one that is not running) through `POST /platform/agents/{agent_id}/restart` (both `require_platform_admin`, no Membership): the only platform writes on an Organization's Agent, limited to these two by [their ADR](../../adr/2026-10-22-platform-administrators-set-an-agents-size.md). While that override stands, the Organization's size route answers `409` to Owners and Admins alike; `allowed_actions` still lists `agent.size.manage`, and `AgentRead.agent_size_set_by_platform` tells the UI to show the size locked.

Agent Memory adds `agent.memory.manage` to the locked Agent Owner role, allowing the creator through their explicit access and Organization Owners/Admins through implicit Agent Owner authority to toggle memory. Editors and Viewers do not receive it. The separate Organization Permission `memory.access.manage` is held only by Organization Owners and Admins; it governs listing, creating, and revoking Memory Grants and viewing shared Organization Memory across that Organization. Owning an Agent does not confer this Organization capability. See [`Agent Memory`](../agent-memory.md) for grant semantics and API contracts.

## Agent Access

An Agent remains owned by its Organization. Agent Creator is immutable provenance; authority comes from implicit Organization governance or explicit Agent Access.

- Organization Owner/Admin have implicit Agent Owner authority over every Agent in that Organization. No bulk Agent Access rows are required.
- Creating an Agent atomically records creator provenance and grants the creator explicit Agent Owner access, including when the creator is currently Organization Owner/Admin.
- An Organization Member without explicit Agent Access or applicable Agent General Access cannot see the Agent or any subordinate resource.
- One Membership has at most one explicit Agent Access Role per Agent.
- Agent General Access is one Agent-scoped setting: Restricted (`NULL`) or All Organization Members with one Agent Access Role. New and migrated Agents default to Restricted.
- Agent General Access applies dynamically to current and future accepted Organization Members. Pending and removed Memberships receive nothing from it.
- Explicit Agent Access and Agent General Access are positive grants whose Permission sets are unioned. Neither source subtracts from the other; removing one source leaves any Permissions from the other intact.
- A role containing access-management Permission may list, grant, change, and revoke explicit assignments, and read, set, change, or remove Agent General Access, including granting Agent Owner onward or through Agent General Access.
- Creator provenance does not create a separate sharing rule or permanent authorization exception.
- Explicit Agent Access targets must be accepted Memberships in the same Organization. Pending, removed, and cross-Organization Memberships are ineligible.
- Implicit Organization Owner/Admin authority is not an explicit assignment and cannot be revoked through Agent Access operations.
- Assignment, Agent General Access, Membership, and Agent Access Role Permission changes take effect on the next request.

Explicit Agent Access and Agent General Access scope the complete Agent aggregate: lifecycle, configuration, conversations, tool calls, activity, costs, logs, Skills, Agent Secrets, and platform/integration configuration. Secret plaintext is never returned.

## Data-access enforcement

The Organization read's `trial_agent_limit_reached` boolean is creation-capacity
metadata for members who may create Agents. It accounts for every non-deleted Agent,
including ones hidden from that member, without exposing identities or an unfiltered
Agent count. See [Hiring choices](../agents.md#hiring-choices) for its UI contract.

Visibility belongs in repository queries rather than post-fetch filtering. Member list, search, count, and detail queries must constrain by Organization, soft-deletion state, and either explicit Agent Access or applicable Agent General Access before ordering, totals, or pagination. Organization Owner/Admin use implicit Organization-wide visibility.

Subordinate repositories must join or use an accessible-Agent query so alternate endpoints cannot reveal conversations, tool calls, costs, logs, Skills, configuration, or credential metadata.

Agent-authenticated gateway traffic has no user Membership. The memory gateway instead resolves the hash of a per-start Agent credential to one undeleted, running, memory-enabled Agent and its existing Organization, then reads only that Agent's same-Organization Memory Grants. Client bank names and tags cannot choose a different tenant or identity. Organization Memory grants permit either read only or read and write; both add a strict `scope:team` scope to recall, and other-Agent grants add exact private scopes only. Shared authorship grants no private read access. The Agent Memory tab requires human `activity.read` and includes Organization records only with the viewed Agent's current Organization grant; revocation hides its own shared contributions too. The explicit writer endpoint requires a live write grant. User-facing memory settings and grants retain the Organization and Agent Permission checks above. See [`Agent Memory`](../agent-memory.md#use-the-memory-gateway) for the machine-request contract.

Agent file sync traffic from the pod has no user Membership either.
- **Authentication:** `/ingest/v1/agents/{agent_id}/file-sync/…` authenticates the Agent in the path by its per-start ingest key. A wrong key is refused before anything about the Agent is revealed.
- **Tenant:** the Organization, connection and Agent Folder come only from that Agent's persisted rows. No request value can name another Agent, folder or Organization.
- **Paths:** they are checked against the Agent's own runtime's sync rules.
- **Not background work:** these methods are reachable from an Ingest router, so the background-work exception below does not cover them. See [Activity and Ingest](../activity-and-ingest.md).
- **Turning File Sync off or on** is a user request, not background work: `PUT …/agents/{agent_id}/file-sync` requires `agent.update` through `AgentAuthorization.require_action`, and `AgentFileSyncRepository` changes only that Agent and its own folder, inside the caller's Organization. It is a separate repository from the Sync Engine's `FileSyncRepository`, so the exception below keeps covering only engine work ([Sync providers](../sync-provider/README.md#turning-sync-off)).
- **Reading an Agent's File Sync status and history** (`GET …/agents/{agent_id}/file-sync` and `…/file-sync/activity`) requires `activity.read`. `AgentFileSyncRepository.status_inputs` reads the Agent through `agent_scope_predicates` and then only that Agent's Organization's active connection and that Agent's own folder ([Sync providers](../sync-provider/README.md#status)). `activity_page` joins `sync_activity` to the Agent under the same predicates before counting, ordering and paging.
- **Accepted gap at the provider:** the "Agent Barn" folder is open to every Organization Member, so Members without Agent Access to an Agent can read its synced files and edit its work and memory files there. Agent Access is not mirrored into provider permissions ([ADR](../../adr/2026-10-21-agent-file-sync-through-sync-provider.md), [Agent file sync](../sync-provider/README.md#known-limits-of-file-sync)).

Agent artifact runtime traffic (`/api/v1/agent-artifacts/runtime`) also has no human Membership.
A purpose-separated credential derived from the per-start Agent secret resolves one
undeleted, running Agent and its Organization. Runtime callers cannot choose another
owner, bucket or key. Workflow publication additionally fences the supplied attempt ID
against that owning Agent, current generation/state/deadline and initiating Membership
authority. Completion credentials never enter model prompts or file-tool arguments.
The entire owning Agent is the runtime trust boundary: all of its sessions share
that identity and may publish into its current workflow attempts. Attempt IDs are
non-secret provenance, not per-session capabilities; this is not session isolation.
Human artifact reads require current `agent.read` and scoped visibility; publication
and deletion require `agent.update`.
The app-facing `/api/v1/agent-artifacts/{organization_id}/{agent_id}/{artifact_id}`
byte route instead uses the opaque provider-signed bearer authority issued after
those checks. Its repository read still joins the exact persisted Organization,
Agent and artifact; the private byte store then validates the capability against
that canonical object before any file bytes/metadata are returned. It is neither
an unscoped metadata endpoint nor the background-work exception. No user cookie or
runtime credential substitutes for provider validation. Existing issued authority
survives issuer-session/Membership revocation until provider expiry (subject to
file/owner deletion); new issuance uses current permissions. See
[Agent artifacts](../agent-artifacts.md).

Playbook Extractions read one Agent's transcripts and write an Organization Skill, so they need Agent `activity.read` on the source Agent and Organization `skill.manage`; in practice Owners and Admins. Publishing the resulting Skill makes content derived from that Agent visible to every Member through `skill.read`; the reviewing Owner or Admin is the control. The worker runs a person's request, not background work: when a run starts it re-checks that the requesting Membership still holds both Permissions on the undeleted source Agent. See [`Playbooks`](../playbooks.md#authorization).

Agent Barn Telegram traffic has no user Membership either. Two callers reach it: Telegram, through the shared bot the Communications process polls, and Agent pods, through the Bot API proxy. Neither carries a session, so there is no Active Organization to scope against. The tenant comes from persisted rows instead, and no caller-supplied value can choose it.

- **Proxy calls** are authenticated by the Connection in the path and a stand-in token derived from that Connection's own secret. The Connection resolves its Agent and Organization, which set the per-Organization rate limit. A chat-scoped call reaches Telegram only when every chat it names is a Telegram user with an active link to that Connection, and the Member who issued the link still holds `agent.update` on the Agent. That Member is checked on every call, so a scheduled send stops on the next call after an Agent Access, Agent General Access, Membership, or role change, as a request would; losing the Permission ends the link. Every message and file id the call names must also belong to that Connection, so an Agent cannot act on what a user exchanged with an Agent they were linked to before.
- **Telegram-driven reads and writes** run in the poller: linking, queuing updates for an Agent, ending links, and recording which Connection owns a message or file. A link is created only by spending a single-use token that a Member with `agent.update` issued through an authorized route, and it records that Membership. The poller's link writes stage Domain Events (`telegram.account.linked`, and `telegram.account.unlinked` for a link it replaces) in the same transaction, with that recorded Membership as the actor and the link's own Organization as the scope; no caller-supplied value chooses either. Before an update is queued, and again before it is delivered, the link's Membership is checked for `agent.update` on the Agent with `AgentAuthorization.membership_has_permission`, which resolves the Membership exactly as a signed-in request does. Losing it ends the link and drops the update. A button press or edit on a message the current Connection does not own is not delivered.

These paths are not the background work described below: product users trigger them, so they keep explicit authority checks against the linking Membership rather than running unscoped.

Background work is the one exception, and it is narrow. It covers scheduled work, Jobs the chart runs on every deploy, and operator-run one-shot commands. A CronJob, a deploy-run Job, or an operator's `kubectl exec` has no `CurrentUserContext` and therefore no Active Organization to scope against. So `ToolCallService.platform_daily_active_agent_ids`, the restore point reconciler's repository methods, the Communications maintenance scan's `CommunicationConnectionRepository.list_enabled_email_page`, the Business Action backfill's `BusinessActionRepository.find_backfill_batch` and `apply_classified`, and the Sync Engine's `FileSyncRepository` reads and writes run unscoped. The Sync Engine's methods take the Organization and connection from persisted connection rows, never from a caller. The exception holds only while all three of these do:

- the method is never reachable from a router
- the request paths over the same table keep their `AgentAuthorization` checks unchanged
- the work is driven by a schedule, a deploy, or an operator with cluster access, never by anything a product user can trigger

One bounded case: turning an Agent's File Sync back on (an authorized `agent.update` request) leaves a request, `sync_agent_folder.resync_requested_at`, on that Agent's own folder. The Sync Engine reads it on its next scheduled pass and re-lists the whole connection, as it already does when the provider expires the change cursor. The request chooses only *when* that re-list happens, never what it may touch: the re-list keys by the connection's own persisted rows, and changes any folder or file only by the same rules as every other pass. So the user's input reaches the engine as a timing hint, and the exception still holds.

A background method that acquires a user-facing caller stops qualifying and needs the accessible-Agent join like any other.

The operator-only Agent Memory purge worker uses this background exception to consume
durable deletion tombstones. It derives the bank and document namespace from persisted
Agent/Organization IDs, refuses live or mismatched targets, and exposes no router.
Only the authorized Agent deletion transaction stages new tombstones. See
[Deletion cleanup](../agent-memory.md#deletion-cleanup).

The artifact purge's `ArtifactRepository.cleanup_candidates` and `purge_target`
methods use the same narrow operator-only background exception. They expose no router
and only inspect persisted ownership, references, deadlines and canonical tenant keys.
They preserve failed deletion records across owner deletion and refuse mismatched
bucket/key targets with recorded retry backoff. Product paths retain their scoped Agent
joins. Agent creation commits its server-generated storage request atomically with
the authorized Agent/access/events transaction. `ArtifactBucketRepository.reserve`
is invoked only after current `agent.update` authorization from the explicit
Provision action, using the scoped Agent and current Organization. Status reads
require current `agent.read` visibility. Neither endpoint accepts bucket/key IDs.
`due` and `operation` use the operator exception from artifact maintenance for
persisted provisioning requests and deleted owners. There is no Agent-discovery
scan or separate privileged workload. API background provisioning and artifact
maintenance receive Garage administrative authority; Agent runtimes and other
workloads never do. Maintenance validates Organization/Agent/bucket identity and
retains data keys until all bytes have been purged. Product paths retain current
human/runtime checks. See
[Artifact retention and recovery](../agent-artifacts.md#retention-deletion-and-recovery).

HTTP semantics remain deliberate:

- Return `404` when an Agent or subordinate resource is absent, cross-Organization, or inaccessible and therefore concealed.
- Return `403` when the resource is visible but the actor lacks the requested operation.
- Use `400` or `409` for invalid state transitions and conflicting mutations.

Repositories own tenant and visibility query composition. Services own Permission-sensitive policy and orchestration. Routes remain thin.

## Backend and UI contract

Agent read responses communicate the operations permitted for the current actor and Agent. The UI uses that server result for lifecycle, configuration, credential, activity, cost, and deletion controls rather than inferring authority from either role family. Every backend mutation independently reauthorizes the current Membership, Agent Access state, and Agent lifecycle.

AF-150 UI is limited to permission-aware Agent controls, fixed Organization Role protections, inaccessible-Agent handling, and Member read-only Template/Skill surfaces. Agent assignment lists, access grant/change/revoke controls, assigned-role display, and custom Agent Access Role settings belong to AF-217.

AF-150 backend supports listing explicit assignments and locked roles, granting a selected locked role, changing an assignment's role, and revoking an assignment. AF-231 exposes those collaboration workflows through the share-oriented contract: `GET /agents/share-roles`, `GET /agents/{agent_id}/share`, and full-snapshot `PUT /agents/{agent_id}/share` for atomic UI saves of Agent General Access and the complete explicit assignment list. All share-management endpoints are gated by `agent.access.manage`; only roles available to the Agent's Organization and granting `agent.read` may be selected for Agent General Access. Reusable Member search is provided by `GET /organizations/{organization_id}/members?search=...`, not an Agent-specific eligible-recipient endpoint, so clients can reconcile search results against in-progress local share edits. Custom Agent Access Role create/edit/delete belongs to AF-216.

## Shared Organization resources

Organization Members may read and use Templates and Skills when creating or configuring an Agent but may not create, update, version, publish, or delete shared definitions. Organization Owner/Admin may manage those resources. Organization-wide cost and activity summaries remain Organization-authorized; Agent Viewer/Editor/Owner permissions authorize only the corresponding Agent aggregate.

## Persistence and migration

The target model contains:

- exactly one fixed Organization Role enum value persisted directly on each Membership;
- an immutable code-owned Organization Role Permission mapping;
- a global immutable Permission catalogue used by database-backed Agent Access Roles;
- locked Agent Viewer, Editor, and Owner roles with Agent Permission mappings;
- immutable, nullable-for-legacy Agent creator provenance;
- nullable Agent General Access role reference on Agent, where `NULL` means Restricted;
- unique same-Organization Agent Access relating Membership, Agent, and one Agent Access Role.

Because the AF-150 migration is unreleased, it should install the target model directly rather than first installing the superseded binary-access model.

Migration requirements:

1. Preserve the existing fixed Organization Role enum and Membership role values without translation.
2. Seed Permissions and locked Agent Access Roles deterministically and idempotently.
3. Preserve existing Agent visibility by granting every existing accepted Organization Member Agent Editor access to every existing Agent in the same Organization; pending and removed Memberships receive none.
4. Grant Agent Owner only when creator provenance is reliable. The pre-AF-150 schema stored no creator ID, Agent assignment, or audit event, so its existing Agents have no recoverable known creator and remain `NULL`; no heuristic Owner grant is made.
5. Keep Organization Owner/Admin Agent authority implicit rather than materializing bulk assignments.
6. Enforce Agent role-family validity, same-Organization relationships, uniqueness, deletion behavior, and repeatable startup validation.
7. Cover fresh installs and upgrades from the pre-AF-150 schema with migrated PostgreSQL integration tests.

New Agents grant explicit Agent Owner access only to their creator and default Agent General Access to Restricted. AF-231 adds a follow-up migration that installs `agent.general_access_role_id` as a nullable foreign key to `agent_access_roles.id` with `ON DELETE RESTRICT`, an index, and a database trigger mirroring explicit Agent Access role-scope validation: system roles are valid for any Agent, while custom roles must belong to the same Organization as the Agent. Application validation performs the same availability check and additionally rejects roles that do not grant `agent.read`.

## Deferred scope

AF-150 does not deliver:

- custom Agent Access Role CRUD, owned by AF-216;
- custom Agent Access Role edit-time guards beyond the AF-231 write-time `agent.read` selection check; referenced role deletion must surface the database `RESTRICT` constraint as a conflict, and Permission edits take effect on the next request;
- Agent sharing or Agent Access Role management UI, owned by AF-217;
- custom Organization Roles;
- multiple additive Organization Roles per Membership;
- explicit deny rules;
- authorization grants in JWT claims;
- Domain Events, transactional outbox, workers, or Security Audit Records, owned by AF-218 through AF-221.

AF-150 workflows must retain clean transaction seams for later event adoption without introducing temporary audit infrastructure.

## Verification expectations

Test Platform Administrator, Organization Owner/Admin, creator, explicit Agent Owner/Editor/Viewer, Agent General Access Viewer/Editor/Owner, explicit-plus-General Permission union, unassigned Member, pending/removed Membership, wrong Organization, soft-deleted Agent, and migrated legacy data across list/count/detail/mutation and subordinate-resource paths.

Verify fresh and pre-AF-150 migration paths, Organization Role policy coverage, Agent Access Role seed idempotency, constraints, 404/403 behavior, direct mutation authorization, persistence-level pagination, and UI control differences. Run the required targets from [`../../guidelines/testing.md`](../../guidelines/testing.md) and keep [`CHANGELOG.md`](CHANGELOG.md) synchronized with every delivered slice.

## Personal API Key access

Personal API Keys use the owning User's current Organization Membership and Agent Access grants. The shared auth dependency enforces read-only key mode for mutations, and Agent allowed-action responses omit write actions for read-only keys. Full-access keys do not bypass Agent visibility, Organization membership, or Permission checks. Platform routes use current Platform Administrator privilege independently of Organization access.
