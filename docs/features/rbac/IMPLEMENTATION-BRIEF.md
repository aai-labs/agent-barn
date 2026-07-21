# Permission-backed RBAC and Agent Access Roles

Status: Accepted design; corrective AF-150 refactor in progress
Source: [AF-150](https://aai-labs.atlassian.net/browse/AF-150)

## Purpose

Read this brief before changing Organization authorization, Agent visibility or operations, Agent Access, role seeding, or the AF-150 migration. It records the target contract; [`CHANGELOG.md`](CHANGELOG.md) records which slices are currently delivered.

Related context:

- [`../../../CONTEXT.md`](../../../CONTEXT.md) defines canonical terms.
- [`../../adr/2026-07-21-separate-organization-and-agent-access-roles.md`](../../adr/2026-07-21-separate-organization-and-agent-access-roles.md) explains the role-family decision.
- [`../identity-and-organizations.md`](../identity-and-organizations.md) defines Organization governance.
- [`../agents.md`](../agents.md) defines the Agent aggregate.
- [`../../guidelines/code.md`](../../guidelines/code.md), [`../../guidelines/webapp.md`](../../guidelines/webapp.md), [`../../guidelines/testing.md`](../../guidelines/testing.md), and [`../../guidelines/epics.md`](../../guidelines/epics.md) govern implementation and verification.

## Authorization model

Authorization combines three independent sources:

1. **Platform authority** — superuser may act through explicit Organization context.
2. **Organization authority** — each Membership has exactly one fixed Organization Role: Owner, Admin, or Member.
3. **Agent authority** — Organization Owner/Admin have implicit Agent Owner authority; an Organization Member requires explicit Agent Access carrying one Agent Access Role.

Permissions are allow-only and missing capabilities deny by default. Grants are resolved from current database state on every request rather than embedded in tokens.

### Organization Roles

| Role | Authority |
| --- | --- |
| Organization Owner | Unique recovery authority; all normal Organization operations plus deletion, ownership transfer, and control of Admin Memberships. |
| Organization Admin | Normal Organization and Membership administration, but no Owner recovery operations or control of other Admins. |
| Organization Member | May create Agents and use shared Templates and Skills, but cannot administer the Organization or shared definitions. |

These roles are locked and cannot be created, edited, renamed, or deleted. Organization Role permissions govern Organization capabilities; they do not grant operations on assigned Agents.

### Agent Access Roles

Every Organization can use these locked defaults:

| Role | Permissions |
| --- | --- |
| Agent Viewer | Read Agent metadata, conversations, tool calls, activity, logs, and Agent-specific costs. |
| Agent Editor | Viewer capabilities plus configuration, lifecycle, Skill assignment, and Agent Secret management. |
| Agent Owner | Editor capabilities plus Agent deletion and access management. |

AF-216 adds Organization-defined custom Agent Access Roles using the same Agent Permission catalogue. AF-150 seeds only the locked defaults and implements role-bearing assignments.

An Agent operation is allowed when the actor has the corresponding Permission through the effective Agent Access Role and the Agent lifecycle permits the operation. Agent role names are not authorization checks.

## Agent Access

An Agent remains owned by its Organization. Agent Creator is immutable provenance; authority comes from implicit Organization governance or explicit Agent Access.

- Organization Owner/Admin and superuser in explicit Organization context have implicit Agent Owner authority over every Agent in that Organization. No bulk Agent Access rows are required.
- Creating an Agent atomically records creator provenance and grants the creator explicit Agent Owner access, including when the creator is currently Organization Owner/Admin.
- An Organization Member without explicit Agent Access cannot see the Agent or any subordinate resource.
- One Membership has at most one explicit Agent Access Role per Agent.
- A role containing access-management Permission may list, grant, change, and revoke explicit assignments, including granting Agent Owner onward.
- Creator provenance does not create a separate sharing rule or permanent authorization exception.
- Targets must be accepted Memberships in the same Organization. Pending, removed, and cross-Organization Memberships are ineligible.
- Implicit Organization Owner/Admin authority is not an explicit assignment and cannot be revoked through Agent Access operations.
- Assignment and role changes take effect on the next request.

Agent Access scopes the complete Agent aggregate: lifecycle, configuration, conversations, tool calls, activity, costs, logs, Skills, Agent Secrets, and platform/integration configuration. Secret plaintext is never returned.

## Data-access enforcement

Visibility belongs in repository queries rather than post-fetch filtering. Member list, search, count, and detail queries must constrain by Organization, soft-deletion state, and explicit Agent Access before ordering, totals, or pagination. Organization Owner/Admin and explicit superuser context use implicit Organization-wide visibility.

Subordinate repositories must join or use an accessible-Agent query so alternate endpoints cannot reveal conversations, tool calls, costs, logs, Skills, configuration, or credential metadata.

HTTP semantics remain deliberate:

- Return `404` when an Agent or subordinate resource is absent, cross-Organization, or inaccessible and therefore concealed.
- Return `403` when the resource is visible but the actor lacks the requested operation.
- Use `400` or `409` for invalid state transitions and conflicting mutations.

Repositories own tenant and visibility query composition. Services own Permission-sensitive policy and orchestration. Routes remain thin.

## Backend and UI contract

Agent read responses communicate the operations permitted for the current actor and Agent. The UI uses that server result for lifecycle, configuration, credential, activity, cost, and deletion controls rather than inferring authority from either role family. Every backend mutation independently reauthorizes current database state and Agent lifecycle.

AF-150 UI is limited to permission-aware Agent controls, fixed Organization Role protections, inaccessible-Agent handling, and Member read-only Template/Skill surfaces. Agent assignment lists, access grant/change/revoke controls, assigned-role display, and custom Agent Access Role settings belong to AF-217.

AF-150 backend supports listing explicit assignments and locked roles, granting a selected locked role, changing an assignment's role, and revoking an assignment. Custom Agent Access Role create/edit/delete belongs to AF-216.

## Shared Organization resources

Organization Members may read and use Templates and Skills when creating or configuring an Agent but may not create, update, version, publish, or delete shared definitions. Organization Owner/Admin may manage those resources. Organization-wide cost and activity summaries remain Organization-authorized; Agent Viewer/Editor/Owner permissions authorize only the corresponding Agent aggregate.

## Persistence and migration

The target model contains:

- a global immutable Permission catalogue;
- fixed database-backed Organization Roles and their Organization Permission mappings;
- locked Agent Viewer, Editor, and Owner roles with Agent Permission mappings;
- exactly one Organization Role reference per Membership;
- immutable, nullable-for-legacy Agent creator provenance;
- unique same-Organization Agent Access relating Membership, Agent, and one Agent Access Role.

Because the AF-150 migration is unreleased, it should install the target model directly rather than first installing the superseded binary-access model.

Migration requirements:

1. Seed Permissions and both locked role catalogues deterministically and idempotently.
2. Backfill Memberships to fixed Organization Roles without changing Organization authority.
3. Preserve existing Agent visibility by granting every existing accepted Organization Member Agent Editor access to every existing Agent in the same Organization; pending and removed Memberships receive none.
4. Grant Agent Owner to a recoverable known creator; legacy creator provenance may remain unknown.
5. Keep Organization Owner/Admin Agent authority implicit rather than materializing bulk assignments.
6. Enforce role-family validity, same-Organization relationships, uniqueness, deletion behavior, and repeatable startup validation.
7. Cover fresh installs and upgrades from the pre-AF-150 schema with migrated PostgreSQL integration tests.

New Agents grant explicit Agent Owner access only to their creator.

## Deferred scope

AF-150 does not deliver:

- custom Agent Access Role CRUD, owned by AF-216;
- Agent sharing or Agent Access Role management UI, owned by AF-217;
- custom Organization Roles;
- multiple additive Organization Roles per Membership;
- explicit deny rules;
- authorization grants in JWT claims;
- Domain Events, transactional outbox, workers, or Security Audit Records, owned by AF-218 through AF-221.

AF-150 workflows must retain clean transaction seams for later event adoption without introducing temporary audit infrastructure.

## Verification expectations

Test superuser, Organization Owner/Admin, creator, explicit Agent Owner/Editor/Viewer, unassigned Member, pending/removed Membership, wrong Organization, soft-deleted Agent, and migrated legacy data across list/count/detail/mutation and subordinate-resource paths.

Verify fresh and pre-AF-150 migration paths, seed idempotency, constraints, 404/403 behavior, direct mutation authorization, persistence-level pagination, and UI control differences. Run the required targets from [`../../guidelines/testing.md`](../../guidelines/testing.md) and keep [`CHANGELOG.md`](CHANGELOG.md) synchronized with every delivered slice.
