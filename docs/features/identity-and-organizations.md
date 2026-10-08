# Identity and Organizations

## Read when

Read before changing login, Google sign-in, self-signup, token refresh, password/invite flows, current-user context, organization selection, roles, membership, global user administration, or tenant isolation.

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
- Agent Barn has no default Organization. Platform-owned resources are global Platform Resources, not Organization-owned rows. Any organization with active agents must remove them before deletion.
- Platform routes accept authority from an authenticated user session or a Personal API Key belonging to a current Platform Administrator. Service and runtime credentials remain excluded.
- Platform Administrators can list users and organizations, provision pending users with an initial Organization, resend pending-user invitations, and grant or revoke Platform Privilege. Platform password reset, account deletion, and platform-level Organization creation/deletion are not supported.
- Platform Privilege changes require a 1–1000 character reason, reject no-op changes, prohibit self-revocation, and cannot remove the final Platform Administrator. The user-state change and Platform-scoped Domain Event commit atomically.

## Authentication flows

Access tokens are signed JWTs. Refresh tokens are opaque persisted values tied to the user's security stamp. Login returns both and writes the refresh token cookie. Refresh accepts the request token or cookie, validates persistence/expiry/stamp, revokes the used token, and rotates the pair.

Personal API Keys are opaque User-owned Bearer credentials. Their hashes, access modes, optional expiry, revocation, and issue-time security stamps are persisted. The complete key is shown once. A key acts through the User's current Memberships and Agent Access; read-only mode blocks mutations. Full-access keys may issue or revoke the same User's keys. Password changes and resets invalidate keys issued under the prior security stamp. The platform API accepts a Platform Administrator's key, while Organization routes still require real Membership.

Password change/reset updates the security stamp so existing refresh tokens fail later validation. Logout clears the browser cookie but does not revoke a separately held persisted refresh token.

Accounts enter through Google sign-in (self-signup), Platform Administrator provisioning, or organization invitation. Password self-registration (`POST /auth/signup`) stays disabled. Platform provisioning atomically creates a pending User, their initial Organization, their Owner Membership, and a one-time set-password token; the invitation email is sent only after commit. The Platform Administrator never chooses or learns the user's password. Reset/invite tokens are stored as hashes, expire, and are marked used after successful enrollment/reset. Resending an invitation rotates the token so prior links stop working.

### Google sign-in and self-signup

`GET /auth/google/start?origin=signup|login` redirects to Google's OpenID Connect consent screen, asking only for `openid email profile`, with the shared `GOOGLE_CLOUD_CLIENT_ID`. `<WEB_APP_URL>/api/v1/auth/google/callback` must be registered on that client. The signed `state` carries a nonce that is also set as a short-lived, single-use, path-scoped `SameSite=Lax` cookie; the callback requires both, so a callback cannot be replayed or used to sign someone else in. The callback redeems the code server-side and checks the id_token's issuer, audience, and expiry (the token comes straight from Google's token endpoint over TLS, so its signature is not checked).

The callback resolves the account by Google account id first, then by email ignoring case:

- An unverified Google address neither creates an account nor signs in to one.
- An existing account is linked to the Google account. A pending invitee is enrolled — verified, with their invitation links retired — as if they had followed the link.
- An address that has already had a trial, even one whose account was deleted, is refused with `?error=trial_used`.
- An unknown address, when `SELF_SIGNUP_ENABLED` is on (it is off by default), creates a verified User marked `signed_up_at`, their trial Organization, and their Owner Membership in one transaction, then provisions the Organization's LiteLLM team. Google-only accounts hold an unusable password hash, as invitees do until they enroll.

Success starts a session like password login: the refresh-token cookie, which the web app trades for an access token. The browser lands on `/onboarding` while a self-signed-up user has not finished onboarding, otherwise on `/dashboard`. Failure returns to the starting page with `?error=cancelled|failed|unavailable|unverified|signup_closed|trial_used` and nothing created. Trial onboarding itself is described in [Trial onboarding](trial-onboarding.md).

## Organization creation and membership flows

Any authenticated user, including a Platform Administrator, creates an Organization through `POST /organizations` using only a name and optional description — except a self-signed-up user whose trial a Platform Administrator has not ended (`trial_ended_at` unset, even after deleting the trial) and the Owner of an active Trial Organization, who are refused with 403; the selector hides the option for them. The server records that user as the immutable Organization Creator, creates their Owner Membership in the same transaction, and applies the platform default model configuration. The configurable per-creator limit defaults to five non-deleted Organizations; Platform Privilege does not bypass it. A Platform-provisioned user's initial Organization follows the same creator and default-model rules and counts toward that limit.

Organization Owners and Admins can rename their Organization from its management page. The name editor trims surrounding whitespace and accepts 3–255 characters; saving refreshes the detail and membership-derived Organization selector.

Self-signup creates a **Trial Organization** (`is_trial`), at most one per email address: it runs up to the platform's trial agent limit (enforced under a lock when an Agent is stored) on a one-off spend limit set from the platform's trial credit. A Platform Administrator ends a trial with `POST /platform/organizations/{id}/end-trial`, giving the spend limit and window it moves to; that lifts the agent limit and its owner's Organization-creation block, and records `organization.trial.ended`. See [Trial onboarding](trial-onboarding.md#trials).

All creation paths provision an Organization-scoped LiteLLM team after commit when the proxy is configured. Team identity, reconciliation, and the platform-administered spend ceiling stored on the Organization are owned by [Costs](costs.md#organization-llm-budgets).

Organization Name is a mutable display label and is intentionally not globally unique. Platform View disambiguates same-named Organizations with owner identity and Organization ID, and its allowlisted Organization detail projection exposes immutable Creator identity without exposing Organization configuration. A separate globally unique human-facing handle is deferred until a URL, CLI, API, or support workflow requires one.

Legacy Organizations backfill Organization Creator from their current Owner Membership. A genuinely ownerless legacy Organization retains an unknown creator instead of inventing provenance.

Membership list, invite, role-update, and removal workflows require their corresponding Organization Permissions through real membership; seeded Owner/Admin roles receive them. Organization invitations and resends are delivered only by email: the add-member and resend-invite responses keep their `invite_link` field for v1 compatibility but always return null, so an inviter cannot enroll an address they don't control. Owner-only rules protect ownership and sensitive Admin operations. Removing a pending Member also revokes outstanding invite/reset links.

The UI resolves Organization View from `/dashboard/[orgId]`; Platform View lives at `/dashboard/platform` and has no active Organization. A signed-in user with no Membership lands on Platform View if they are a Platform Administrator, otherwise on `/no-organization`, which says so (and, for a self-signed-up user whose trial was deleted, that the trial has ended). The Organization selector is always membership-derived—even for Platform Administrators—and exposes self-service creation to every authenticated user. Platform-wide Organization results are never injected into the selector. Remembered organization state is only a navigation fallback for returning to Organization View. Organization-scoped hooks include the organization ID in API URLs. Organization switching removes known organization-scoped query caches because those keys are not organization-dimensioned.

## Source map

| Concern                               | Authoritative source                                                                                                                                                                                                                                                                                  |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Auth storage and current-user context | `../../api/domains/auth/models.py`                                                                                                                                                                                                                                                                          |
| Token and enrollment workflows        | `../../api/domains/auth/service.py`, `../../api/domains/auth/routes.py`                                                                                                                                                                                                                                           |
| Google sign-in and self-signup        | `../../api/domains/auth/google_sign_in.py`, `../../api/infrastructure/google/identity.py`, `../../api/tests/integration/test_google_sign_in.py` |
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
