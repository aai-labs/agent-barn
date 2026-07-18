# Use permission-backed organization roles

Status: Accepted
Date: 2026-07-18
Origin: [Agent farm multi-organization support](https://aai-labs.atlassian.net/wiki/x/MIA0pQ)

Agent Farm will persist roles, permissions, and role-permission mappings while initially exposing only the seeded Owner, Admin, and Member organization roles. Services will authorize named permissions rather than role names; this adds schema and policy complexity now but avoids coupling every authorization site to a fixed enum when organization-defined roles are introduced later.

## Considered alternatives

- Keep the current role enum and hardcode role checks. This is simpler now but makes custom roles a cross-cutting code and schema change later.
- Deliver organization-defined roles immediately. This adds role lifecycle, validation, recovery, and UI scope beyond the initial RBAC feature.

## Consequences

Permissions and the immutable seeded Owner, Admin, and Member roles are global; future custom roles are scoped to one Organization. Each Membership references exactly one role valid for its Organization. Custom-role management is deferred from the initial RBAC feature.

Superuser remains platform-wide authority rather than an organization role. Resource assignment, including member access to individual Agents, is modeled separately from role permissions. A role-permission mapping carries an `ASSIGNED` or `ORGANIZATION` resource scope rather than encoding scope into the permission name; `ORGANIZATION` never crosses the active tenant boundary. Grants are allow-only and missing permissions deny by default; explicit deny rules are not supported. Tokens do not embed authorization grants; the server resolves current Membership, role, permissions, and Agent Access for each request so revocation takes effect immediately.
