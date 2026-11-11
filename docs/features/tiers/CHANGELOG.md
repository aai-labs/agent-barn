# Tiers — change log

Status: Active
Epic: Tiers from the public pricing page (Free, Cloud Tier 1, Cloud Tier 2, Supervised Pilot)
Related context: [Tiers](../tiers.md), [Credit](../credit.md), [Trial onboarding](../trial-onboarding.md), [Identity and Organizations](../identity-and-organizations.md), [ADR: a Tier's usage is Credit](../../adr/2026-11-08-tier-usage-is-credit.md)

## Current state

- Delivered:
  - the Tier catalog and its Platform Settings section, and the payment grace period setting;
  - an Organization's Tier, assigned by a Platform Administrator or kept by a subscription; Organizations that were never trials are on none and behave as before;
  - the Tier's Agent Limit as a layer beneath the Organization's own;
  - Tier Entitlement checks after authorization at every gate point, and the web app hiding what a Tier leaves out;
  - Tier Holds, applied as soon as coverage drops; Owners and Admins swap held Agents and re-enable held items under Settings → Tier;
  - Free is the trial: sign-up lands on Free or none, and further Organizations on Credit on none while a paid Tier can be bought, the trial's credit and limit live on the Free row, existing trials moved to Free, and Free and none can't buy credit;
  - the Credit Grant kinds for a paid Tier's one-time credit, allowance and its expiry;
  - subscriptions behind a provider seam: Stripe wherever payments are on (Checkout, upgrades charged now, downgrades at renewal, the customer portal, failed payments and the grace period), and a demo provider (`TIERS_MOCK_PAYMENTS`) otherwise; the Tier sweep, and End period now for demo subscriptions;
  - the onboarding tier step, `/signup?tier=` deep links, and the Billing page's subscription panel;
  - tier enforcement in one place: every gate and read asks the `UsageGuard`, new Organizations start through `OrganizationPlans`, Tier Holds are Suspensions each domain owns, and only the tiers and subscriptions domains import the tiers domain.
- In transition:
  - The live Stripe account isn't set up for subscriptions yet: `make stripe-setup-tiers` and the Dashboard's failed-payment retries, before paid Tiers are offered in production.
- Next: the Pilot contact card's platform polish, analytics and end-to-end flows (slice 8), deferred.
- Blockers: none. Decided on 2026-11-08:
  - Free replaces the trial, and existing trials move to Free.
  - Free can't buy credit and must upgrade.
  - Monthly usage expires each month.
  - A cancelled or finally unpaid subscription drops to Free, keeping its credit, after a configurable grace period.
  - After a downgrade the Owner chooses what to stop, and nothing is deleted; an upgrade lets it be re-enabled.
  - Free allows Web Chat (configurable) and invitations, but not Agent Memory.
  - The Pilot links to the existing intake form.
  - A Tier refuses only new or more use; what an Organization has stays readable, editable, disableable and deletable.
  - Without custom agents, only the premade Agent (`general-purpose` on Hermes) may be hired, and Templates can't be switched.
  - Holds apply as soon as coverage drops, keeping the oldest Agents; Owners and Admins choose, swap and re-enable through `tier_hold.manage`.
  - Until a payment provider exists, a deployment flag turns on demo payments, which behave like a provider's: cancelling waits for the period's end, and the sweep renews.
  - Self-signed-up Organizations whose trial had already ended stay on no Tier; only new sign-ups from an inbox that had Free land on none.
  - Free is offered by the migration exactly where self-signup was on.
  - The one-time credit is granted once per Organization, and migrated trials got 14 days to choose.
  - Without a choice, the oldest Agents are kept.
  - Decided on 2026-11-10: a bigger Tier applies at once and is charged the prorated difference; a smaller one waits for the renewal. No tax is collected for now. A refund or dispute of a subscription payment doesn't change the Tier.

## Planned slices

1. Catalog (delivered below).
2. Organization Tier and entitlements.
3. Holding Agents, Connections, memory and webhooks a Tier no longer covers; choosing what to keep; re-enabling.
4. Free replaces the trial. This covers sign-up onto Free or `none`, folding the trial settings into the Free row, the cap counting active Free Organizations, migrating trials, and refusing top-ups on Free.
5. Ledger kinds for the one-time credit, monthly usage and its expiry, with the period-end sweep.
6. Stripe subscriptions (delivered below). This covers Checkout, webhooks, the Customer Portal, the grace period and dropping to Free.
7. The onboarding Tier step, `?tier=` deep links, and the subscription panel on the Billing page.
8. The Pilot contact card, platform assignment UI, analytics, and end-to-end flows.
9. Tier enforcement in one place, in four behavior-preserving phases: (1) the usage guard and its strategies, with every gate moved onto it; (2) the read side and the Agent Limit's Tier layer; (3) Tier Holds as a suspended state each domain owns; (4) a new Organization's starting Tier decided in the tiers domain.

## Changes

### 2026-11-12 — Tiers — architecture review fixes (PR pending)

- Fixed:
  - An activation that stopped partway is finished by the provider's next event or the Tier sweep (`activated_at`), and a paid period without its allowance gets it; a grant that already landed is recorded rather than lost.
  - A Platform Administrator's assignment ends a live subscription first, so it stops charging, and a subscription's end keeps a Tier the platform chose.
  - An Agent already held loses the Connections, Webhooks and memory a lower Tier leaves out.
  - Lowering Free's credit or Agent limit under **Signup & trials** is a Free Tier change: audited as `platform.tier.changed`, with holds.
  - A second paid Stripe subscription, or one paid after the platform chose the Tier, is refunded and cancelled at Stripe.
  - `over_tier` counts Agents against the Agent Limit in force.
  - Every subscription change takes the Organization's subscription lock, a transaction-level advisory lock that a transaction-pooling proxy keeps on one connection.
- Changed:
  - the tiers and subscriptions packages no longer import each other: Tier assignment and `TierPlans` moved to the subscriptions domain;
  - assigning the Tier an Organization is already on, as the platform's choice, records the change of who chose it;
  - schema: the seven Tier migrations are squashed into three (`55e07653f502`, `86bca32c95be`, `38de1199ae19`); `organization_subscription.activated_at` is new. The revisions the entries below name no longer exist;
  - docs: `tiers.md`.

### 2026-11-10 — Tiers — Stripe subscriptions (PR pending)

- Delivered:
  - The Stripe provider: hosted Checkout to subscribe, each paid Tier's monthly Price found by its lookup key and refused unless it matches; upgrades charged the prorated difference at once (`402` on a declined card); downgrades on a subscription schedule at the period's end, which **Keep** takes back; cancelling at the period's end; the customer portal (`POST /organizations/{id}/subscription/portal`).
  - `StripeSubscriptionSync`: subscription events re-read the subscription from Stripe and apply it, under a lock per subscription, so repeats and out-of-order delivery change nothing.
  - Failed renewals: past due, the Tier kept through the payment grace period, the new period's usage granted once paid; the Tier sweep ends subscriptions past their grace and cancels them at Stripe.
  - The demo provider schedules downgrades the same way. The Tier sweep leaves Stripe's periods to Stripe, and End period now is for demo subscriptions only.
  - `make stripe-setup-tiers`: Products, Prices and the customer portal from the Tier catalog.
  - The Billing page: Stripe's Checkout and the return to it, a scheduled downgrade, a failed payment with its deadline, and **Manage payment**.
- Changed:
  - schema: migration `fa0322c6cd7a` (`scheduled_tier_id`, `provider_schedule_id` on `organization_subscription`);
  - API: `subscription_provider` on the Billing read; `scheduled_tier`, `past_due_since`, `grace_ends_at` and `manageable` on the subscription read; the portal route; inventory `api/developer_docs/operations-v1.json`;
  - operations: the webhook's subscription events, the key's added permissions, the setup target;
  - docs: `tiers.md`, `operations.md`, `.env.spec`.
- Follow-up: set the live account up before launch.

### 2026-11-10 — Tiers — Downgrade warnings and held Agents that keep running (PR pending)

- Delivered:
  - Billing asks to confirm a cancellation and a switch, listing what the new Tier would put on hold (`GET /organizations/{id}/subscription/preview`).
  - The Team page says what is on hold and links Owners and Admins to Settings → Tier.
  - A kept running Agent whose native Connection is held restarts without it; a start under way when a hold lands stops or restarts the Agent once it finishes; the Tier sweep stops held Agents still running.
- Changed: API inventory (`api/developer_docs/operations-v1.json`); docs: `tiers.md`, `agents.md`, `operations.md`.
- Follow-up: none.

### 2026-11-10 — Tiers — Tier enforcement in one place, phases 2–4 (PR pending)

- Delivered:
  - Phase 2: the Organization and Billing reads and the Agent Limit's Tier layer come from `UsageGuard.summary`; their DTOs live in `api/domains/usage/models.py`.
  - Phase 3: Tier Holds are Suspensions. Agents, Connections and Agent Webhooks own `suspend` and `resume`, the Agent its memory's; the tiers domain only decides what to hold.
  - Phase 4: `OrganizationPlans` (`TierPlans`) gives sign-up and Organization creation their starting Tier and the trial settings their terms; assigning a Tier moved to `TierAssignmentService`; the premade Template key moved to the templates domain.
  - `test_tier_boundary.py` allows only the tiers and subscriptions domains to import the tiers domain.
- Changed:
  - schema: migration `0c24c221ee1e` renames `tier_held_at` to `suspended_at` and `memory_tier_held_at` to `memory_suspended_at`, and adds the reasons, `tier` for every existing hold;
  - API: `suspended_at` and `suspension_reason` replace `tier_held_at` on the Agent, Connection, Agent Webhook and Tier Holds reads, `memory_suspended_at` and `memory_suspension_reason` replace `memory_tier_held_at`, and a held start answers `409` `AGENT_SUSPENDED` with `reason` instead of `AGENT_ON_TIER_HOLD`; the web app moved with them;
  - docs: `tiers.md`, `agents.md`, `CONTEXT.md`.
- Follow-up: none for the refactor.

### 2026-11-10 — Tiers — Tier enforcement in one place, phase 1 (PR pending)

- Delivered:
  - `UsageGuard` (`api/domains/usage/`): services name a `UsageAction` and never a Tier or feature.
  - `TierUsagePolicy`: loads the Organization's Tier, chooses the unrestricted or catalog strategy, and checks the action's rule. The premade-Agent rule moved out of the Agent service and the credit-purchase rule out of billing.
  - All 31 gate calls moved onto the guard, and the Platform list filters through it; responses are unchanged.
  - `test_tier_boundary.py` keeps other domains from importing the tiers domain.
- Changed: no schema or API change; docs: `tiers.md`, `INDEX.md`.
- Follow-up: phase 2, the read side.

### 2026-11-09 — Tiers — Free replaces the trial, subscriptions, and onboarding (PR pending)

- Delivered:
  - Sign-up onto Free, or onto none for an inbox that can't have Free when a paid Tier can be bought; `?tier=` from `/signup` through the Google state to onboarding.
  - Further Organizations created on Credit land on none while a paid Tier can be bought, and subscribe on their own; their empty Team page points to Billing.
  - The trial's credit and Agent limit stored on the Free row; Free offered where self-signup was on; existing trials on Free with 14 days to choose (`tier_holds_due_at`).
  - Credit purchases refused on Free and none (`TIER_UPGRADE_REQUIRED`).
  - `tier_credit`, `allowance` and `allowance_expiry` Credit Grants.
  - `organization_subscription` and `SubscriptionService` (subscribe, switch, cancel, resume, period end, renew, end to Free) behind `SubscriptionProvider`, with the demo provider; the Tier sweep (`tier-sweep` CronJob and Compose service, `make run-tier-sweep`) and End period now.
  - `GET /tiers`; the Billing page's subscription panel; onboarding's Choose your tier step; Gmail skipped where the Tier leaves out integrations.
- Changed:
  - schema: migrations `86bca32c95be` and `38de1199ae19`;
  - events: `organization.subscription.started|changed|renewed|ended`;
  - config: `TIERS_MOCK_PAYMENTS` / `tiersMockPayments`; chart: the `tier-sweep` CronJob (`tierSweep`);
  - API inventory: `api/developer_docs/operations-v1.json`;
  - docs: `tiers.md`, `trial-onboarding.md`, `credit.md`, `identity-and-organizations.md`, `domain-events.md`, `operations.md`, `INDEX.md`, `CONTEXT.md`.
- Follow-up: a payment provider (slice 6).

### 2026-11-08 — Tiers — Tier Holds and choosing what to keep (PR pending)

- Delivered:
  - `tier_held_at` on Agents, Connections and Agent Webhooks, and `memory_tier_held_at` on Agents.
  - Holds applied when a Platform Administrator assigns a Tier or edits one's coverage: the newest Agents beyond the Agent Limit are held and stopped, and Connections, Webhooks and Agent Memory the Tier leaves out are switched off. Nothing is deleted or released automatically.
  - A held Agent can't start (`409` `AGENT_ON_TIER_HOLD`) and takes no place in the Agent Limit.
  - `GET /organizations/{id}/tier-holds` and hold/release of one Agent, under the new Organization Permission `tier_hold.manage` (Owner and Admin); enabling a held Connection, Webhook or Agent Memory releases it.
  - Settings → Tier, the **On hold** badge, and a disabled Start for held Agents.
- Changed:
  - schema: migration `53961518cfc3`, including the `tier_hold.manage` Permission row;
  - events: `organization.tier_holds.changed`;
  - API inventory: `api/developer_docs/operations-v1.json` lists the three operations;
  - docs: `tiers.md`, `agents.md`, `identity-and-organizations.md`, the RBAC brief, `domain-events.md`, `CONTEXT.md`.
- Follow-up: Free replaces the trial.

### 2026-11-08 — Tiers — Organization Tier and entitlements (PR pending)

- Delivered:
  - `organization.tier_id` and `tier_assigned_by_platform`; `PUT /platform/organizations/{id}/tier` and the Platform Organization page's Tier card, audited as `organization.tier.changed`.
  - The Tier's `agent_limit` between the Organization's own limit and the trial or platform default.
  - `TierEntitlementService`: `403` `TIER_FEATURE_UNAVAILABLE` with the first offered Tier that allows it, after authorization, at every gate point listed in [Tiers](../tiers.md#tier-entitlements).
  - `tier`, `entitlements` and `over_tier` on the Organization reads; the web app hides or explains each gated control.
- Changed:
  - schema: migration `9b0aec4da777`;
  - events: `organization.tier.changed`;
  - API inventory: `api/developer_docs/operations-v1.json` lists the new operation;
  - docs: `tiers.md`, `identity-and-organizations.md`, the RBAC brief, `domain-events.md` (which also gains slice 1's `platform.tier.*` events), `CONTEXT.md`.
- Follow-up: Tier Holds and choosing what to keep.

### 2026-11-08 — Tiers — Catalog (PR pending)

- Delivered:
  - The Tier catalog (`tier`), seeded with Free, Cloud Tier 1, Cloud Tier 2, the contact-only Supervised Pilot and the system's none Tier, all off.
  - The rules for each activation, enforced in the database and the API.
  - Keys and activations that never change; Free and none never deleted, none never changed.
  - Audit Events for every change.
  - `GET/POST/PATCH/DELETE /platform/tiers`; Platform Settings → Tiers.
  - `payment_grace_days` (default 7) in the billing settings and their UI.
- Changed:
  - schema: migration `55e07653f502`;
  - events: `platform.tier.created|changed|deleted`;
  - API inventory: `api/developer_docs/operations-v1.json` lists the four operations;
  - docs: `tiers.md`, `credit.md`, `CONTEXT.md`, `INDEX.md`, and the ADR.
- Follow-up: Organization Tier and entitlements.
