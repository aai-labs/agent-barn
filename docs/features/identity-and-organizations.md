# Identity and Organizations

## Read when

Read before changing login, token refresh, password/invite flows, current-user context, organization selection, roles, membership, global user administration, or tenant isolation.

## Role in the system

Authentication establishes a user and membership context; Organization is the tenancy boundary used by services and the UI to scope product data. Platform administration and organization administration have separate authority rules.

## Authorization invariants

- Organization Roles are the fixed `OWNER`, `ADMIN`, and `MEMBER` enum values persisted directly on Membership; current APIs expose those stable names.
- A user has at most one membership per organization, and the database permits at most one owner membership per organization. Normal creation and transfer flows establish an owner, but global user deletion can leave an organization without one.
- Ordinary Organization and Membership capabilities resolve the Membership's current Organization Role through the immutable code-owned Permission mapping. Organization deletion, ownership transfer, and sensitive Admin changes remain protected Organization Owner governance invariants.
- Organization Roles do not grant per-Agent operations to Members. Organization Owner/Admin have implicit Agent Owner authority; Organization Members receive Agent authority through explicit Agent Access Roles.
- Organization-scoped routes carry the active organization in the URL. A route without an `organization_id` path parameter has no active Organization.
- Org-scoped routes require real membership in the selected organization, including for Platform Administrators. Platform Administrator authority is reserved for platform routes.
- Cross-organization resource access is intentionally hidden with 404 for tenant-owned entities; known but unauthorized organization administration uses 403.
- Agent Farm has no default Organization. Platform-owned resources are global Platform Resources, not Organization-owned rows. Any organization with active agents must remove them before deletion.
- Platform routes accept Platform Administrator authority only from an authenticated user session. API-key, service, runtime, and other non-user-session credential classes are denied even when they identify a Platform Administrator.
- Platform Administrators can list users and organizations, provision pending users with an initial Organization, resend pending-user invitations, and grant or revoke Platform Privilege. Platform password reset, account deletion, and platform-level Organization creation/deletion are not supported.
- Platform Privilege changes require a 1–1000 character reason, reject no-op changes, prohibit self-revocation, and cannot remove the final Platform Administrator. The user-state change and Platform-scoped Domain Event commit atomically.

## Authentication flows

Access tokens are signed JWTs. Refresh tokens are opaque persisted values tied to the user's security stamp. Login returns both and writes the refresh token cookie. Refresh accepts the request token or cookie, validates persistence/expiry/stamp, revokes the used token, and rotates the pair.

Password change/reset updates the security stamp so existing refresh tokens fail later validation. Logout clears the browser cookie but does not revoke a separately held persisted refresh token.

Self-registration is disabled. Accounts enter through Platform Administrator provisioning or organization invitation. Platform provisioning atomically creates a pending User, their initial Organization, their Owner Membership, and a one-time set-password token; the invitation email is sent only after commit. The Platform Administrator never chooses or learns the user's password. Reset/invite tokens are stored as hashes, expire, and are marked used after successful enrollment/reset. Resending an invitation rotates the token so prior links stop working.

## Organization creation and membership flows

Any authenticated user, including a Platform Administrator, creates an Organization through `POST /organizations` using only a name and optional description. The server records that user as the immutable Organization Creator, creates their Owner Membership in the same transaction, and applies the platform default model configuration. The configurable per-creator limit defaults to five non-deleted Organizations; Platform Privilege does not bypass it. A Platform-provisioned user's initial Organization follows the same creator and default-model rules and counts toward that limit.

Organization Name is a mutable display label and is intentionally not globally unique. Platform View disambiguates same-named Organizations with owner identity and Organization ID; the planned Organization detail surface will also expose immutable Creator identity. A separate globally unique human-facing handle is deferred until a URL, CLI, API, or support workflow requires one.

Legacy Organizations backfill Organization Creator from their current Owner Membership. A genuinely ownerless legacy Organization retains an unknown creator instead of inventing provenance.

Membership list, invite, role-update, and removal workflows require their corresponding Organization Permissions through real membership; seeded Owner/Admin roles receive them. Owner-only rules protect ownership and sensitive Admin operations. Removing a pending Member also revokes outstanding invite/reset links.

The UI resolves Organization View from `/dashboard/[orgId]`; Platform View lives at `/dashboard/platform` and has no active Organization. The Organization selector is always membership-derived—even for Platform Administrators—and exposes self-service creation to every authenticated user. Platform-wide Organization results are never injected into the selector. Remembered organization state is only a navigation fallback for returning to Organization View. Organization-scoped hooks include the organization ID in API URLs. Organization switching removes known organization-scoped query caches because those keys are not organization-dimensioned.

## Source map

| Concern                               | Authoritative source                                                                                                                                                                                                                                                                                  |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Auth storage and current-user context | `../../api/domains/auth/models.py`                                                                                                                                                                                                                                                                          |
| Token and enrollment workflows        | `../../api/domains/auth/service.py`, `../../api/domains/auth/routes.py`                                                                                                                                                                                                                                           |
| Bearer and active-org resolution      | `../../api/domains/auth/utils.py`                                                                                                                                                                                                                                                                           |
| Platform Administrator authority      | `../../api/domains/platform_admin/service.py`                                                                                                                                                                                                                                                                |
| Platform user onboarding, listing, and privilege administration | `../../api/domains/users/service.py`, `../../api/domains/users/repository.py`, `../../api/domains/users/routes.py` |
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
- [`2026-07-30-platform-oversight-without-organization-access.md`](../adr/2026-07-30-platform-oversight-without-organization-access.md)
- [`2026-07-30-explicit-platform-and-organization-event-scopes.md`](../adr/2026-07-30-explicit-platform-and-organization-event-scopes.md)

## Change impact

Authorization changes require tenant-isolation, membership, Platform Administrator, and organization tests. Token changes affect API routes, auth interceptors, cookies, security-stamp behavior, and Playwright login/session mocks. New organization-scoped UI query families must participate in safe cache isolation or include organization identity in their keys.
