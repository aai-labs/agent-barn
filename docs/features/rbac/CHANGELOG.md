# Permission-backed RBAC — change log

Status: Active  
Feature: Permission-backed RBAC and Agent Access Roles
Related context: [implementation brief](IMPLEMENTATION-BRIEF.md), [current role decision](../../adr/2026-07-21-separate-organization-and-agent-access-roles.md)

## Current state

- Delivered on the branch: fixed Organization Role and Permission persistence; locked Agent Viewer/Editor/Owner persistence and grants; role-bearing Agent Access; legacy Member-to-Editor migration; creator Owner assignment; request-time Organization and Agent authorization; Organization/Membership/Template/Skill/cost enforcement; and staged permission-aware UI work.
- In transition: backend access-management contracts still need explicit role selection and role changes, aggregate authorization requires final matrix hardening, and staged access-management UI must move to AF-217.
- Next: complete role-bearing Agent access operations, harden the full Agent aggregate, and reduce the UI to AF-150 scope.
- Blockers: none. Custom Agent Access Role backend management is deferred to AF-216, Agent sharing and role-management UI to AF-217, and event/audit infrastructure to AF-218 through AF-221.

## Changes

### 2026-07-21 — AF-150 — Agent Access Role schema and authorization foundation

- Delivered: separate fixed Organization Role and Agent Access Role persistence, locked Viewer/Editor/Owner grants, required role-bearing Agent Access, implicit Organization Owner/Admin authority, and explicit creator Owner assignment.
- Changed: Organization Role grants no longer carry resource scope or Agent-operation permissions; Agent visibility and permitted operations resolve from implicit Owner authority or explicit Agent Access Role permissions.
- Migrated: existing accepted Organization Members receive Editor on existing Agents, pending Members receive none, Organization Owner/Admin remain implicit, and legacy creator provenance remains unknown where unrecoverable.
- Verified: API lint/type checks; 17 migration/schema tests; 45 focused schema, policy, authorization, and Agent RBAC tests; full API suite reached 832 passing with three unrelated email-delivery failures in `test_auth_flow_extended.py`.
- Follow-up: add selected-role grant/change contracts and complete aggregate security hardening.

### 2026-07-21 — AF-150 — Agent Access Role contract correction

- Decided: fixed Organization Owner/Admin/Member roles remain the Organization-governance model; per-Agent authority moves to locked Viewer, Editor, and Owner Agent Access Roles.
- Changed: Organization Owner/Admin receive implicit Agent Owner authority, creators receive explicit Agent Owner, existing accepted Members migrate to Editor on existing Agents, and new Agents are creator-only.
- Scope: AF-150 delivers locked role persistence, role-bearing assignments, backend list/grant/change/revoke, aggregate enforcement, and permission-aware product surfaces. AF-216 owns custom Agent Access Role backend management; AF-217 owns access and role-management UI.
- Follow-up: supersede the previous ADRs, rewrite the unreleased migration, refactor authorization and access contracts, remove deferred UI, and rerun the complete security matrix.

Entries below record implementation slices produced before this correction. They are historical branch state, not the current authorization contract.

### 2026-07-20 — AF-150 — pending PR — RBAC-aware UI

- Delivered: typed effective Agent actions, action-gated lifecycle/configuration/access controls, Agent Access assigned/eligible member management, immediate grant/revoke cache refresh, Member read-only Template/Skill surfaces, and protected Admin member-management controls.
- Changed: the browser consumes server-computed Agent actions instead of inferring resource authority from Organization Role names; role and ownership changes invalidate current-user and Agent authorization caches; organization switching removes Agent Access queries through the existing Agent key family.
- Verified: focused RBAC, Agent detail, Template, and Skill Playwright coverage; UI type checking and linting.
- Follow-up: complete the final cross-domain authorization and migration hardening task.

### 2026-07-20 — AF-150 — pending PR — organization-wide Permission enforcement

- Delivered: `ORGANIZATION`-scoped Permission checks for Organization read/update, Membership list/invite/role-update/remove, Template read/manage, Skill read/manage, and organization cost summaries; protected Owner governance rules remain explicit role invariants and superuser governance actions require matching explicit Organization context.
- Changed: Members retain shared Template/Skill read and Agent-use access without shared-definition mutation; cost summaries now require `cost.read` at `ORGANIZATION` scope rather than a route-level Owner/Admin role gate; authorization tests can temporarily alter persisted grants without leaking catalogue mutations between tests.
- Follow-up: consume effective actions and access-management contracts in the RBAC-aware UI; adopt durable events later under AF-218.

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
