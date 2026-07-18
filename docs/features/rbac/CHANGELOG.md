# Permission-backed RBAC — change log

Status: Active  
Feature: Permission-backed RBAC and assigned Agent access
Related context: [implementation brief](IMPLEMENTATION-BRIEF.md), [role decision](../../adr/2026-07-18-permission-backed-organization-roles.md), [Agent Access decision](../../adr/2026-07-18-assigned-agent-access-boundary.md)

## Current state

- Delivered: accepted RBAC domain language and decisions; deterministic Permission and system Role catalogue; scoped role grants; Membership role foreign keys; Agent creator provenance; same-Organization Agent Access constraints; legacy role and Agent Access backfill.
- In transition: current APIs still expose Owner/Admin/Member compatibility values and existing role-based authorization behavior. New Agent creation does not establish creator access until the Agent authorization slice adds the required transaction boundary. Assigned-only query enforcement and access-management APIs are not yet active.
- Next: centralize permission evaluation and request-scoped authorization, then enforce assigned-Agent visibility and creation assignment.
- Blockers: the audit logging feature must be available before RBAC security mutations are wired to durable audit events.

## Changes

### 2026-07-18 — schema foundation

- Delivered: database-backed Permissions, immutable system Roles, scoped Role-Permission grants, Membership role migration, nullable Agent creator provenance, and Agent Access persistence.
- Changed: existing enum Membership roles are backfilled to stable Role IDs; existing Memberships receive access to every legacy Agent in their Organization; startup validates and repairs missing immutable catalogue rows.
- Follow-up: replace compatibility role checks with permission evaluation, atomically assign creators on new Agents, scope Agent aggregate queries, add grant/revoke workflows, and update the UI.
