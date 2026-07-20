# Permission-backed RBAC implementation brief

Status: Accepted design; backend enforcement delivered, UI adoption pending
Source proposal: [Agent farm multi-organization support](https://aai-labs.atlassian.net/wiki/x/MIA0pQ)

## Purpose

This brief preserves the implementation-relevant decisions for permission-backed RBAC without reproducing the design conversation. It is the handoff context for agents implementing database-backed RBAC and assigned Agent access.

Read this together with:

- [`../../../CONTEXT.md`](../../../CONTEXT.md) for canonical terminology.
- [`../../adr/2026-07-18-permission-backed-organization-roles.md`](../../adr/2026-07-18-permission-backed-organization-roles.md) for role-model rationale.
- [`../../adr/2026-07-18-assigned-agent-access-boundary.md`](../../adr/2026-07-18-assigned-agent-access-boundary.md) for resource-access rationale.
- [`../identity-and-organizations.md`](../identity-and-organizations.md) and [`../agents.md`](../agents.md) for current behavior.
- [`../../guidelines/code.md`](../../guidelines/code.md), [`../../guidelines/webapp.md`](../../guidelines/webapp.md), [`../../guidelines/testing.md`](../../guidelines/testing.md), and [`../../guidelines/epics.md`](../../guidelines/epics.md) before implementation.

Implementation is in transition. Membership references database-backed seeded Roles; scoped Role-Permission grants, Agent creator provenance, and same-Organization Agent Access are persisted and legacy data is backfilled. Agent creation establishes creator access atomically; Agent aggregate paths enforce permission and assigned visibility; Agent Access management APIs are delivered; and Organization, Membership, Template, Skill, and cost-summary services enforce named Permissions. RBAC-aware UI controls are not yet delivered. Follow `CHANGELOG.md` rather than treating the full accepted design as complete.

## Authorization model

Authorization combines three independent facts:

1. **Platform authority** — a superuser may act across Organizations through explicit Organization context.
2. **Capability** — a Membership's Organization Role grants a named Permission.
3. **Resource scope** — the role-permission grant applies to every matching resource in the Organization or only assigned Agent aggregates.

Permissions are allow-only. Missing permission means deny; there are no explicit deny rules. Authorization grants are resolved server-side for each request and are not embedded in access tokens, so role and access revocation takes effect on the next request.

### Roles

Every Membership has exactly one Organization Role.

| Authority | Scope and responsibilities |
| --- | --- |
| Superuser | Platform-wide authority rather than an Organization Role. Uses explicit Organization context and bypasses organization permission checks. |
| Owner | Unique recovery role. Has all organization permissions and alone may delete the Organization, transfer ownership, or promote, demote, and remove Admins. |
| Admin | Manages normal organization operations, Memberships, and all organization resources, but cannot perform Owner recovery actions or control other Admins. |
| Member | May create Agents and see or act only on assigned Agents. Cannot administer the Organization or shared organization definitions. |

Permissions and the immutable Owner, Admin, and Member system roles are global records. Future custom roles belong to one Organization, but custom-role APIs, permission editing, and role-editor UI are outside the initial RBAC feature. Organizations must never mutate seeded roles; a future custom role may be cloned from one.

### Permission scope

A role-permission mapping carries scope rather than encoding scope into the permission name:

- `ORGANIZATION` means all matching resources inside the active Organization, never cross-tenant.
- `ASSIGNED` means only Agent aggregates connected to the current Membership through Agent Access.

For example, Admin may receive `agent.update` at `ORGANIZATION` scope while Member receives the same action at `ASSIGNED` scope. Permissions that do not support assignment use organization scope.

## Agent Access

An Agent remains owned by its Organization. Creation is provenance and assignment, not ownership.

- Agent Creator is immutable historical provenance.
- Agent Access relates one Membership to one Agent and makes that Agent assigned to the Membership.
- Creating an Agent atomically creates access for its creator, including an Owner/Admin creator so a later demotion preserves access to Agents they created.
- A superuser acting without a Membership needs no Agent Access row.
- Owner/Admin may grant or revoke access to any Agent in the Organization.
- A Member may grant or revoke access only for an Agent they originally created.
- A recipient cannot forward access merely because they can manage the Agent.
- A creator cannot revoke their own access in the initial Agent Access feature.
- Access can be granted only to an accepted ordinary Member in the same Organization; pending invitees cannot be pre-granted access.
- Agent transfer, relinquishment, and viewer/operator/manager grant levels are out of scope.
- Creator and recipient otherwise receive the same assigned-Agent capabilities allowed by their Organization Role.

Agent Access scopes the entire Agent aggregate:

- Agent lifecycle and configuration
- conversations and tool calls
- Agent-specific activity and cost data
- assigned Skills
- Slack/Teams and other Agent configuration
- Agent Secrets and integrations
- logs and related runtime-facing control-plane data

Aggregate scope does not automatically permit every operation. The Membership still needs the relevant Permission. Agent Secret plaintext is never returned; only safe provider and masked metadata may be read.

## Data-access enforcement

Visibility must be part of repository queries, not post-fetch filtering.

For Member list, search, and count operations, SQL must constrain by Organization, soft-deletion state, and an Agent Access `EXISTS` predicate before ordering, totals, or pagination. Owner/Admin organization-scoped permissions do not require one access row per Agent.

Single-resource reads must use an accessible-resource query rather than loading an unrestricted row and authorizing afterward. Subordinate repositories must join or use an accessible-Agent subquery so conversations, tool calls, costs, secrets, logs, and configuration cannot bypass Agent visibility through alternate endpoints.

HTTP semantics remain deliberate:

- Return `404` when an Agent or subordinate resource is cross-organization or unassigned and therefore concealed.
- Return `403` when the resource is visible but the actor lacks the requested action Permission.
- Use `400` or `409` for invalid state transitions and conflicting mutations.

Repositories own tenant/resource query composition. Services own permission-sensitive policy and orchestration. Routes remain thin.

## API and UI contract

Agent read/list DTOs expose server-computed effective actions as canonical Agent-related `PermissionKey` values for the current actor and resource. This deliberately reuses the Permission catalogue rather than maintaining a second action vocabulary; the UI must validate the typed subset it consumes.

The UI uses effective actions to render edit, delete, start, stop, configuration, secret, and access-management controls. It must not reconstruct authorization from role names. Hidden or disabled controls are usability only: every mutation re-resolves authorization and Agent state on the server.

After grant, revoke, or role changes, invalidate affected Agent lists/details, effective-action data, access lists, current-user context, and organization-scoped caches. Organization switching must retain the existing safe cache-isolation behavior.

## Shared organization resources

The seeded Member policy is:

- May view and use organization Templates and Skills when creating or configuring assigned Agents.
- May not create, update, version, publish, or delete shared Template or Skill definitions.
- May view conversations, tool calls, activity, and cost summaries only for assigned Agents.
- May not view organization-wide costs, activity, or Membership administration.
- May add, replace, or remove masked Agent credentials only when their assigned-Agent permissions allow it.

Owner/Admin may manage shared organization resources. Superuser access uses explicit Organization context.

## Deferred events and auditing

AF-150 does not introduce event infrastructure or security audit persistence. Durable internal Domain Events are tracked by [AF-218](https://aai-labs.atlassian.net/browse/AF-218), with the transactional outbox foundation in [AF-219](https://aai-labs.atlassian.net/browse/AF-219), Dramatiq/Redis delivery in [AF-220](https://aai-labs.atlassian.net/browse/AF-220), and Security Audit Records in [AF-221](https://aai-labs.atlassian.net/browse/AF-221).

AF-150 grant/revoke, role-change, and credential workflows must preserve the transaction seams and safe changed-field information needed for later event adoption, but they do not emit or persist audit events in this epic.

## Persistence and migration shape

The intended model contains:

- `permissions` — global immutable capability catalogue.
- `roles` — global immutable system roles and future Organization-scoped custom roles.
- `role_permissions` — role-to-permission grants carrying `ORGANIZATION` or `ASSIGNED` scope.
- Membership role foreign key — replaces enum persistence while keeping exactly one role per Membership.
- Agent creator reference — immutable provenance, nullable for legacy/system cases according to user-deletion policy.
- `agent_access` — unique same-Organization relationship between Membership and Agent.

Migration requirements:

1. Seed permissions and system roles deterministically and idempotently.
2. Backfill existing Membership enums to the corresponding seeded roles without changing authority.
3. Existing Agents have no recoverable creator. Mark creator provenance unknown/legacy.
4. Preserve current access by granting every existing accepted Membership access to every existing Agent in the same Organization. Pending invitees receive no backfilled access. Use reviewed bulk SQL suitable for real data volume.
5. Enforce uniqueness, same-Organization validity, deletion behavior, PostgreSQL enum ordering, and repeatable startup seeding.
6. Cover fresh installs and upgrades from the pre-RBAC schema with migrated PostgreSQL integration tests.

## Explicit non-goals

The initial RBAC feature does not deliver:

- organization-defined custom-role CRUD or UI
- mutation of seeded roles or the Permission catalogue
- multiple additive roles per Membership
- explicit deny rules
- Agent transfer or creator relinquishment
- multiple Agent Access levels
- authorization grants in JWT claims
- Domain Event, transactional outbox, worker, or Security Audit Record infrastructure; these belong to AF-218

## Remaining implementation choices

The design leaves these details to implementation, provided they preserve the decisions above:

- canonical Permission key names and the complete seeded action matrix
- exact effective-action DTO evolution beyond the initial canonical Permission-key list
- creator-reference behavior when a User is permanently deleted, coordinated with the product's retention and privacy policy

Material deviations from the accepted model require updating the ADRs, this brief, tests, and the RBAC change log together.

## Verification expectations

At minimum, test superuser, Owner, Admin, creator Member, recipient Member, unassigned Member, removed/pending Membership, wrong Organization, soft-deleted Agent, and migrated legacy data across list/count/detail/mutation and subordinate-resource paths.

Run the relevant repository targets from `docs/guidelines/testing.md`: `make check-api`, `make test-api`, `make lint-ui`, `make check-ui`, and `make test-ui`. Add focused migration, tenant-isolation, service, repository, and Playwright coverage. Use `docs/features/rbac/CHANGELOG.md` for every delivered PR slice as required by `docs/guidelines/epics.md`.
