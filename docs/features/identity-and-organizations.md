# Identity and Organizations

## Read when

Read before changing login, token refresh, password/invite flows, current-user context, organization selection, roles, membership, global user administration, or tenant isolation.

## Role in the system

Authentication establishes a user and membership context; Organization is the tenancy boundary used by services and the UI to scope product data. Platform administration and organization administration have separate authority rules.

## Authorization invariants

- Organization Roles are the fixed `OWNER`, `ADMIN`, and `MEMBER` enum values persisted directly on Membership; current APIs expose those stable names.
- A user has at most one membership per organization, and the database permits at most one owner membership per organization. Normal creation and transfer flows establish an owner, but global user deletion can leave an organization without one.
- Ordinary Organization and Membership capabilities resolve the Membership's current Organization Role through the immutable code-owned Permission mapping. Organization deletion, ownership transfer, and sensitive Admin changes remain protected Organization Owner/Platform Administrator governance invariants.
- Organization Roles do not grant per-Agent operations to Members. Organization Owner/Admin have implicit Agent Owner authority; Organization Members receive Agent authority through explicit Agent Access Roles.
- Organization-scoped routes carry the active organization in the URL. A route without an `organization_id` path parameter has no active Organization.
- Org-scoped routes require real membership in the selected organization, including for Platform Administrators. Platform Administrator authority is reserved for platform routes.
- Cross-organization resource access is intentionally hidden with 404 for tenant-owned entities; known but unauthorized organization administration uses 403.
- Agent Farm has no default Organization. Platform-owned resources are global Platform Resources, not Organization-owned rows. Any organization with active agents must remove them before deletion.
- Global user list/create/reset/delete operations require Platform Administrator authority.

## Authentication flows

Access tokens are signed JWTs. Refresh tokens are opaque persisted values tied to the user's security stamp. Login returns both and writes the refresh token cookie. Refresh accepts the request token or cookie, validates persistence/expiry/stamp, revokes the used token, and rotates the pair.

Password change/reset updates the security stamp so existing refresh tokens fail later validation. Logout clears the browser cookie but does not revoke a separately held persisted refresh token.

Self-registration is disabled. Accounts enter through Platform Administrator provisioning or organization invitation. Reset/invite tokens are stored as hashes, expire, and are marked used after successful enrollment/reset.

## Organization and membership flows

Platform Administrators create organizations and establish an Owner Membership through platform routes. Membership list, invite, role-update, and removal workflows require their corresponding Organization Permissions through real membership; seeded Owner/Admin roles receive them. Owner-only rules protect ownership and sensitive Admin operations. Removing a pending Member also revokes outstanding invite/reset links.

The UI resolves Organization View from `/dashboard/[orgId]`; Platform View lives at `/dashboard/platform` and has no active Organization. Remembered organization state is only a navigation fallback for returning to Organization View. Organization-scoped hooks include the organization ID in API URLs. Organization switching removes known organization-scoped query caches because those keys are not organization-dimensioned.

## Source map

| Concern                               | Authoritative source                                                                                                                                                                                                                                                                                  |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Auth storage and current-user context | `../../api/domains/auth/models.py`                                                                                                                                                                                                                                                                          |
| Token and enrollment workflows        | `../../api/domains/auth/service.py`, `../../api/domains/auth/routes.py`                                                                                                                                                                                                                                           |
| Bearer and active-org resolution      | `../../api/domains/auth/utils.py`                                                                                                                                                                                                                                                                           |
| Platform Administrator authority      | `../../api/domains/platform_admin/service.py`                                                                                                                                                                                                                                                                |
| User administration                   | `../../api/domains/users/service.py`, `../../api/domains/users/routes.py`                                                                                                                                                                                                                                         |
| Organization policy                   | `../../api/domains/organizations/service.py`                                                                                                                                                                                                                                                                |
| Membership roles and constraints      | `../../api/domains/users/organization_users/models.py`                                                                                                                                                                                                                                                      |
| Organization Role and Permission policy | `../../api/domains/rbac/catalog.py`, `../../api/domains/rbac/policy.py`                                                                                                                                                    |
| Agent Permission and Access Role persistence | `../../api/domains/rbac/models.py`, `../../api/domains/rbac/repository.py`, `../../api/domains/rbac/seeder.py` |
| Membership workflows                  | `../../api/domains/users/organization_users/service.py`                                                                                                                                                                                                                                                     |
| UI user gate                          | `../../ui/src/auth/providers/user-context-provider.tsx`                                                                                                                                                                                                                                                     |
| UI organization context               | `../../ui/src/features/organizations/providers/organization-provider.tsx`                                                                                                                                                                                                                                   |
| Isolation and auth tests              | `../../api/tests/integration/test_cross_org_isolation.py`, `../../api/tests/integration/test_tenant_resolution.py`, `../../api/tests/integration/test_auth.py`, `../../api/tests/integration/test_auth_flow_extended.py`, `../../api/tests/integration/test_organizations.py`, `../../api/tests/integration/test_organization_members.py` |

## Related decisions

- [`2026-07-17-explicit-organization-context.md`](../adr/2026-07-17-explicit-organization-context.md)
- [`2026-07-21-separate-organization-and-agent-access-roles.md`](../adr/2026-07-21-separate-organization-and-agent-access-roles.md)

## Change impact

Authorization changes require tenant-isolation, membership, Platform Administrator, and organization tests. Token changes affect API routes, auth interceptors, cookies, security-stamp behavior, and Playwright login/session mocks. New organization-scoped UI query families must participate in safe cache isolation or include organization identity in their keys.
