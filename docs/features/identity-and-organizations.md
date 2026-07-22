# Identity and Organizations

## Read when

Read before changing login, token refresh, password/invite flows, current-user context, organization selection, roles, membership, global user administration, or tenant isolation.

## Role in the system

Authentication establishes a user and membership context; Organization is the tenancy boundary used by services and the UI to scope product data. Global user administration and organization administration have separate authority rules.

## Authorization invariants

- Organization roles are `OWNER`, `ADMIN`, and `MEMBER`.
- A user has at most one membership per organization, and the database permits at most one owner membership per organization. Normal creation and transfer flows establish an owner, but global user deletion can leave an organization without one.
- Owner and admin are organization managers. Organization deletion, ownership transfer, and sensitive admin changes require owner or superuser authority.
- `X-Organization-Id` selects the active organization; an absent header falls back to the process default organization.
- Normal users require membership in the selected organization. Superusers can target organizations without persisted membership through explicit context behavior.
- Cross-organization resource access is intentionally hidden with 404 for tenant-owned entities; known but unauthorized organization administration uses 403.
- The default organization cannot be deleted, and an organization with active agents must remove them before deletion.
- Global user list/create/reset/delete operations require superuser authority.

## Authentication flows

Access tokens are signed JWTs. Refresh tokens are opaque persisted values tied to the user's security stamp. Login returns both and writes the refresh token cookie. Refresh accepts the request token or cookie, validates persistence/expiry/stamp, revokes the used token, and rotates the pair.

Password change/reset updates the security stamp so existing refresh tokens fail later validation. Logout clears the browser cookie but does not revoke a separately held persisted refresh token.

Self-registration is disabled. Accounts enter through superuser provisioning or organization invitation. Reset/invite tokens are stored as hashes, expire, and are marked used after successful enrollment/reset.

## Organization and membership flows

Superusers create organizations and establish an owner membership. Organization managers can administer ordinary membership; owner-only rules protect ownership and sensitive admin operations. Removing a pending member also revokes outstanding invite/reset links.

The UI resolves the selected organization from the route, then remembered/default state, and applies the organization header before protected child queries run. Organization switching removes known organization-scoped query caches because those keys are not organization-dimensioned.

## Source map

| Concern                               | Authoritative source                                                                                                                                                                                                                                                                                  |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Auth storage and current-user context | `../../api/domains/auth/models.py`                                                                                                                                                                                                                                                                          |
| Token and enrollment workflows        | `../../api/domains/auth/service.py`, `../../api/domains/auth/routes.py`                                                                                                                                                                                                                                           |
| Bearer and active-org resolution      | `../../api/domains/auth/utils.py`                                                                                                                                                                                                                                                                           |
| User administration                   | `../../api/domains/users/service.py`, `../../api/domains/users/routes.py`                                                                                                                                                                                                                                         |
| Organization policy                   | `../../api/domains/organizations/service.py`                                                                                                                                                                                                                                                                |
| Membership roles and constraints      | `../../api/domains/users/organization_users/models.py`                                                                                                                                                                                                                                                      |
| Membership workflows                  | `../../api/domains/users/organization_users/service.py`                                                                                                                                                                                                                                                     |
| UI user gate                          | `../../ui/src/auth/providers/user-context-provider.tsx`                                                                                                                                                                                                                                                     |
| UI organization context               | `../../ui/src/features/organizations/providers/organization-provider.tsx`                                                                                                                                                                                                                                   |
| Isolation and auth tests              | `../../api/tests/integration/test_cross_org_isolation.py`, `../../api/tests/integration/test_tenant_resolution.py`, `../../api/tests/integration/test_auth.py`, `../../api/tests/integration/test_auth_flow_extended.py`, `../../api/tests/integration/test_organizations.py`, `../../api/tests/integration/test_organization_members.py` |

## Related decisions

- [`2026-07-17-explicit-organization-context.md`](../adr/2026-07-17-explicit-organization-context.md)

## Change impact

Authorization changes require tenant-isolation, membership, superuser, and organization tests. Token changes affect API routes, auth interceptors, cookies, security-stamp behavior, and Playwright login/session mocks. New organization-scoped UI query families must participate in safe cache isolation or include organization identity in their keys.
