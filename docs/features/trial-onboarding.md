# Trial onboarding

## Read when

Read before changing self-signup, Trial Organizations, Trial Credit, the onboarding
pages, or what a new user's Agent is set up with.

## Role in the system

Someone new signs in with Google, then chooses a ready-made assistant or configures
an Agent of their own. Signing in, the account, and the Trial Organization are described
in [Identity and Organizations](identity-and-organizations.md#google-sign-in-and-self-signup);
the shared bot and account linking in the AF-367 entry of the
[Communications change log](communications/CHANGELOG.md).

## Flow

`/login` and `/signup` share a welcome screen with Google sign-in followed by the
email and password login form, visible by default. Google is the only way to sign up.
Forgot, set, and reset password pages share its two-pane frame and return
to the welcome screen. Google failures return to their origin
with an explanation and nothing created.

Before the choices appear, a branded waiting screen loads onboarding status and
selects the trial Organization. It shows an animated mark and rotating previews of
the setup choices, respects reduced motion, and advances as soon as data is ready.
This stage does not create or start an Agent; errors retain the setup retry screen.
After completion, the ready screen retains this visit's setup summary and navigation
targets: the refreshed API status no longer includes the trial setup details.

After sign-in, `/onboarding` uses four steps: **Signed in → Choose how to start →
Connect Telegram or Set up your agent → You're ready**. Signed in is already complete.
The frame shows a step rail on desktop and compact progress on small screens; Trial
Credit appears in the desktop rail.

1. **Choose how to start**. Quick start is recommended and preselected. Build my own
   lets the user choose their Agent's name, runtime, template and model. The trial's
   Agent limit is shown when available. Opening onboarding creates no Agent.
   **I'll do this later** records completion and opens the dashboard without creating
   an Agent. The user can hire from the dashboard whenever ready.
   Both ready-made and custom hiring remain available from the dashboard afterward
   while the Organization remains on a trial;
   see [Hiring choices](agents.md#hiring-choices) for trial capacity and retry behavior.
2. **Quick start: Connect Telegram**. Only after Continue does the UI call
   `POST /onboarding/agent`. Each call does what is still missing: creates a Hermes
   Agent from `general-purpose`, names it like the hire dialog, gives it an enabled
   Agent Barn Telegram Connection before starting, and starts it if stopped or failed.
   Setup failures show an explanation and Try again.

   Once running, the step mints a link token. Open in Telegram is a plain link; desktop
   users can also scan its QR code. Status polling detects either route without a
   browser click. Pressing Start links the account; expired 10-minute tokens are
   replaced. Already-linked users can Continue. **Skip, I'll chat on the web** records
   completion and opens this Agent's Web Chat without requiring a Telegram link.
3. **Build my own: Set up your agent**. The wizard shares the hire dialog's form logic
   and ordinary create/start calls, including template-required Skills, group choices,
   credential validation, model inheritance and Hermes command approval. No quick-start
   Agent or Telegram Connection is created. A failed start retries the created Agent
   rather than consuming another trial slot. Back is available before creation.
   Templates are paginated in groups of six full cards, without an inner scrolling
   area. Previous/Next controls show the visible range; browsing preserves the selection,
   with the selected Template named below the grid.
   Template pages request six items from the API and use its total, so catalogs
   beyond the first API page remain reachable. The selected Template version,
   generated name, required Skills, and entered credentials persist while browsing.
   **I'll do this later** is also available here when no hire/start request is in flight;
   it creates no Agent and preserves any Agent already created by a failed start.
4. **You're ready**. Successful linking or hiring records `user.onboarding_completed_at`
   through `POST /onboarding/complete`. A completion failure retries only that save,
   without creating or starting another Agent. Quick start makes Go to dashboard
   the primary action, with Open Telegram as a secondary link that opens separately;
   Build my own offers Web Chat and a link to configure channels.

Returning with an existing Agent keeps that Agent: one with the shared Telegram
Connection can resume Quick start, while a custom Agent can finish and return to the
dashboard for any remaining setup. Neither recovery path hires another Agent.

All create, start and linking calls run as the current user in the trial Organization,
through the dashboard's existing authorization and validation. No API or schema changes
are required by the wizard.

`GET /onboarding` reports whether onboarding is still required: only for a self-signed-up
user who has not finished, acting in the first Organization they created. Everyone else —
invited and Platform-provisioned users, and anyone who finished — gets
`required: false`, and the web app sends them to the dashboard. `/dashboard` sends a
self-signed-up user back to `/onboarding` until they finish.

## Trials

| Rule | Where |
| --- | --- |
| One trial per email address, ever: signup records a hash of the lowercased address in `trial_grant`, kept when the account is deleted; a recorded address is refused (`?error=trial_used`) with nothing created | `../../api/domains/auth/google_sign_in.py`, `TrialSettingsService` |
| A self-signed-up user creates no Organizations until a Platform Administrator has ended their trial (`user.trial_ended_at`), so deleting the trial unlocks nothing; nor does anyone owning an active Trial Organization (403; the selector hides the option) | `OrganizationService.create_organization_for_current_user` |
| A Trial Organization runs at most the platform's trial agent limit, counted under a lock as an Agent is stored (409). The limit applies to existing trials at once; a trial over a lowered limit keeps its Agents but hires no more | `AgentRepository.create_with_creator_access`, `AgentService.create_agent` |
| At most the platform's cap on active trials exist at once, counted under a lock at sign-up; a sign-up past it is refused (`?error=trials_full`) with nothing created or recorded, so the address can come back. Ending or deleting a trial frees its place; no cap is the default | `GoogleSignInService._sign_up`, `TrialSettingsService.trials_full` |
| Trial Credit is a one-off Model Spend Limit | [Costs](costs.md#organization-llm-budgets) |
| A Platform Administrator ends a trial, choosing the spend limit and renewal window it goes on to | `POST /platform/organizations/{id}/end-trial` with `{budget_usd, budget_duration}`, the platform Organization page |

Platform Administrators enable or disable self-signup and set the Trial Credit for new trials, the trial agent limit and
the cap on active trials on the platform settings page under **Signup & trials** (`GET`/`PUT
/platform/settings/trial`, a singleton row; each setting that moves is audited as
`platform.trial_settings.changed`, a removed cap as `null`). The page also shows how many
trials are active. Until the first save, self-signup is disabled, Trial Credit is $0,
the Agent limit is one, and there is no cap. Self-signup requires positive Trial Credit.
Updates validate the combined persisted settings under a lock: administrators may enable
signup and set credit in one save, or disable signup and clear credit together. Zero
credit is refused while signup remains enabled; negative or non-finite credit is always
refused. A database constraint also enforces the positive-credit requirement. Signup
reads its enabled state and credit together and holds them stable until trial creation
commits. Changes apply without a restart. An active trial is any Organization still
on a trial, including one whose credit is spent. An existing trial's spend limit is changed on its Organization page, like any other Organization's; the platform
Organizations list marks trials.

An Owner may delete their Trial Organization (after deleting its Agents). The delete
dialog warns that this ends the free trial for good: the address keeps its trial grant and
the user stays unable to create Organizations and receives no automatic replacement until
someone invites them to an Organization or a Platform Administrator ends their trial restriction.

Ending a trial (409 for an Organization that is not one) stores the chosen spend limit
through the ordinary spend-limit path, then lifts the agent limit and, by recording
`trial_ended_at` on the trial's creator, their Organization-creation block, recording
`organization.trial.ended`. If the proxy can't take the new limit yet, the limit is still
saved for the reconciler and the trial still ends; the administrator gets the usual "saved,
not applied yet" 502. A trial is never left half-ended on a renewing budget. The trial's
spend so far counts against its first renewing period, for the team and its Agents' keys
alike, until their shared renewal (see [Costs](costs.md#organization-llm-budgets)). The
owner is not notified, and a trial cannot be restarted.

Signup is off unless a Platform Administrator enables it and the environment has Agent Barn's
Telegram bot configured (`AGENTBARN_TELEGRAM_BOT_TOKEN` and `_USERNAME`), because Quick start uses it (`?error=signup_closed` otherwise); existing users can always sign in with
Google. If setting up an Agent fails anyway (say the bot was removed later), onboarding
shows the API's reason with "Try again", and the API logs it. Signup policy and Trial
Credit are database-owned settings; deployment environment variables and Helm values
do not control them.

Organization invitations are emailed only: the API returns no set-password link to whoever
invites (`invite_link` is always null on Organization routes), so nobody can enroll an
address whose inbox they don't read. Platform Administrator provisioning still returns its
link.

There are no rate limits on the sign-in routes. In the shared cluster, Traefik sits
behind MetalLB with `externalTrafficPolicy: Cluster`, so the API never sees a visitor's
own address, and a per-address limit would throttle everyone together.

## Source map

| Concern | Source |
| --- | --- |
| Onboarding status and Agent setup | `../../api/domains/onboarding/service.py`, `../../api/domains/onboarding/routes.py` |
| Trial settings | `../../api/domains/onboarding/settings_service.py`, `../../api/domains/onboarding/repository.py` |
| Onboarding UI | `../../ui/src/features/onboarding/`, `../../ui/src/app/onboarding/page.tsx`, `../../ui/src/app/(auth)/signup/page.tsx` |
| Tests | `../../api/tests/integration/test_onboarding.py`, `../../api/tests/integration/test_trial_organizations.py`, `../../api/tests/integration/test_platform_trial_settings.py`, `../../ui/tests/e2e/trial-onboarding.spec.ts`, `../../ui/tests/e2e/platform-trials.spec.ts` |

## Change impact

The Agent a trial gets is the hire dialog's choice made for the user: changing the template,
runtime or naming here should stay consistent with it. Hermes and OpenClaw are both
first-class; trials start on Hermes only because the Agent is created for the user, and the
Agent Barn Telegram Connection works on both.

The dashboard ready-made option reuses the Telegram and completion steps in a
dialog after an explicit **Hire assistant** confirmation. It provisions a new Agent
through ordinary scoped Agent/Connection APIs and leaves onboarding completion
unchanged; see [Hiring choices](agents.md#hiring-choices).
