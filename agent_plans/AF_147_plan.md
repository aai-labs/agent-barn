# AF-147 — Enable Multi-Organization Support — Implementation Plan

## Context

AF-147 turns the single-tenant default-org system into a real multi-tenant one, per
the AF-146 design ([wiki: Agent farm multi-organization support](https://aai-labs.atlassian.net/wiki/spaces/AF/pages/2771681328)).
The chosen model is **shared pool (row-level isolation)**: every resource carries
`organization_id`, and the tenant must be resolved **before the first DB query**.

Acceptance criteria (AF-147):
- It is possible to enroll a new org.
- Agents, templates, skills, users and all resources are scoped by org.
- The AF-146 design is implemented.

**Scope boundary with AF-150.** Role _authorization semantics_ (superuser = all orgs;
org admin = manage whole org; member = only agents they create) and the
permissions/roles tables live in **AF-150**, done next. AF-147 keeps the existing
`OrganizationRole` enum (OWNER/ADMIN/MEMBER) and existing coarse checks
(`_ensure_can_manage_organization`, `organization_roles` in `get_current_user`).
AF-147 delivers the **data plane** (isolation + enrollment); AF-150 layers
fine-grained authorization on top. The shared seam is `CurrentUserContext` — AF-147
puts the _active org_ on it; AF-150 adds permission checks that read it.

**Methodology: TDD** — for each phase write failing tests first (red), implement to
green, then check coverage.

**Code quality posture** — stay mindful of quality as we go (reuse over duplication,
sensible naming, thin routes / logic in services), but don't over-engineer mid-flight.
A dedicated final pass at the end of the ticket extracts shared helpers and reusable
components (API and UI) and removes repetition. When something is obviously reusable
(e.g. the invite helper, a copy-link component), factor it now; otherwise flag it with a
`# TODO(AF-147 refactor):` note and leave it for the final pass rather than blocking.

## Current-state findings (already in place)

- `Organization`, `User`, `OrganizationUser` tables exist; `OrganizationUser` has a
  partial unique index `uq_user_organization_one_owner_per_org` (one OWNER per org)
  and `uq_user_organization` (one membership per user+org).
- `organization_id` columns already exist on `agent`, `agent_template`, `skill`
  (nullable — global skills), `tool_call`.
- **Resource scoping is already plumbed through the context**: `agents`, `templates`,
  and `skills` services all resolve the org via
  `context.require_current_user_organization().organization_id`
  (`agents/service.py:181` `_org_id`, `templates/service.py:46`, `skills/service.py:35`).
  So per-resource scoping already works — the only gap is that
  `current_user_organization` is populated from a **global default org**, not per request.
- Tenant resolution is a module global: `set_default_org_id(default_org.id)` is called
  once at startup (`api_app.py` lifespan) and `get_organization_id(request)` always
  returns it (`auth/utils.py`).
- Org endpoints exist: `GET`, `GET /{id}`, `PATCH /{id}`, `DELETE /{id}`. **No `POST`.**
- Invite infra exists but is unwired: `EmailService.send_user_invite_email(...)` and
  `templates/user-invite-template.mjml` (⚠️ branded "Export Discovery" — needs
  rebranding to Agent Barn — done). Password-reset token infra is reusable:
  `AuthService.generate_password_reset_token`, `verify_password_reset_token`,
  `reset_password`; links use `config.web_app_url`.
- `POST /auth/signup` is a 410 no-op (self-signup disabled — enrollment is invite-only).
- `UserService.get_paginated_users` passes `organization_id=None` → returns all users
  (not org-scoped). `UserRepository._get_query` already supports org scoping (and
  excludes superusers) when `organization_id` is passed.
- `organization_users` has models/service/repository but **no routes** (no member-mgmt API).
- **UI already scaffolds org state**: `features/organizations/stores/org-store.ts`
  persists `selectedByUser` (userId → orgId), plus `organization-provider.tsx`. The
  auth interceptor (`shared/api/interceptor/auth-intercepter.ts`) attaches
  `Authorization` but **not** an org header yet.

## Decisions

| Question | Decision |
|----------|----------|
| Sequencing | AF-147 (this) first, then AF-150 (roles + agent ownership). |
| RBAC / permission tables | Out of scope — AF-150. Keep the `OrganizationRole` enum. |
| Tenant resolution | Per-request **`X-Organization-Id` header**, validated against membership in `get_current_user`; superuser may target any org. Global default remains the fallback when the header is absent. |
| First user of a new org | Becomes **OWNER** (one-per-org; wiki says owner/admin are functionally identical). |
| Enrollment path | Superuser creates the org **and** invites the first owner in one call; invite reuses the password-reset token flow. Self-signup stays disabled. |
| Superuser acting in an org | When superuser + `X-Organization-Id` present but no membership row, synthesize a transient `current_user_organization` (role OWNER) for that org so scoping/`_org_id()` resolve. Not persisted. |
| Member listing | New org-scoped `/organizations/{id}/members` endpoints. `/users` stays superuser-only/global. |
| Invite link surfaced | `POST /organizations` (and resend) return the set-password link in the response so an admin can deliver it manually. Email is still sent (email delivery is configured). |
| Resend invite | `POST /organizations/{id}/members/{user_id}/resend-invite` regenerates the token, resends the email, and returns a fresh link. Covers a pending owner or member whose invite expired or was lost. Only valid while the target user is still unverified (`email_verified_at is None`). |

---

## Phase 1 — Per-request tenant resolution (`X-Organization-Id`) — ✅ DONE

Goal: `current_user_organization` reflects the header org (validated), not the global
default. This immediately makes every already-scoped resource honor the active org.

_Status: implemented in `auth/utils.py` (`get_organization_id` reads/validates the
header; superuser synthesis for cross-org access). Tests in
`api/tests/integration/test_tenant_resolution.py` (5). Full suite 512 passed._

### 1a. Tests first (RED)
- `api/tests/integration/test_tenant_resolution.py` (new). Reuse steps in
  `api/tests/steps/{organization,user,agent}.py`.
  - Member sends `X-Organization-Id` for an org they belong to → resource lists (e.g.
    `GET /agents`) scoped to that org.
  - Member sends header for an org they do **not** belong to → `403`.
  - Superuser sends header for any org → allowed; scope is that org.
  - Two orgs, agent created in org A → not visible when acting as org B (isolation).
  - Malformed header (not a UUID) → `400`.
  - No header → falls back to default org (existing behavior preserved).

### 1b. Implement (GREEN) — `api/domains/auth/utils.py`
- `get_organization_id(request)`: read `X-Organization-Id`; if present parse UUID
  (raise `HTTPException(400)` on malformed); else return the global `_default_org_id`
  fallback. (Keep `set_default_org_id`/`_default_org_id` for the no-header fallback.)
- In `get_authenticated_user`, after computing `user_organization`: if
  `user.is_superuser and organization_id and user_organization is None`, synthesize a
  transient `OrganizationUser(user_id=user.id, organization_id=organization_id,
  role=OWNER)` and use it as `current_user_organization` (do not persist). The existing
  non-superuser `ForbiddenException` when membership is missing stays as-is.
- No signature changes to `get_current_user`; resource services already read
  `context.require_current_user_organization()`.

### 1c. Confirm GREEN
- `make check-api && make test-api`.

---

## Phase 2 — Organization creation + first-owner invite (superuser) — ✅ DONE

_Status: `POST /organizations` (superuser) creates a non-default org, invites the owner
as OWNER via the reusable `AuthService.invite_user` helper, and returns
`OrganizationCreateResult{organization, invite_link}`. Invite template redesigned to the
Agent Barn brand (warm cream palette, dark button, barn logo). Tests in
`api/tests/integration/test_organizations.py` (5). Org+owner
creation is not yet a single transaction — flagged `# TODO(AF-147 refactor)`._


### 2a. Tests first (RED)
- `api/tests/integration/test_organizations.py` (extend/new):
  - Superuser `POST /organizations {name, description?, owner_email, owner_name?}` →
    `201`, org created (`is_default=False`), owner `OrganizationUser` with role OWNER
    exists, invite email attempted, and the response includes the set-password
    `invite_link` for the newly invited owner.
  - Non-superuser → `403`.
  - `name` < 3 chars → `422`.
  - `owner_email` already an existing **active** user → org still created, existing user
    added as OWNER, no new account, `invite_link` is null (no invite needed).
  - Second org with same owner_email → allowed (user can own/belong to multiple orgs).

### 2b. Implement (GREEN)
- `models.py` — extend `OrganizationCreate` with `owner_email: EmailStr`,
  `owner_name: str | None = None`. Add response model
  `OrganizationCreateResult { organization: OrganizationRead, invite_link: str | None }`
  (invite link lives only on the create/resend responses — never on `GET`, so it can't leak).
- `routes.py` — `POST /organizations` (`get_current_user(check_superuser=True)`) →
  `201 OrganizationCreateResult`; takes `BackgroundTasks` for the invite send.
- `service.py` — `create_organization(data, actor, background_tasks)`:
  1. Create `Organization(name, description, is_default=False)` (transaction via
     `save_with_session`).
  2. Find user by `owner_email`; if absent, create `User(email, full_name=owner_name,
     hashed_password="")`, `email_verified_at=None` (invited, not yet active).
  3. Create `OrganizationUser(user_id, org_id, role=OWNER)` (handles
     `OneOwnerPerOrganizationException`).
  4. If the user was newly created (or unverified), generate an invite token
     (`AuthService.generate_password_reset_token`), build
     `set_password_link = f"{config.web_app_url}/auth/set-password?token={token}"`, and
     `EmailService.send_user_invite_email(owner_email, set_password_link, owner_name)`
     via `background_tasks`.
  5. Return `OrganizationCreateResult(organization=..., invite_link=set_password_link)`
     (`invite_link` null when the owner was an existing active user).
  6. Factor the "ensure a pending user + generate token + send invite" logic into a
     reusable helper — Phase 4 add-member and resend-invite reuse it.
- Wire `OrganizationService` deps: add `UserRepository`, `OrganizationUserRepository`,
  `AuthService`, `EmailService`, `Config` (mirror `UserService` wiring).

### 2c. Rebrand invite template
- `api/infrastructure/email/templates/user-invite-template.mjml` — replace
  the old generic gray/blue palette with the Agent Barn brand (warm cream palette,
  dark primary button, barn logo mark, "Agent Barn" wordmark).

### 2d. Confirm GREEN — `make check-api && make test-api`.

---

## Phase 3 — Accept invite / set password (enrollment completion) — ✅ DONE

_Status: `POST /auth/set-password` → `AuthService.accept_invite` (shared
`_apply_new_password` helper with `reset_password`, adds email verification). Tests in
`api/tests/integration/test_set_password.py` (4)._


### 3a. Tests first (RED)
- `api/tests/integration/test_auth.py` (extend):
  - Valid invite token → `POST /auth/set-password {token, new_password}` sets password,
    stamps `email_verified_at`, marks token used; user can then log in.
  - Expired/used token → `400`/`410`.
  - Weak password → `400`.

### 3b. Implement (GREEN)
- `api/domains/auth/routes.py` — add `POST /auth/set-password` taking
  `PasswordResetRequest` (reuse). Delegate to `AuthService`.
- `api/domains/auth/service.py` — add `accept_invite(reset_request)` (or extend
  `reset_password`) that verifies the token, calls `UserService.reset_user_password`,
  and stamps `email_verified_at = now()` when unset. Reuses `verify_password_reset_token`.
- (Same UI page can serve both reset-password and set-password; link differs only by route.)

### 3c. Confirm GREEN — `make check-api && make test-api`.

---

## Phase 4 — Org-scoped member management — ✅ DONE (API)

_Status: member router at `domains/users/organization_users/routes.py` (registered in
`api_app.py`): GET/POST members, PATCH role, DELETE member, POST transfer-ownership,
POST resend-invite. Service enforces owner/admin (superuser bypass); transfer restricted
to owner/superuser and done atomically (demote→flush→promote). Tests in
`api/tests/integration/test_organization_members.py` (12) + `test_user_listing_scope.py`
(3). Add/resend reuse `AuthService.invite_user`._


Endpoints under `org_router`, guarded by the existing
`OrganizationService._ensure_can_manage_organization` (superuser or owner/admin of that org).

### 4a. Tests first (RED)
- `api/tests/integration/test_organization_members.py` (new):
  - Owner/admin lists members of their org → only that org's members (superusers
    excluded); other org's members not shown.
  - Member (non-admin) lists → `403`.
  - Add member by email (existing user) → `201`, membership row with requested role.
  - Add member by new email → invite email sent, membership created as MEMBER.
  - Change role → `200`; changing someone to OWNER when one exists → `409`
    (one-owner-per-org) unless via transfer.
  - Remove member → `204`; membership gone.
  - Transfer ownership → old owner becomes ADMIN, new owner becomes OWNER (single tx).
  - Resend invite for a pending (unverified) member → `200` with a fresh `invite_link`,
    new token, email re-sent.
  - Resend invite for an already-active member → `409` (nothing to resend).
  - Non-member / cross-org actor → `403`.

### 4b. Implement (GREEN)
- `api/domains/organizations/routes.py` (or a nested members router) — add:
  - `GET  /organizations/{org_id}/members` → `PaginatedItems[OrganizationUserRead]`.
  - `POST /organizations/{org_id}/members {email, role}` → `201` (invite if new user).
  - `PATCH /organizations/{org_id}/members/{user_id} {role}` → `200`.
  - `DELETE /organizations/{org_id}/members/{user_id}` → `204`.
  - `POST /organizations/{org_id}/transfer-ownership {user_id}` → `200`.
  - `POST /organizations/{org_id}/members/{user_id}/resend-invite` → `200`
    `{ invite_link }` (only while target `email_verified_at is None`; reuses the
    Phase 2 invite helper to regenerate the token + resend the email).
- `OrganizationUserService` — add `list_members`, `add_member` (reuse invite flow from
  Phase 2 for new emails), `change_role`, `remove_member`, `transfer_ownership`
  (transactional swap using `save_with_session`). Reuse
  `OrganizationUserRepository` and its `OneOwnerPerOrganizationException` /
  `UserAlreadyPartOfOrganizationException` translation.
- `OrganizationUserRepository` — add `find_all_paginated_by_org`,
  `get_owner`, and role-update helpers as needed.

### 4c. Org-scope `/users` and open it to org admins/owners — ✅ DONE
_Status: `list_users` now guarded by `organization_roles=[OWNER, ADMIN]` (superuser
bypasses); `get_paginated_users` scopes by the active org for admins/owners, global for
superuser. Tests in `api/tests/integration/test_user_listing_scope.py` (3). Full suite
524 passed._

Org admins/owners must be able to see the users in their org — today `/users` is
`check_superuser=True` (they get 403). Fix:
- **Route guard**: change `list_users` to `get_current_user(organization_roles=[OWNER,
  ADMIN])` (superuser bypasses `organization_roles` in `get_authenticated_user`). Plain
  members get 403 (aligns with AF-150 "members only see/manage their own agents").
- **Scoping**: `get_paginated_users` takes the active org from context and passes it to
  `find_all_paginated`. Superuser → all users when no header, or the targeted org when a
  header is sent; owner/admin → their active org only (repo filter already excludes
  superusers). This is the org-scoped **listing** surface (the Users page).
- Membership *mutations* still live under `/organizations/{org_id}/members` (4b);
  `/users` is listing + platform-level superuser management only.
- Tests: owner/admin lists only their org's users; member → 403; superuser → all;
  cross-org isolation (org A admin can't see org B users).

### 4d. Confirm GREEN — `make check-api && make test-api`.

---

## Phase 5 — UI

### 5.0 Design consistency (applies to every new page/dialog)
New UI must look native to the app — reuse existing primitives, do not introduce new
component styles, colors, or spacing. Concretely:
- **Primitives**: `src/components/ui/*` — `dialog`, `button`, `input`, `label`, `field`,
  `card`, `tabs`, `dropdown-menu`, `alert`, `avatar`, `skeleton`, `separator`, `tooltip`.
- **Page shell**: `components/list-page-header.tsx` for list headers;
  `components/app-error-state.tsx` / `route-error-state.tsx` for errors;
  `ui/skeleton.tsx` for loading.
- **Toasts**: `shared/toast.ts` (sonner) — same success/error pattern as existing flows.
- **Icons**: `components/icons.tsx` (don't inline new SVGs).
- **Pattern templates (copy these, they're the AF-143 canon)**:
  - Create-org dialog → mirror `features/users/components/create-user-dialog.tsx`
    (react-hook-form + `zodResolver`, `field`/`input`/`label`, footer buttons, toast).
  - Members grid + row actions → mirror `features/users/components/users-grid.tsx`,
    `delete-user-dialog.tsx`, `reset-password-dialog.tsx`, and the existing
    `features/organizations/components/organizations-grid.tsx`.
  - Set-password page → reuse the reset-password form styling
    (`features/users/components/reset-password-dialog.tsx` / the auth reset form).
- Follow AGENTS.md UI conventions: reuse `@/*` imports, `shared/api` client, centralized
  query keys, invalidate affected keys on mutation.

### 5a. Send the active-org header — ✅ DONE
_`OrganizationProvider` sets `X-Organization-Id` from `selectedOrganization` via
`api.setHeader` during render (ref-guarded — avoids the initial-fetch race), and
`queryClient.invalidateQueries()` on org switch. tsc + lint clean._

### 5b. Org switcher (top-nav) — ✅ DONE
_`features/organizations/components/org-switcher.tsx` (matches the top-nav's own custom
dropdown style): static breadcrumb for 0–1 orgs, dropdown for many; replaced the static
`orgName` prop in `top-nav.tsx`/`dashboard/layout.tsx`. Added shared `ChevronDownIcon`.
Regular users' picker = their memberships; **superusers' picker = ALL orgs**
(`use-all-organizations.ts`, GET /organizations), so a superuser can enter/scope to any
org (backend synthesizes their membership + scopes resources/users to the picked org —
superuser-gets-scoped is intended). Provider gates render until the superuser org list
loads so the header is set before children fetch._

### 5a-orig. Send the active-org header (original notes)
- `ui/src/shared/api/interceptor/auth-intercepter.ts` — in `attachAuthToken`, also set
  `config.headers["X-Organization-Id"]` from the selected org for the current user
  (`useOrgStore.getState().selectedByUser[userId]`). Guard for absence. Wire the store
  getter through `AuthConfig`/factory so the interceptor stays framework-agnostic.
- Ensure a sensible default: on login/hydration, if no org is selected, default to the
  user's first membership (see `organization-provider.tsx`,
  `stores/init-store-sync.ts`, `use-org-store-hydrated.ts`).
- Invalidate all resource queries when the active org changes (org switch must refetch
  agents/templates/skills/etc.).

### 5b. Org switcher (top-nav)
- Add/confirm an org switcher that lists the user's orgs (from `/auth/me`
  `organization_users`) and calls `setOrganizationId(userId, orgId)`.

### 5c. Create-org dialog (superuser) — ✅ DONE
_`create-organization-dialog.tsx` (mirrors create-user-dialog; name/description/ownerEmail/
ownerName) + `use-organization-actions.ts` (POST /organizations, invalidates list). On
success shows the returned invite link via reusable `invite-link-field.tsx` (copy button).
"Create organization" button added to `organizations-grid.tsx`._

### 5e. Set-password page — ✅ DONE
_`app/(auth)/set-password/page.tsx` (Suspense) + `set-password-form.tsx` +
`use-set-password.ts` (POST /auth/set-password). Closes the enrollment loop from the
invite email. Invalid/missing token → error card._

### 5d. Members management — ✅ DONE
_Route `app/dashboard/organizations/[id]/members/page.tsx` → `organization-members.tsx`:
list with search, role change, remove, transfer-ownership, resend-invite (reusing
`invite-link-field`), add-member dialog. Hooks: `use-organization-members`,
`use-member-actions`, `use-organization`. Entry points: "Manage members" on each org card
(superuser) + a "Members" dropdown link for owners/admins of the active org._

### 5c-orig. Create-org dialog (superuser) — original notes
- `features/organizations/` — Zod `CreateOrganizationSchema` (name, description,
  ownerEmail, ownerName), `use-organization-actions` mutation `POST /organizations`
  (invalidate `organizationKey.lists()`), and a create dialog. Show entry only to superusers.
- On success, if the response carries an `invite_link`, show it in the dialog with a
  **Copy** button (and a note that the invite email was also sent) so the admin can
  deliver it directly.

### 5d. Members page
- `app/.../organizations/[id]/members` (or a members tab) — list members, invite
  (email + role), change role, remove, transfer ownership. Reuse patterns from the
  users feature (AF-143). Hooks via `shared/api`, centralized query keys.
- Pending (unverified) members show a **Resend invite** action; on success surface the
  returned `invite_link` with a Copy button (same component as the create dialog).

### 5e. Accept-invite / set-password page
- `app/(auth)/set-password/page.tsx` — token-driven form; `POST /auth/set-password`;
  on success redirect to `/login`. Reuse the reset-password form/component.

### 5f. Tests + checks
- Playwright: org switch refetches scoped lists; superuser creates org; invite/accept
  flow; member add/remove/role-change. Page objects in `tests/pages`, mocks in shared
  support, assertions in specs.
- `make lint-ui && cd ui && pnpm -s tsc --noEmit && make test-ui`.

---

## Refactor items / follow-ups (end-of-ticket pass or separate tickets)

- **Centralize superuser authorization.** Superuser access is a boolean `User.is_superuser`
  flag checked in ~9 scattered spots (auth util synthesis at `auth/utils.py:95`, the
  `organization_roles`/`check_superuser` gates, and per-service guards in
  `organizations/service.py`, `users/service.py`, `organization_users/service.py`). It's
  consistent but repeated and easy to forget on a new org-scoped endpoint. Fold the
  "superuser OR has-role/permission" pattern into a single helper — and ideally into the
  `require_permission()`/`can()` layer AF-150 introduces (superuser ⇒ all permissions), so
  these branches collapse to one place. The load-bearing one is the synthesis in
  `get_authenticated_user`; most service checks are just "superuser OR role".
- **Dedicated `invitation` table.** Invites currently reuse the `password_reset_token`
  table (JWT + `(user_id, jti, is_used, expires_at)` row), which conflates password reset
  with invitation and carries no invite metadata. As invites expand to regular users, add
  a first-class `Invitation` (`email, organization_id, role, invited_by_user_id,
  token_hash/jti, status, expires_at, accepted_at`) — revocable, listable ("pending
  invites"), and able to *create* the membership on accept rather than pre-creating it.
  Prefer an opaque hashed token over a JWT. Decide: fold into AF-147 vs. a separate ticket
  (dovetails with AF-150). Rewires `invite_user`/`accept_invite`.
- **Single transactions.** Wrap org+owner creation (`create_organization`) and
  add-member+invite in one DB transaction so a failed invite can't leave an org without an
  owner / a half-created membership (current `# TODO(AF-147 refactor)` markers).
- **Block org deletion when it still has agents.** `delete_organization` currently
  cascades/soft-deletes the org's resources and orphans running k8s pods. Require an
  explicit teardown first: after the owner/superuser authz + `is_default` (409) guards,
  count active (non-deleted) agents for the org and raise `409 Conflict` ("Delete this
  organization's agents before deleting it") if any remain. Add integration tests (org
  with agents → 409; org with none → 204); the UI delete dialog already surfaces
  `e.message`. Open question: should templates/skills block too, or only agents (the hard
  requirement)?
- **UI/API shared cleanup.** Extract any remaining duplicated dialog/hook boilerplate
  surfaced during review (per the code-quality posture).

## Verification

1. `make check-api && make test-api` — API checks + tests pass; `make coverage` for gaps.
2. `make lint-ui && cd ui && pnpm -s tsc --noEmit && make test-ui`.
3. Manual: superuser creates Org B with owner email → owner receives invite → sets
   password → logs in as Org B owner.
4. Manual isolation: create an agent in Org A; switch active org to Org B → agent not
   visible; templates/skills/tool-calls likewise scoped.
5. Manual: Org B owner invites a member; member sees only Org B.
6. Manual: member cannot access Org A via `X-Organization-Id` spoofing → `403`.
7. Migrations: any schema change (e.g. if a column is added) has a migration + it
   `make migrate` / `make rollback` cleanly.

## Migrations

- No new tables/columns are strictly required for Phases 1–4 (org scoping columns
  already exist; enrollment reuses existing tables). If member-management needs a new
  index/column, add an Alembic migration via `make makemigrations` and cover it per
  AGENTS.md.

## Key files to modify/create

| Action | File |
|--------|------|
| Modify | `api/domains/auth/utils.py` — header-based `get_organization_id`, superuser org synthesis |
| Create | `api/tests/integration/test_tenant_resolution.py` |
| Modify | `api/domains/organizations/models.py` — `OrganizationCreate` owner fields |
| Modify | `api/domains/organizations/routes.py` — `POST /organizations`, member endpoints |
| Modify | `api/domains/organizations/service.py` — `create_organization` + deps |
| Modify | `api/domains/users/organization_users/service.py` — member mgmt methods |
| Modify | `api/domains/users/organization_users/repository.py` — member queries |
| Modify | `api/domains/auth/routes.py` — `POST /auth/set-password` |
| Modify | `api/domains/auth/service.py` — `accept_invite` / verify+stamp email |
| Modify | `api/domains/users/service.py` — org-scope `get_paginated_users` |
| Modify | `api/infrastructure/email/templates/user-invite-template.mjml` — rebrand |
| Create | `api/tests/integration/test_organizations.py` (create/invite) |
| Create | `api/tests/integration/test_organization_members.py` |
| Modify | `api/tests/integration/test_auth.py` — set-password |
| Modify | `ui/src/shared/api/interceptor/auth-intercepter.ts` — `X-Organization-Id` |
| Modify | `ui/src/features/organizations/*` — switcher, create dialog, members, actions/hooks |
| Create | `ui/src/app/(auth)/set-password/page.tsx` |
| Create | Playwright specs for org switch / create / invite / members |

## Reusable existing code

| Utility | Location |
|---------|----------|
| Active-org seam | `CurrentUserContext.require_current_user_organization()` (`auth/models.py`) |
| Org resolution hook | `get_organization_id` / `set_default_org_id` (`auth/utils.py`) |
| Invite email | `EmailService.send_user_invite_email` (`infrastructure/email/service.py`) |
| Token infra | `AuthService.generate_password_reset_token` / `verify_password_reset_token` / `reset_password` |
| Manage-org guard | `OrganizationService._ensure_can_manage_organization` |
| Owner/membership constraints | `uq_user_organization_one_owner_per_org`, `OneOwnerPerOrganizationException`, `UserAlreadyPartOfOrganizationException` |
| Org-scoped user query | `UserRepository._get_query(..., organization_id=...)` (excludes superusers) |
| Web app base URL | `Config.web_app_url` |
| UI org state | `features/organizations/stores/org-store.ts`, `organization-provider.tsx` |
| UI primitives | `ui/src/components/ui/*` (dialog, button, field, input, tabs, …) |
| UI pattern templates | `features/users/components/*` (create/delete/reset dialogs, grid), `components/list-page-header.tsx`, `shared/toast.ts` |
| Test steps | `api/tests/steps/{organization,user,agent,database,template}.py` |
```
