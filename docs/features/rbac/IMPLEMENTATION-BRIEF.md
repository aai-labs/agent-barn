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

1. **Platform authority** — superuser may act through explicit Organization context.
2. **Organization authority** — each Membership has exactly one fixed Organization Role: Owner, Admin, or Member.
3. **Agent authority** — Organization Owner/Admin have implicit Agent Owner authority; an accepted Organization Member may receive additive authority from explicit Agent Access, Agent General Access, or both.

Permissions are allow-only and missing capabilities deny by default. Organization authorization resolves the Membership's current persisted Organization Role against an immutable code-owned Permission mapping. Agent authorization resolves current database-backed explicit Agent Access, Agent General Access, and Agent Access Role grants. Grants are not embedded in tokens.

### Organization Roles

| Role | Authority |
| --- | --- |
| Organization Owner | Unique recovery authority; all normal Organization operations plus deletion, ownership transfer, and control of Admin Memberships. |
| Organization Admin | Normal Organization and Membership administration, but no Owner recovery operations or control of other Admins. |
| Organization Member | May create Agents and use shared Templates and Skills, but cannot administer the Organization or shared definitions. |

These roles are a closed enum persisted directly on Membership. They cannot be created, edited, renamed, or deleted, and their immutable Permission mapping is defined with the authorization policy in code. Organization Role permissions govern Organization capabilities; they do not grant operations on assigned Agents.

### Agent Access Roles

Every Organization can use these locked defaults:

| Role | Permissions |
| --- | --- |
| Agent Viewer | Read Agent metadata, conversations, tool calls, activity, logs, and Agent-specific costs. |
| Agent Editor | Viewer capabilities plus configuration, lifecycle, Skill assignment, and Agent Secret management. |
| Agent Owner | Editor capabilities plus Agent deletion and access management. |

AF-216 adds Organization-defined custom Agent Access Roles using the same Agent Permission catalogue. AF-150 seeds only the locked defaults and implements role-bearing assignments.

An Agent operation is allowed when the actor has the corresponding Permission through implicit Agent Owner authority, explicit Agent Access, or Agent General Access, and the Agent lifecycle permits the operation. Start and stop use one `agent.lifecycle.manage` Permission; current Agent state selects the valid transition. Agent role names are not authorization checks.

## Agent Access

An Agent remains owned by its Organization. Agent Creator is immutable provenance; authority comes from implicit Organization governance or explicit Agent Access.

- Organization Owner/Admin and superuser in explicit Organization context have implicit Agent Owner authority over every Agent in that Organization. No bulk Agent Access rows are required.
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

Visibility belongs in repository queries rather than post-fetch filtering. Member list, search, count, and detail queries must constrain by Organization, soft-deletion state, and either explicit Agent Access or applicable Agent General Access before ordering, totals, or pagination. Organization Owner/Admin and explicit superuser context use implicit Organization-wide visibility.

Subordinate repositories must join or use an accessible-Agent query so alternate endpoints cannot reveal conversations, tool calls, costs, logs, Skills, configuration, or credential metadata.

HTTP semantics remain deliberate:

- Return `404` when an Agent or subordinate resource is absent, cross-Organization, or inaccessible and therefore concealed.
- Return `403` when the resource is visible but the actor lacks the requested operation.
- Use `400` or `409` for invalid state transitions and conflicting mutations.

Repositories own tenant and visibility query composition. Services own Permission-sensitive policy and orchestration. Routes remain thin.

## Backend and UI contract

Agent read responses communicate the operations permitted for the current actor and Agent. The UI uses that server result for lifecycle, configuration, credential, activity, cost, and deletion controls rather than inferring authority from either role family. Every backend mutation independently reauthorizes the current Membership, Agent Access state, and Agent lifecycle.

AF-150 UI is limited to permission-aware Agent controls, fixed Organization Role protections, inaccessible-Agent handling, and Member read-only Template/Skill surfaces. Agent assignment lists, access grant/change/revoke controls, assigned-role display, and custom Agent Access Role settings belong to AF-217.

AF-150 backend supports listing explicit assignments and locked roles, granting a selected locked role, changing an assignment's role, and revoking an assignment. AF-231 backend supports `GET`, `PUT`, and `DELETE` on `/agents/{agent_id}/general-access`, all gated by `agent.access.manage`; only roles available to the Agent's Organization and granting `agent.read` may be selected. Custom Agent Access Role create/edit/delete belongs to AF-216.

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

Test superuser, Organization Owner/Admin, creator, explicit Agent Owner/Editor/Viewer, Agent General Access Viewer/Editor/Owner, explicit-plus-General Permission union, unassigned Member, pending/removed Membership, wrong Organization, soft-deleted Agent, and migrated legacy data across list/count/detail/mutation and subordinate-resource paths.

Verify fresh and pre-AF-150 migration paths, Organization Role policy coverage, Agent Access Role seed idempotency, constraints, 404/403 behavior, direct mutation authorization, persistence-level pagination, and UI control differences. Run the required targets from [`../../guidelines/testing.md`](../../guidelines/testing.md) and keep [`CHANGELOG.md`](CHANGELOG.md) synchronized with every delivered slice.
