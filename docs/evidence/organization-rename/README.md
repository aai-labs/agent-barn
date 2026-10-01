# Organization rename execution evidence

Tested application commit: `50335fd12fe89541429a2e10875a991c499307d6`.
Date: 2026-09-30. Environment: local Linux, Node 24.15.0, pnpm 11.17.0,
Next.js development server at `http://127.0.0.1:3003`, Playwright Chromium,
1280×720 viewport. All identities shown are synthetic fixtures.

## Boundary and limitations

This exercises the real rendered UI and shared API client with deterministic
HTTP interception using the repository's Playwright support. Authentication and
organization endpoints are mocked to isolate the UI and force failure/pending
states safely. It does not establish real database persistence or live-backend
authorization. The existing backend endpoint and permission policy are unchanged;
no live deployment smoke test was performed.

## Results

From `ui/`:

```sh
pnpm exec playwright test tests/e2e/organizations.spec.ts --project chromium
```

25 tests passed, including Owner/Admin rename, trimmed name in the heading and
selector, validation, failed-save retention, and cancellation. Adjacent organization
creation, deletion, invitations, member management, and switching also passed.
The full organization suite was rerun together with two temporary exploratory
scenarios at the tested commit: 27 passed in 17.6 seconds.

Exploratory scenarios used a temporary Playwright spec, reusing `DataSupport` and
`OrganizationDetailPage`, with screenshots taken after disabling CSS animations:

- Open management page → Rename organization: current name prefilled; inspected
  label, focus, Cancel and Save buttons. [Dialog screenshot](rename-dialog.png).
- Empty name → Save: inline minimum-length error. The committed validation test
  also rejects whitespace-only, two-character, and 256-character names.
- Hold PATCH response pending: input, Cancel, and Saving button disabled;
  Escape leaves the pending dialog open. Release response: dialog closes.
- Successful save: heading and selector both show the new name.
  [Saved screenshot](renamed.png).
- Ordinary Member navigates directly to management URL: redirected to organization
  home, with no Rename control.
- Platform Administrator with only Member memberships: the management heading
  renders but Rename is absent (separate exploratory run: 1 passed).

## Red/green evidence

Kept the same three committed rename tests and temporarily replaced only
`organization-detail.tsx` with its `origin/staging` version. All three failed
at `OrganizationDetailPage.openRename`: the visible Rename organization button
was absent (15-second locator timeout). Restored the candidate source; all three
passed in the full suite above. This is a UI feature-removal check, not a claim
that the entire checkout was switched to the baseline.

## Compatibility

Uses existing `PATCH /api/v1/organizations/{id}` with only `{name}`. No schema,
API, dependency, configuration, migration, or deployment-order change. Existing
names prefill the editor; surrounding whitespace is trimmed on save. Ordinary
UI rollout applies; reverting the UI commits removes the editor while saved
names remain valid existing backend data.

ADR: N/A — this adds a reversible UI control to an existing API and permission
contract. Epic changelog: N/A — this is not a slice of an active multi-PR epic.
Current behavior is documented in `docs/features/identity-and-organizations.md`.
