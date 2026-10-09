# Trial onboarding

## Read when

Read before changing self-signup, Trial Organizations, Trial Credit, the onboarding
pages, or what a new user's Agent is set up with.

## Role in the system

Someone new signs in with Google and, within a couple of minutes, is talking to their own
Agent in Telegram through Agent Barn's shared bot. Signing in, the account, and the Trial
Organization are described in
[Identity and Organizations](identity-and-organizations.md#google-sign-in-and-self-signup);
the shared bot and account linking in the AF-367 entry of the
[Communications change log](communications/CHANGELOG.md). This page covers what happens
between them.

## Flow

The web app shows three steps: **Sign in → Telegram → Done**.

1. **Sign in** (`/signup`, or "Continue with Google" on `/login`). Google sign-in is the
   only way to sign up. A failure comes back to the page it started from, saying why,
   with nothing created.
2. **Telegram** (`/onboarding`). On opening, onboarding asks the API to set up the
   trial's Agent (`POST /onboarding/agent`). Each call does only what is still missing:
   - creates a Hermes Agent from the `general-purpose` template, named like the hire
     dialog names one ("Ava the Assistant");
   - gives it an enabled Agent Barn Telegram Connection — before starting it, because
     the runtime picks up its Connection when it starts;
   - starts it if it is stopped or failed. A failed start is recorded on the Agent and
     shown with a "Try again" that repeats the call.

   It runs as the user, through the same services and authorization as the dashboard.
   When the Agent is running, the step mints a link token, so "Open in Telegram" is a
   plain link the browser opens straight away. It polls until the user presses Start
   (linked), or until the 10-minute token expires, when a fresh link replaces it. Someone
   already linked goes straight to "Continue". The welcome message is the AF-367 one.
3. **Done**. "Continue" records `user.onboarding_completed_at`
   (`POST /onboarding/complete`). The summary shows the account, the linked Telegram
   username and the Trial Credit, with "Open Telegram" and "Go to dashboard".

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

Platform Administrators set the Trial Credit for new trials, the trial agent limit and
the cap on active trials on the platform settings page (`GET`/`PUT
/platform/settings/trial`, a singleton row; each setting that moves is audited as
`platform.trial_settings.changed`, a removed cap as `null`). The page also shows how many
trials are active. Until the first save, `TRIAL_DEFAULT_CREDIT_USD`, a limit of one Agent
and no cap apply. An active trial is any Organization still on a trial, including one
whose credit is spent. An existing trial's spend limit
is changed on its Organization page, like any other Organization's; the platform
Organizations list marks trials.

An Owner may delete their Trial Organization (after deleting its Agents). The delete
dialog warns that this ends the free trial for good: the address keeps its trial grant and
the user stays unable to create Organizations, so they land on `/no-organization` until
someone invites them to an Organization.

Ending a trial (409 for an Organization that is not one) stores the chosen spend limit
through the ordinary spend-limit path, then lifts the agent limit and, by recording
`trial_ended_at` on the trial's creator, their Organization-creation block, recording
`organization.trial.ended`. If the proxy can't take the new limit yet, the limit is still
saved for the reconciler and the trial still ends; the administrator gets the usual "saved,
not applied yet" 502. A trial is never left half-ended on a renewing budget. The trial's
spend so far counts against its first renewing period, for the team and its Agents' keys
alike, until their shared renewal (see [Costs](costs.md#organization-llm-budgets)). The
owner is not notified, and a trial cannot be restarted.

Signup is off unless `SELF_SIGNUP_ENABLED` is true and the environment has Agent Barn's
Telegram bot configured (`AGENTBARN_TELEGRAM_BOT_TOKEN` and `_USERNAME`), since a trial is
used through it (`?error=signup_closed` otherwise); existing users can always sign in with
Google. If setting up an Agent fails anyway (say the bot was removed later), onboarding
shows the API's reason with "Try again", and the API logs it. The chart default is off; the deploy workflows
read the `SELF_SIGNUP_ENABLED`, `STAGING_SELF_SIGNUP_ENABLED` and
`PUBLIC_SELF_SIGNUP_ENABLED` GitHub Variables, an unset one meaning off.

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
