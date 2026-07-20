# Permission-backed RBAC — change log

Status: Active  
Feature: Permission-backed RBAC and assigned Agent access
Related context: [implementation brief](IMPLEMENTATION-BRIEF.md), [role decision](../../adr/2026-07-18-permission-backed-organization-roles.md), [Agent Access decision](../../adr/2026-07-18-assigned-agent-access-boundary.md)

## Current state

- Delivered: accepted RBAC language and decisions; deterministic Permission/system Role catalogue; scoped grants; Membership role foreign keys; legacy backfill; request-time permission resolution; atomic creator assignment; assigned Agent lifecycle/list/detail enforcement; canonical effective Permission actions; scoped conversation, tool-call, log, integration-validation, and per-Agent cost reads; and Agent Access list/grant/revoke APIs.
- In transition: APIs still expose Owner/Admin/Member compatibility values, organization-wide shared-resource services still use compatibility role gates, and RBAC-aware UI controls are not yet active.
- Next: apply the permission matrix to organization-wide resources, then update the UI.
- Blockers: none. Durable Domain Events and Security Audit Records are deferred to [AF-218](https://aai-labs.atlassian.net/browse/AF-218) and do not block AF-150.

## Changes

### 2026-07-20 — AF-150 — pending PR — Agent Access management API

- Delivered: authorized assigned/eligible Member lists, idempotent grants, deterministic revocation, creator-only Member sharing, recipient non-propagation, pending/cross-organization rejection, and Membership-deletion cascade coverage.
- Changed: user-facing access contracts identify recipients by User ID while persistence remains Membership-scoped; access changes affect visibility and effective actions on the next request.
- Follow-up: consume these contracts in the RBAC-aware UI and add durable access events later under AF-218.

### 2026-07-20 — AF-150 event and audit scope split

- Delivered: AF-150 remains focused on permission-backed authorization, Agent Access management, organization-wide policy, and RBAC-aware UI behavior.
- Changed: Domain Event, transactional outbox, Dramatiq/Redis delivery, and Security Audit Record work moved to [AF-218](https://aai-labs.atlassian.net/browse/AF-218) and its child tickets AF-219 through AF-221.
- Follow-up: implement grant/revoke workflows without temporary audit coupling; adopt durable events after the event epic lands.

### 2026-07-18 — assigned Agent authorization boundary

- Delivered: Agent creator/access transaction; SQL-scoped Agent list/count/detail queries; server-computed effective actions using canonical Permission keys; action-specific lifecycle, secret/configuration, activity, and cost checks; and subordinate conversation/tool-call repository scoping.
- Changed: Members see and act only on assigned active Agents, unassigned/cross-organization resources return 404, visible resources missing an action return 403, and organization-scoped managers retain deleted-Agent cost history.
- Follow-up: deliver access-management APIs, replace remaining organization-wide role gates, and consume effective actions in the UI.

### 2026-07-18 — centralized permission policy

- Delivered: request-time database-backed Permission lookup, active-Organization validation, explicit superuser bypass, allow-only/default-deny enforcement, and typed ORGANIZATION/ASSIGNED authorization scopes for repository queries.
- Changed: authorization grants can now be resolved without role-name checks or JWT claims; role and permission changes take effect on the next request.
- Follow-up: migrate organization and resource services to the policy, then apply ASSIGNED scope in Agent aggregate queries.

### 2026-07-18 — schema foundation

- Delivered: database-backed Permissions, immutable system Roles, scoped Role-Permission grants, Membership role migration, nullable Agent creator provenance, and Agent Access persistence.
- Changed: existing enum Membership roles are backfilled to stable Role IDs; existing accepted Memberships receive access to every legacy Agent in their Organization while pending invitees do not; startup validates and repairs missing immutable catalogue rows.
- Follow-up: replace compatibility role checks with permission evaluation, atomically assign creators on new Agents, scope Agent aggregate queries, add grant/revoke workflows, and update the UI.
