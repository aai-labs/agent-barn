# Permission-backed RBAC — change log

Status: Active  
Feature: Permission-backed RBAC and assigned Agent access
Related context: [implementation brief](IMPLEMENTATION-BRIEF.md), [role decision](../../adr/2026-07-18-permission-backed-organization-roles.md), [Agent Access decision](../../adr/2026-07-18-assigned-agent-access-boundary.md)

## Current state

- Delivered: accepted RBAC domain language and decisions; deterministic Permission and system Role catalogue; scoped role grants; Membership role foreign keys; Agent creator provenance; same-Organization Agent Access constraints; legacy role and Agent Access backfill; request-time permission resolution with explicit Organization context, superuser bypass, default deny, and repository-facing authorization scopes.
- In transition: current APIs still expose Owner/Admin/Member compatibility values and existing service authorization primarily uses role checks. New Agent creation does not establish creator access until the Agent authorization slice adds the required transaction boundary. Assigned-only query enforcement and access-management APIs are not yet active.
- Next: replace service role checks with the centralized permission policy and enforce assigned-Agent visibility and creation assignment.
- Blockers: the audit logging feature must be available before RBAC security mutations are wired to durable audit events.

## Changes

### 2026-07-18 — centralized permission policy

- Delivered: request-time database-backed Permission lookup, active-Organization validation, explicit superuser bypass, allow-only/default-deny enforcement, and typed ORGANIZATION/ASSIGNED authorization scopes for repository queries.
- Changed: authorization grants can now be resolved without role-name checks or JWT claims; role and permission changes take effect on the next request.
- Follow-up: migrate organization and resource services to the policy, then apply ASSIGNED scope in Agent aggregate queries.

### 2026-07-18 — schema foundation

- Delivered: database-backed Permissions, immutable system Roles, scoped Role-Permission grants, Membership role migration, nullable Agent creator provenance, and Agent Access persistence.
- Changed: existing enum Membership roles are backfilled to stable Role IDs; existing Memberships receive access to every legacy Agent in their Organization; startup validates and repairs missing immutable catalogue rows.
- Follow-up: replace compatibility role checks with permission evaluation, atomically assign creators on new Agents, scope Agent aggregate queries, add grant/revoke workflows, and update the UI.
