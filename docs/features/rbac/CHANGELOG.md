# Permission-backed RBAC — change log

Status: Active
Epic: [AF-144](https://aai-labs.atlassian.net/browse/AF-144)
Related context: [implementation brief](IMPLEMENTATION-BRIEF.md), [current role decision](../../adr/2026-07-21-separate-organization-and-agent-access-roles.md)

## Current state

- Delivered: fixed Organization Role enum persistence with code-owned Permission grants; locked Agent Viewer/Editor/Owner persistence and grants; role-bearing Agent Access; legacy Member-to-Editor migration; creator Owner assignment for new Agents; request-time Organization and Agent authorization; Organization/Membership/Template/Skill/cost enforcement; and permission-aware UI without sharing or role-management surfaces.
- In transition: none for the delivered AF-150 slice; the AF-144 epic remains active.
- Next: AF-216 adds custom Agent Access Role backend management; AF-217 adds Agent sharing and role-management UI; AF-218 through AF-221 add event/audit infrastructure.
- Blockers: none.

## Changes

### 2026-07-21 — [AF-150](https://aai-labs.atlassian.net/browse/AF-150) — PR pending — dead-code cleanup

- Delivered: removed obsolete Organization-only Agent lookups superseded by authorization-scoped queries, an unused assignment-ID query, unused Agent Access Role conversion helpers, and an unused batch Permission policy method.
- Changed: updated the sole legacy test caller to use the retained internal lookup; no product behavior or API contract changed.
- Verified: API lint/type checks and 28 focused policy, Agent RBAC, and legacy-row tests.
- Follow-up: none for this cleanup.

### 2026-07-21 — [AF-150](https://aai-labs.atlassian.net/browse/AF-150) — PR pending — review hardening

- Delivered: database-enforced immutability for the global Permission catalogue and locked system Agent Access Role grants, plus an explicit immutable Organization Role Permission mapping in code.
- Changed: removed the deferred `audit.read` Permission; recorded that the pre-AF-150 schema contains no reliable creator provenance and therefore receives no heuristic Owner grants; synchronized all authoritative documents to AF-150's completed state.
- Verified: 17 PostgreSQL migration/schema tests, 156 affected authorization integration tests, API lint/type checks, `git diff --check`, and relative Markdown links.
- Follow-up: introduce audit Permissions with AF-218 and replace `PR pending` references with the pull-request link when available.

### 2026-07-21 — [AF-150](https://aai-labs.atlassian.net/browse/AF-150) — PR pending — final hardening

- Verified: fresh and pre-AF-150 migration paths, accepted-Member Editor preservation, pending exclusion, explicitly unknown legacy creator provenance, atomic Owner assignment for new creators, constraints, seed idempotency, downgrade, and the superuser/implicit administrator/explicit Owner/Editor/Viewer/unassigned authorization matrix.
- Audited: Agent list/detail/count/pagination, lifecycle, configuration, Skills, conversations, tool calls, activity, costs, logs/health, integrations, credentials, direct mutations, Organization switching, and authorization-sensitive cache refresh.
- Checks: `make check-api`, focused API RBAC suites, `make lint-ui`, `make check-ui`, focused RBAC Playwright, full 162-test Playwright suite, `git diff --check`, and relative Markdown link validation pass. `make test-api` reports 835 passing tests, including the exact Organization Role Permission matrix, and only the three isolated password-reset email-mock failures noted above.
- Residual scope: custom Agent Access Role CRUD, sharing/role-management UI, and durable audit events remain intentionally deferred to their owning follow-up tickets.

### 2026-07-21 — [AF-150](https://aai-labs.atlassian.net/browse/AF-150) — PR pending — permission-aware product UI

- Delivered: server-permission-gated Agent lifecycle, configuration, credential, activity, cost, and deletion controls; direct-URL configuration protection; inaccessible-Agent handling; fixed Organization role management protections; and Member read-only Template/Skill surfaces.
- Deferred: Agent assignment lists, role display, sharing controls, and custom Agent Access Role settings remain outside AF-150 and belong to AF-217.
- Verified: UI lint and type checks; six focused RBAC Playwright tests across Viewer/Editor/Owner, inaccessible Agents, Organization role protections, and shared-resource read-only behavior; full Playwright suite with 162 passing tests.

### 2026-07-21 — [AF-150](https://aai-labs.atlassian.net/browse/AF-150) — PR pending — unified Agent lifecycle permission

- Changed: replaced separate `agent.start` and `agent.stop` grants with one `agent.lifecycle.manage` Permission in the unreleased schema, default Agent Access Roles, backend authorization, effective-action contract, and UI schema.
- Preserved: start and stop remain distinct lifecycle operations; current Agent state determines which transition the API and UI allow.

### 2026-07-21 — [AF-150](https://aai-labs.atlassian.net/browse/AF-150) — PR pending — role-bearing Agent access operations

- Delivered: available Agent Access Role listing; explicit assignment listing with role details; selected-role grant; assignment role change; and revocation.
- Changed: duplicate same-role grants remain idempotent, different-role duplicate grants require the role-change operation, explicit Agent Owners can share onward, and creator assignments follow the same change/revoke rules as other assignments.
- Preserved: Organization Owner/Admin and superuser authority remains implicit and absent from assignment rows; only accepted same-Organization Members can receive explicit assignments; authorization changes take effect on the next request.
- Verified: API checks and 20 focused Agent RBAC integration tests covering locked role grants, immediate role changes, explicit Owner sharing, creator revocation, invalid roles, pending/cross-Organization targets, concurrency, and implicit administration.
- Follow-up: remove AF-217 UI from the AF-150 diff and run final aggregate hardening.

### 2026-07-21 — [AF-150](https://aai-labs.atlassian.net/browse/AF-150) — PR pending — Agent Access Role schema and authorization foundation

- Delivered: separate fixed Organization Role enum and database-backed Agent Access Role persistence, locked Viewer/Editor/Owner grants, required role-bearing Agent Access, implicit Organization Owner/Admin authority, and explicit creator Owner assignment.
- Changed: Organization Role grants no longer carry resource scope or Agent-operation permissions; Agent visibility and permitted operations resolve from implicit Owner authority or explicit Agent Access Role permissions.
- Migrated: existing accepted Organization Members receive Editor on existing Agents, pending Members receive none, Organization Owner/Admin remain implicit, and legacy creator provenance remains unknown where unrecoverable.
- Verified: API lint/type checks; 17 migration/schema tests; 45 focused schema, policy, authorization, and Agent RBAC tests; full API suite reached 832 passing with three unrelated email-delivery failures in `test_auth_flow_extended.py`.
- Follow-up: add selected-role grant/change contracts and complete aggregate security hardening. Completed by the role-bearing Agent access operations slice above.

### 2026-07-21 — [AF-150](https://aai-labs.atlassian.net/browse/AF-150) — PR pending — Agent Access Role contract

- Delivered: fixed Organization Owner/Admin/Member governance and locked Viewer/Editor/Owner per-Agent authority.
- Applied: Organization Owner/Admin receive implicit Agent Owner authority, creators receive explicit Agent Owner, existing accepted Members migrate to Editor on existing Agents, and new Agents are creator-only.
- Scope: AF-150 delivers locked Agent Access Role persistence, role-bearing assignments, backend list/grant/change/revoke, aggregate enforcement, and permission-aware product surfaces. AF-216 owns custom Agent Access Role backend management; AF-217 owns access and role-management UI.

### 2026-07-20 — [AF-150](https://aai-labs.atlassian.net/browse/AF-150) — PR pending — RBAC-aware UI

- Delivered: typed effective Agent actions, action-gated lifecycle/configuration controls, inaccessible-Agent handling, Member read-only Template/Skill surfaces, and protected Admin member-management controls.
- Changed: the browser consumes server-computed Agent actions instead of inferring resource authority from Organization Role names; role and ownership changes invalidate current-user and Agent authorization caches; organization switching removes Agent Access queries through the existing Agent key family.
- Verified: focused RBAC, Agent detail, Template, and Skill Playwright coverage; UI type checking and linting.
- Follow-up: Agent sharing and Agent Access Role management UI belongs to AF-217.

### 2026-07-20 — [AF-150](https://aai-labs.atlassian.net/browse/AF-150) — PR pending — organization-wide Permission enforcement

- Delivered: `ORGANIZATION`-scoped Permission checks for Organization read/update, Membership list/invite/role-update/remove, Template read/manage, Skill read/manage, and organization cost summaries; protected Owner governance rules remain explicit role invariants and superuser governance actions require matching explicit Organization context.
- Changed: Members retain shared Template/Skill read and Agent-use access without shared-definition mutation; cost summaries require `cost.read` through Organization policy rather than a route-level Owner/Admin role gate; authorization tests can temporarily override the policy seam without mutating fixed grants.
- Follow-up: consume effective actions and access-management contracts in the RBAC-aware UI; adopt durable events later under AF-218.

### 2026-07-20 — [AF-150](https://aai-labs.atlassian.net/browse/AF-150) — PR pending — Agent Access management API

- Delivered: authorized assigned/eligible Member lists, idempotent grants, deterministic revocation, creator-only Member sharing, recipient non-propagation, pending/cross-organization rejection, and Membership-deletion cascade coverage.
- Changed: user-facing access contracts identify recipients by User ID while persistence remains Membership-scoped; access changes affect visibility and effective actions on the next request.
- Follow-up: consume these contracts in the RBAC-aware UI and add durable access events later under AF-218.

### 2026-07-20 — [AF-150](https://aai-labs.atlassian.net/browse/AF-150) — PR pending — event and audit scope split

- Delivered: AF-150 remains focused on permission-backed authorization, Agent Access management, organization-wide policy, and RBAC-aware UI behavior.
- Changed: Domain Event, transactional outbox, Dramatiq/Redis delivery, and Security Audit Record work moved to [AF-218](https://aai-labs.atlassian.net/browse/AF-218) and its child tickets AF-219 through AF-221.
- Follow-up: implement grant/revoke workflows without temporary audit coupling; adopt durable events after the event epic lands.

### 2026-07-18 — [AF-150](https://aai-labs.atlassian.net/browse/AF-150) — PR pending — assigned Agent authorization boundary

- Delivered: Agent creator/access transaction; SQL-scoped Agent list/count/detail queries; server-computed effective actions using canonical Permission keys; action-specific lifecycle, secret/configuration, activity, and cost checks; and subordinate conversation/tool-call repository scoping.
- Changed: Members see and act only on assigned active Agents, unassigned/cross-organization resources return 404, visible resources missing an action return 403, and organization-scoped managers retain deleted-Agent cost history.
- Follow-up: deliver access-management APIs, replace remaining organization-wide role gates, and consume effective actions in the UI.

### 2026-07-18 — [AF-150](https://aai-labs.atlassian.net/browse/AF-150) — PR pending — centralized permission policy

- Delivered: request-time fixed Organization Role Permission evaluation, active-Organization validation, explicit superuser bypass, allow-only/default-deny enforcement, and typed Organization/Agent authorization scopes for repository queries.
- Changed: authorization grants resolve without role-name checks or JWT claims; Membership role and Agent access changes take effect on the next request.
- Follow-up: migrate organization and resource services to the policy, then apply ASSIGNED scope in Agent aggregate queries.

### 2026-07-18 — [AF-150](https://aai-labs.atlassian.net/browse/AF-150) — PR pending — schema foundation

- Delivered: fixed Organization Role enum persistence, code-owned Organization Permission grants, an immutable Permission catalogue, database-backed Agent Access Roles and grants, nullable Agent creator provenance, and Agent Access persistence.
- Changed: existing Membership roles remain unchanged; existing accepted Members receive Editor access to every legacy Agent in their Organization while pending invitees do not; startup validates the Permission and locked Agent Access Role catalogues.
- Follow-up: replace compatibility role checks with permission evaluation, atomically assign creators on new Agents, scope Agent aggregate queries, add grant/revoke workflows, and update the UI.
