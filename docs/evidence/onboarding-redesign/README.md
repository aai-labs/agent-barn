# Onboarding and signup settings evidence

Application commit: `1ede6ddb44cbb8d29a4bcab0d11641bbc5c5e282`.
Captured on 2026-10-14 with local Next.js, Playwright Chromium, and the
repository's DataSupport/Page Object fixtures. Desktop viewport: 1440 × 1050;
mobile: 390 × 844. All identities, trial settings, Templates, Telegram accounts,
and QR/link tokens shown are synthetic test fixtures.

## Screenshots

| Evidence | Behavior shown |
| --- | --- |
| [Welcome](welcome.png) | Google sign-in and the default email/password form |
| [Onboarding choices](onboarding-choices.png) | Quick start, custom setup, and deferral |
| [Mobile choices](onboarding-choices-mobile.png) | Compact progress and accessible actions on mobile |
| [Template pagination](onboarding-template-pagination.png) | Six complete cards, range 7–12 of 20, selected Template, runtime icons, and deferral |
| [Trial hiring choices](trial-hiring-choices.png) | Neither choice selected before an explicit decision |
| [Ready-made confirmation](ready-made-confirmation.png) | Explanation and Hire assistant action; opening the dialog creates no Agent |
| [Telegram setup](telegram-setup.png) | Locally rendered QR code, linking instructions, and optional Web Chat |
| [Telegram completion](telegram-complete.png) | Go to dashboard is primary; Open Telegram is secondary |
| [Non-trial hiring](non-trial-custom-hiring.png) | Ordinary and former Trial Organizations open the full custom form directly |
| [Signup settings](platform-signup-settings.png) | Database-owned signup switch and Trial Credit in platform settings |

## Capture boundary

Six temporary exploratory Playwright scenarios exercised the rendered application
and shared HTTP client using deterministic request interception. All six passed.
The screenshots were inspected after capture. CSS animations were disabled during
capture and the Next.js development indicator was hidden. Product content was not
altered or composited. The temporary capture spec is not part of the product diff.

These screenshots establish UI behavior, not live Google/Telegram integration,
real account creation, or database persistence. Existing fixture trials show $10
while the example admin settings show $20: credit changes apply to new trials.

## Verification

- Full production browser suite: 789 passed, zero retries, at `576609f6`.
- Final UI eligibility change: 105 affected tests passed at `1ede6ddb`:
  `pnpm exec playwright test tests/e2e/dashboard-page.spec.ts tests/e2e/hire-dialog.spec.ts tests/e2e/ready-made-agent.spec.ts tests/e2e/trial-onboarding.spec.ts --project=chromium` (from `ui/`).
- Full API validation earlier in the branch: 4,850 unique cases passed, one expected
  empty-provider skip, including 19 Kubernetes cases, at `39099878`.
- Subsequent persisted signup-policy change: 106 unique relevant API cases passed
  across platform trial settings, Google sign-in, onboarding, trial Organizations,
  and migration tests. This was an affected-suite rerun, not a second full API run.
- API Ruff/format/type checks, migration head, UI ESLint/TypeScript, Helm memory
  isolation/authentication checks, and whitespace checks passed.
- Independent GPT-6.1-sol quality reviews approved the full feature and subsequent
  fixes; no required or optional findings remain.

Migration `c61a94e72b30` adds the persisted signup flag and positive-credit
constraint. Signup defaults off and requires positive credit to enable; configure
it in Platform settings → Signup & trials. The old environment/GitHub/Helm signup
controls and default-credit environment fallback are removed. Existing trials
keep their credit; signup closure does not end a trial.
