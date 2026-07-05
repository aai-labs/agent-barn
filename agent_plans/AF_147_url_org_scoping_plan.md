# AF-147 — Org-in-URL scoping (UI) — Implementation Plan

## Goal

Move the active organization from a hidden global (Zustand store + `X-Organization-Id`
header) into the **URL**, so org context is a single source of truth. The org switcher
then becomes "swap the `[orgId]` segment and navigate", working uniformly on every
org-scoped page — fixing the root cause behind the members-page switcher bug rather than
patching it per page. Org context becomes bookmarkable/shareable and back-button-friendly.

## URL shape (decided)

`/dashboard/[orgId]/…` for org-scoped pages (least churn, keeps the dashboard mental
model; static segments resolve before the dynamic `[orgId]`, and org ids are UUIDs, so no
collision with the global routes below).

### Org-scoped → under `/dashboard/[orgId]/`
Scope is driven by the active org (`X-Organization-Id`), so these move:
- `/dashboard` (agents home) → `/dashboard/[orgId]`
- `/dashboard/agents/[id]` → `/dashboard/[orgId]/agents/[id]`
- `/dashboard/settings` (templates + skills) → `/dashboard/[orgId]/settings`
- `/dashboard/activity` → `/dashboard/[orgId]/activity`
- `/dashboard/users` → `/dashboard/[orgId]/users` *(org-scoped: the users list filters by
  the active org even for a superuser — confirmed in `get_paginated_users`)*
- members: `/dashboard/organizations/[id]/members` → `/dashboard/[orgId]/members`

### Global (no org prefix) — unchanged locations
- `/dashboard/organizations` — **all** orgs (superuser; `get_paginated_organizations`
  returns everything regardless of active org). Clicking a card → `/dashboard/[orgId]`.
- `/dashboard/account` — the signed-in user's own account.

### The old org-detail page
`/dashboard/organizations/[id]` (org info + stat tiles + delete + members) becomes the
current org's page. Fold it into `/dashboard/[orgId]/members` (org header + delete +
members list). Remove `/dashboard/organizations/[id]` and `/[id]/members` (the latter's
redirect too).

## Backend

No contract change — scoping already keys off the `X-Organization-Id` header. The header
value now originates from the URL instead of the store. (Optional later: a stricter
"header must match a real membership or 403" is already the behaviour via
`get_authenticated_user`.)

## Frontend changes

1. **Route moves** — create `app/dashboard/[orgId]/` and move the five org-scoped route
   folders under it; convert the org-detail component into the `[orgId]/members` page.
2. **`OrganizationProvider`** — derive the active org from the URL (`useParams().orgId` /
   pathname) and set `X-Organization-Id` from it (drop the store-driven header). On an
   org-scoped route with an `orgId` the user can't access (non-superuser, not a member),
   redirect to their default/first org. On global routes (no `orgId`), don't require one.
3. **Redirects / entry points**
   - `/dashboard` → `/dashboard/[lastUsedOrg ?? default ?? first]`.
   - `/` and post-login → same resolved org home.
   - Store shrinks to "remember last-used orgId" (per user) for these redirects only.
4. **Links** (~11 internal `href`/`router.push`) — thread the current `orgId`:
   top-nav, org-switcher, agents (hire-dialog-steps, config-drawer, agent-detail-page),
   organizations-grid (card → `/dashboard/[orgId]/members`), `app/page.tsx`,
   `not-found.tsx`, login-form redirect.
5. **`OrgSwitcher`** — replace the current `[orgId]` segment in the pathname and navigate
   (works everywhere); remove the members-page-only special case added earlier.
6. **Superuser** — all-orgs card → `/dashboard/[orgId]/members` (or `/dashboard/[orgId]`).

## Tests

- Update every e2e spec URL: `/dashboard/…` → `/dashboard/[orgId]/…` (page objects +
  specs). Bulk but mechanical.
- New e2e: switching org on an agents/settings page navigates + rescopes; `/dashboard`
  redirects to the resolved org; a forbidden `orgId` redirects (non-superuser).
- Backend suite is unaffected (header contract unchanged) — run to confirm.

## Definition of done

- Switching orgs works uniformly on every org-scoped page (navigation, not in-place).
- Deep-linking `/dashboard/[orgId]/…` loads that org's context directly (bookmarkable).
- Global admin (all orgs, account) unaffected.
- `make check-ui`, `pnpm tsc --noEmit`, full e2e green; backend suite green.

## Open questions / follow-ups

- `/dashboard/[orgId]/users` vs `/dashboard/[orgId]/members` now heavily overlap (accounts
  vs memberships+roles). Decide later whether to merge; out of scope here.
- Back-compat redirects for old `/dashboard/*` URLs: skip (internal app, no external
  links) except where trivial.
