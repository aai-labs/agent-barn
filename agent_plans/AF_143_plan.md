# User Management Feature — Implementation Plan

## Context

The application needs basic user management where super admins can create and delete users, and any user can change their password. Currently, user creation only happens via self-signup (creates user + personal org) or startup bootstrap (creates default super admin). Self-signup will be disabled, making admin-created users the only path.

**Methodology: TDD (Test-Driven Development)** — For each feature, write tests first (red), then implement code to make them pass (green).

## Decisions

| Question | Decision |
|----------|----------|
| Org assignment for new users | Default org as MEMBER |
| "Skills" in acceptance criteria | Means existing features (agents, templates) — no new domain |
| Password change UI location | Dialog from user menu dropdown in top-nav |
| Self-signup | Disable — remove endpoint + UI |
| Delete rules | Cannot delete self |
| Create form fields | Email (required) + password (required, auto-gen + copy) + full name (optional) |

---

## Phase 1: API — Tests First (RED)

### 1a. Add request model — `api/domains/users/models.py`
- Add `AdminUserCreate(PydanticBaseModel)` with fields: `email: EmailStr`, `password: str`, `full_name: str | None = None`
- This is a prerequisite for writing tests that reference the model.

### 1b. Write integration tests — `api/tests/integration/test_users.py` (new file)
Write all tests FIRST. They will fail because the endpoints/logic don't exist yet.

Test cases using existing `given`/`when`/`then` BDD pattern:
- **Create user happy path**: super admin POST `/api/v1/users` → 201, verify user data in response
- **Create user → duplicate email**: create same email twice → 409
- **Create user → weak password**: e.g. "123" → 400
- **Create user → non-super-admin rejected**: regular user POST → 403
- **Delete user → cannot delete self**: super admin DELETE own ID → 400
- **Delete user → works for other user**: 204

Setup steps to reuse: `there_is_a_default_organization()`, `there_is_authenticated_user(is_superuser=True)`, `there_is_a_user()`

### 1c. Update existing `delete_user` unit test for new signature
- `api/tests/unit/test_service_edge_cases.py:97` — `service.delete_user(user.id)` currently passes 1 arg. Update to pass a different `actor_id` so it matches the new `(user_id, actor_id)` signature: `service.delete_user(user.id, uuid7())`

### 1d. Update existing signup tests to expect 410
These tests currently test self-signup. Update them BEFORE disabling the endpoint so they fail (red):
- `api/tests/integration/test_auth.py:48` — `test_i_can_signup_and_user_is_created` → update to expect 410
- `api/tests/integration/test_auth_flow_extended.py:87` — `test_signup_grants_access_to_organizations_immediately` → remove or update to expect 410
- `api/tests/integration/test_templates.py:573` — `test_signup_seeds_predefined_templates_for_new_org` → remove (templates are seeded for default org at startup, not per-user signup)

### 1e. Run tests → confirm RED
- `make test-api` — new tests fail (404 for POST /users, wrong status codes for updated signup tests), existing delete test fails on self-delete guard

---

## Phase 2: API — Implementation (GREEN)

### 2a. Update service — `api/domains/users/service.py`
- **Add dependency**: inject `OrganizationRepository` (import from `api.domains.organizations.repository`)
- **Add method** `create_user(self, data: AdminUserCreate) -> User`:
  1. `validate_strong_password(data.password)` — reuse from `api/domains/auth/password_validation.py`
  2. Create `User(email=data.email, full_name=data.full_name, hashed_password=hash_text(data.password))` — reuse `hash_text` from `api/domains/auth/hashing.py`
  3. `self.user_repository.save(user)` — `EmailTakenHTTPException` auto-raised on duplicate email
  4. `default_org = self.organization_repository.find_default()` — raise `HTTPException(500)` if None
  5. `self.organization_user_repository.save(OrganizationUser(user_id=user.id, organization_id=default_org.id, role=OrganizationRole.MEMBER))`
  6. Return user

- **Update method** `delete_user(self, user_id: UUID, actor_id: UUID)`:
  - Add guard: `if user_id == actor_id: raise HTTPException(400, "Cannot delete your own account")`
  - Rest unchanged

### 2b. Update routes — `api/domains/users/routes.py`
- **Add** `POST /users` (super admin only, status 201):
  - Depends: `get_current_user(check_superuser=True)`, `Injected(UserService)`
  - Body: `AdminUserCreate`
  - Calls `user_service.create_user(data)`, returns `UserRead` via `user_service.to_user_read(user)`
- **Update** `DELETE /users/{user_id}`:
  - Change `_` to `context` for the auth dependency
  - Pass `context.user.id` as `actor_id` to `user_service.delete_user(user_id, context.user.id)`

### 2c. Disable signup — `api/domains/auth/routes.py`
- Replace the `signup` function body: raise `HTTPException(410, "Self-registration is disabled. Contact an administrator.")`
- Clean up now-unused imports from that route (BackgroundTasks, SignupRequest, etc.)

### 2d. No migration needed
No database schema changes — `User`, `OrganizationUser` tables already exist.

### 2e. Run tests → confirm GREEN
- `make check-api && make test-api` — all tests pass

---

## Phase 3: UI — Playwright Tests First (RED)

### 3a. Update data support — `ui/tests/pages/data-support/user-data-support.po.ts` (or similar)
- Add `interceptCreateUserRequest()` — intercept POST `/api/v1/users` with mock success response
- Add `interceptDeleteUserRequest()` — intercept DELETE `/api/v1/users/**` with 204
- Add `interceptChangePasswordRequest()` — intercept POST `/api/v1/auth/me/change-password` with 204

### 3b. Users page tests — `ui/tests/e2e/users-page.spec.ts` (new file)
- "Create user" button opens dialog
- Creating a user shows toast + refreshes grid
- Delete button shown on non-current-user cards only
- Deleting a user shows confirmation then removes from grid

### 3c. Update signup tests — `ui/tests/e2e/signup-page.spec.ts`
- Update to expect redirect to `/login`

### 3d. Change password test — `ui/tests/e2e/change-password.spec.ts` (new file)
- "Change password" opens from user menu dropdown
- Submitting form with correct old password succeeds

### 3e. Run Playwright → confirm RED
- `make test-ui` — new tests fail (buttons/dialogs don't exist yet, signup still works)

---

## Phase 4: UI — Implementation (GREEN)

### 4a. Update schemas — `ui/src/features/users/schemas.ts`
- Add `CreateUserSchema` (Zod): email (required), password (reuse `strongPasswordSchema` from `@/auth/schemas`), fullName (optional string)
- Export `CreateUserData` type

### 4b. Add password generator — `ui/src/features/users/utils.ts`
- Add `generateStrongPassword(length = 16)`: produces random string with guaranteed uppercase, lowercase, digit, then shuffled

### 4c. Add mutation hook — `ui/src/features/users/hooks/use-user-actions.ts` (new file)
- `createUser` mutation: POST `/api/v1/users` with `{ email, password, full_name }`
- `deleteUser` mutation: DELETE `/api/v1/users/{id}`
- Both invalidate `usersKey.lists()` on success
- Return `{ createUser, isCreating, deleteUser, isDeleting }`
- Reuse: `api` client from `@/shared/api`, `usersKey` from `../utils`

### 4d. Create user dialog — `ui/src/features/users/components/create-user-dialog.tsx` (new file)
- Use Radix `Dialog` from `@/components/ui/dialog` (max-w-lg, appropriate size for a form)
- react-hook-form + `zodResolver(CreateUserSchema)`
- Fields:
  - Email input (required)
  - Password input with show/hide toggle + "Generate" button + "Copy" button
  - Full name input (optional)
- Generate button calls `generateStrongPassword()`, sets form value, shows password as visible
- Copy button uses `navigator.clipboard.writeText()`
- Submit calls `createUser` mutation
- Toast on success: "User created successfully" / on error: show API error message
- Props: `open: boolean`, `onOpenChange: (open: boolean) => void`

### 4e. Delete user dialog — `ui/src/features/users/components/delete-user-dialog.tsx` (new file)
- Radix `Dialog` confirmation with destructive styling
- Shows: "Are you sure you want to delete {user.email}?"
- Cancel + Delete buttons
- Delete calls `deleteUser` mutation
- Toast on success/error
- Props: `user: User | null`, `open: boolean`, `onOpenChange: (open: boolean) => void`

### 4f. Update users grid — `ui/src/features/users/components/users-grid.tsx`
- Add "Create user" button between `ListPageHeader` and the grid (a `PlusIcon` + "Create user" primary button)
- Add state for `createOpen`, `deleteTarget`
- Import `useCurrentUser()` to get current user ID
- On each user card: add a delete icon button (only if `user.id !== currentUser.id`)
- Render `<CreateUserDialog>` and `<DeleteUserDialog>` controlled by state
- Place button in a wrapper div above the grid alongside the header (the `ListPageHeader` has no action slot)

### 4g. Change password dialog — `ui/src/features/users/components/change-password-dialog.tsx` (new file)
- Radix `Dialog`
- react-hook-form with Zod schema: `oldPassword` (required), `newPassword` (strongPasswordSchema), `confirmNewPassword` (required) with `.refine()` for match
- Calls `POST /api/v1/auth/me/change-password` with `{ old_password, new_password }` via `api.post()`
- Toast on success: "Password changed successfully" / on error: show API message
- Props: `open`, `onOpenChange`

### 4h. Update top-nav — `ui/src/components/top-nav.tsx`
- Import `ChangePasswordDialog` and a key/lock icon from lucide-react
- Add state `changePasswordOpen`
- Add "Change password" menu item in the user dropdown (below "Account", above the super admin section)
- Render `<ChangePasswordDialog>` controlled by state
- Close dropdown when "Change password" is clicked (set `menuOpen(false)`)

### 4i. Remove signup — login form, signup page, auth actions
- `ui/src/auth/components/login-form.tsx` — Remove the "Don't have an account? Sign up" paragraph (lines 120-125)
- `ui/src/app/(auth)/signup/page.tsx` — Replace with a redirect to `/login` using `redirect()` from `next/navigation`
- `ui/src/auth/hooks/use-auth-actions.ts` — Remove `signup` mutation, `signupMutation`, and related exports
- `ui/src/auth/components/signup-form.tsx` — can be deleted (dead code)

### 4j. Run all UI checks → confirm GREEN
- `make lint-ui`
- `cd ui && pnpm -s tsc --noEmit`
- `make test-ui` — all Playwright tests pass

---

## Verification

1. `make check-api && make test-api` — all API checks and tests pass
2. `make lint-ui && cd ui && pnpm -s tsc --noEmit` — no lint/type errors
3. Manual flow: login as super admin → navigate to Users → click "Create user" → fill form → verify user appears in grid
4. Manual flow: login as new user → verify access to agents/templates on dashboard
5. Manual flow: change password → logout → login with new password
6. Manual flow: verify `/signup` redirects to `/login`
7. Manual flow: verify non-super-admin user doesn't see Users/Organizations nav links
8. `make test-ui` — Playwright tests pass

---

## Key Files to Modify/Create

| Action | File |
|--------|------|
| Modify | `api/domains/users/models.py` — add `AdminUserCreate` |
| Modify | `api/domains/users/service.py` — add `create_user`, update `delete_user` |
| Modify | `api/domains/users/routes.py` — add POST, update DELETE |
| Modify | `api/domains/auth/routes.py` — disable signup |
| Create | `api/tests/integration/test_users.py` |
| Modify | `api/tests/unit/test_service_edge_cases.py` — update `delete_user` call signature |
| Modify | `api/tests/integration/test_auth.py` — update signup test |
| Modify | `api/tests/integration/test_auth_flow_extended.py` — update signup test |
| Modify | `api/tests/integration/test_templates.py` — update/remove signup template seeding test |
| Modify | `ui/src/features/users/schemas.ts` — add `CreateUserSchema` |
| Modify | `ui/src/features/users/utils.ts` — add `generateStrongPassword` |
| Create | `ui/src/features/users/hooks/use-user-actions.ts` |
| Create | `ui/src/features/users/components/create-user-dialog.tsx` |
| Create | `ui/src/features/users/components/delete-user-dialog.tsx` |
| Create | `ui/src/features/users/components/change-password-dialog.tsx` |
| Modify | `ui/src/features/users/components/users-grid.tsx` — add create/delete UI |
| Modify | `ui/src/components/top-nav.tsx` — add change password |
| Modify | `ui/src/auth/components/login-form.tsx` — remove signup link |
| Modify | `ui/src/app/(auth)/signup/page.tsx` — redirect to login |
| Modify | `ui/src/auth/hooks/use-auth-actions.ts` — remove signup |
| Create | `ui/tests/e2e/users-page.spec.ts` |
| Create | `ui/tests/e2e/change-password.spec.ts` |
| Modify | `ui/tests/e2e/signup-page.spec.ts` — expect redirect |

## Reusable Existing Code

| Utility | Location |
|---------|----------|
| `validate_strong_password()` | `api/domains/auth/password_validation.py` |
| `hash_text()` | `api/domains/auth/hashing.py` |
| `EmailTakenHTTPException` | `api/domains/users/exceptions.py` (auto-raised by `UserRepository.save()`) |
| `OrganizationRepository.find_default()` | `api/domains/organizations/repository.py` |
| `strongPasswordSchema` | `ui/src/auth/schemas.ts` |
| Radix Dialog components | `ui/src/components/ui/dialog.tsx` |
| `usersKey` query keys | `ui/src/features/users/utils.ts` |
| `api` client | `ui/src/shared/api/` |
| Test steps: `there_is_a_user`, `there_is_a_default_organization`, `there_is_authenticated_user` | `api/tests/steps/` |
