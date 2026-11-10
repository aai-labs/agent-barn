# Tiers

## Read when

Read before changing the Tier catalog, its Platform Settings section, what a Tier allows or grants, an Organization's Tier, or any action a Tier Entitlement gates.

## Role in the system

A **Tier** is a named package from a catalog that Platform Administrators keep. It sets the price, the usage it grants, its Agent Limit, the Platforms its Agents may be reached on, and the features it allows. The public pricing page's Free, Cloud Tier 1, Cloud Tier 2 and Supervised Pilot are Tiers.

Tiers are being delivered as an epic ([`tiers/CHANGELOG.md`](tiers/CHANGELOG.md)). The catalog exists. Sign-up grants Free, which is the trial. A Platform Administrator can put an Organization on any Tier, and an Owner can subscribe to a paid one, today with a demo payment. A Tier sets the Organization's Agent Limit and what it may use, and what a Tier no longer covers is held until the Organization chooses what to keep. Organizations that were never trials are on no Tier and behave as before. Why the usage a Tier grants will be Credit rather than a renewing spend limit is in [its ADR](../adr/2026-11-08-tier-usage-is-credit.md).

## The catalog

Stored in `tier`, a Platform Resource. Each column:

| Column | Meaning |
| --- | --- |
| `key` | A stable slug (`free`, `cloud_1`), unique, set when the Tier is added and never changed. Links, analytics and the payment provider know a Tier by it. |
| `name`, `tagline` | What the Tier is called and the line shown with it. Names are unique, ignoring case and surrounding space. |
| `activation` | How an Organization comes to be on it, set when the Tier is added and never changed. See below. |
| `enabled` | Offered to new Organizations. Turning it off will move nobody already on it. |
| `sort_order` | Catalog order, then name. |
| `price_usd`, `price_note` | A paid Tier's monthly price, and how it reads beside the amount ("per month"). Informational on a contact-only Tier. |
| `monthly_usage_usd` | Credit granted on every paid month. What is unused expires when the month ends. |
| `one_time_credit_usd` | Credit granted once, when an Organization first comes onto the Tier. |
| `agent_limit` | How many live Agents an Organization on the Tier may run. |
| `allowed_platform_keys` | The Platforms its Agents may be reached on; null allows every Platform. Keys are those of the shipped Platform Plugins, so `web` is Web Chat and `agentbarn_telegram` is Agent Barn Telegram. |
| `features` | What else it allows: `custom_agents`, `integrations`, `templates_and_skills`, `workflows`, `agent_webhooks`, `agent_memory`, `team`, `priority_support` (display only). |
| `contact_url` | Where people go to ask for a contact-only Tier. |

Amounts are US dollars, stored as `NUMERIC(10,2)` and returned as decimal strings.

### Activations

- **`free`**: the system's Free Tier, the one self-signup will grant, once per inbox. It costs nothing and grants no monthly usage.
- **`paid`**: kept by a monthly subscription. It has a price above zero and is the only kind that grants monthly usage.
- **`contact`**: only a Platform Administrator assigns it, after a conversation; it is never activated automatically. It needs an `https` contact link and grants no monthly usage.
- **`none`**: the system's Tier for an Organization that has no Tier it may use. It is never offered, allows no Agents and grants nothing.

The database enforces each of these rules (`ck_tier_*`) and allows only one Free Tier and one none Tier (`uq_tier_system_activation`). The API checks the same rules first and answers `422`. An edit is checked against the values it keeps, so clearing a contact-only Tier's link is refused.

### What the migration seeded

Migration `55e07653f502` seeded the pricing page's Tiers, all switched off:

| Key | Price | Usage | Agents | Platforms | Features |
| --- | --- | --- | --- | --- | --- |
| `free` | — | $10 once | 1 | Agent Barn Telegram, Web Chat | `team` |
| `cloud_1` | $20 per month | $20 monthly, $10 once | 1 | All | All but `priority_support` |
| `cloud_2` | $100 per month | $100 monthly, $10 once | 4 | All | All |
| `pilot` (contact) | $500 per one-week pilot | — | 4 | All | All |
| `none` | — | — | 0 | None | None |

Tests reset the catalog to this seed (`SEED_TIERS` in `../../api/domains/tiers/models.py`); the migration keeps its own copy.

## Invariants

- **The system's Tiers stay.** Free and none cannot be deleted (`409`), and none cannot be changed at all (`409`). Free can be edited within its activation's rules, including its one-time credit, Agent Limit, Platforms and features.
- **A key and an activation never change.** An update carrying either is refused (`422`), because the Tier's identity elsewhere depends on them.
- **Changes apply live.** A change to a Tier's limits, Platforms or features applies at once to every Organization on it; a price change will apply to new subscriptions only.
- **Only the tiers domain knows about Tiers.** Other domains ask the `UsageGuard` and don't import `api.domains.tiers`; subscriptions, which change an Organization's Tier, may. Reads go through `UsageGuard.summary`, and sign-up, Organization creation and the trial settings through `OrganizationPlans` (`../../api/domains/usage/plans.py`), which `TierPlans` implements. `../../api/tests/unit/test_tier_boundary.py` enforces it.
- **Every change is audited.** `platform.tier.created` and `platform.tier.deleted` carry every value; `platform.tier.changed` records one Event per setting that moved, with amounts as numbers. An unchanged save records nothing. All three are Platform-scoped and reach the security audit.

## An Organization's Tier

`organization.tier_id` names the Tier an Organization is on (`ON DELETE RESTRICT`, so a Tier Organizations are on cannot be deleted: `409`). NULL means platform-managed: no Tier restricts it and it behaves exactly as before Tiers. Every existing Organization starts there.

A Platform Administrator puts an Organization on a Tier, or takes it off any, with `PUT /api/v1/platform/organizations/{id}/tier` (`{"tier_id": … | null}`) or the **Tier** card on the Platform Organization page. Any Tier in the catalog may be assigned, offered or not, including contact-only Tiers and none; an unknown Tier is `422`. The assignment sets `tier_assigned_by_platform`, so a later payment provider event will not replace it, and is audited as `organization.tier.changed`; assigning the Tier it is already on records nothing. What the Organization already runs is kept.

**Agent Limit.** On a Tier, the Agent Limit is the Organization's own limit when one was set, otherwise the Tier's `agent_limit`, otherwise the trial setting or the platform default as before ([Agent Limit](identity-and-organizations.md#agent-limit)). The none Tier allows no Agents.

**Reads.** The member-facing Organization read carries `tier` (id, key, name, activation, or null), `entitlements` (`features`, and `allowed_platform_keys` with null for every Platform; without a Tier, every feature and null), and `over_tier`. The Platform read carries `tier_id`, `tier_assigned_by_platform`, `tier` and `over_tier`. `over_tier` is true when the Organization already runs more than its Tier covers: more live Agents than its `agent_limit` that aren't on hold, an enabled Connection on a Platform it leaves out, Agent Memory on without `agent_memory`, or an enabled Agent Webhook without `agent_webhooks`. Once holds apply it is false again.

## Tier Entitlements

Domain services ask one question before new or more use: `UsageGuard.check(organization_id, action, subject)` (`../../api/domains/usage/guard.py`). They name the action (`UsageAction`, such as `CREATE_WORKFLOW` or `CONNECT_CHANNEL` with the Platform) and never the Tier or feature behind it. `TierUsagePolicy` (`../../api/domains/tiers/usage_policy.py`) is the guard's implementation, bound in `../../api/infrastructure/app.py`. It loads the Organization's Tier and chooses a strategy: no Tier is unrestricted, and any Tier is checked against its catalog row, where none allows nothing. Each action has one rule in `_RULES`: a feature, a Platform, the premade Agent or `custom_agents`, or a paid Tier for buying credit. `UsageGuard.allows` answers the same question without refusing, for filtering and for the Billing read's `upgrade_required`.

The check runs after authorization, so a caller who may not act at all still gets the ordinary `404` or `403`; it is not a Permission and is not part of any role. A refusal is `403` with:

```json
{"detail": {"code": "TIER_FEATURE_UNAVAILABLE", "message": "…", "feature": "integrations", "platform": null,
            "tier": "free", "upgrade_tier": {"key": "cloud_1", "name": "Cloud Tier 1"}}}
```

`upgrade_tier` is the first offered Tier, in catalog order, that allows it, or null when none is offered.

It refuses only **new or more** use. Reading, editing, disabling and deleting what an Organization already has stay allowed, so an Organization can always clean up.

| Entitlement | Refused |
| --- | --- |
| Platforms | Listing Platforms leaves out the ones the Tier doesn't allow; creating a Connection on one; enabling a disabled one; sending a Web Chat message without `web` (answering an approval the Agent asked for still works) |
| `custom_agents` | Hiring anything but the premade Agent (the platform Template `general-purpose` on Hermes); assigning Skills an Agent doesn't have yet, on hire or later; re-pinning an Agent to another Template; selecting a Template; starting a configuration override draft |
| `integrations` | Adding credentials for a provider an Agent doesn't have yet, on hire or later; a first SharePoint sign-in on an Agent; creating a shared credential; creating a Custom API connection; connecting a sync provider |
| `templates_and_skills` | Creating an Organization Template, or customizing a platform one the Organization has no copy of; creating or forking a Skill, Organization or Agent-owned; starting a Playbook Extraction |
| `workflows` | Creating a workflow; starting or re-running a run |
| `agent_webhooks` | Creating a webhook; enabling a disabled one |
| `agent_memory` | Turning Agent Memory on; creating a Memory Grant |
| `team` | Inviting a member |
| `priority_support` | Nothing; display only |

The web app reads `entitlements` from the Organization read and hides or explains what would be refused: the hire dialog and onboarding offer only the ready-made assistant without `custom_agents`, and each gated add, connect, invite or enable control is replaced by a short note naming the Tier.

## Tier Holds

What an Organization's Tier no longer covers is held: stopped or switched off, never deleted. Holds apply as soon as coverage drops, in the same request: when a Platform Administrator puts the Organization on a Tier, and when one edits a Tier's `agent_limit`, `allowed_platform_keys` or `features` (every Organization on it). Raising coverage releases nothing.

| What | Held means | Released by |
| --- | --- | --- |
| Agent | Suspended (`agent.suspended_at`, `suspension_reason` `tier`) and stopped. Every start path refuses it with `409` `AGENT_SUSPENDED` and `reason` `tier`, and it takes no place in the Agent Limit. Its configuration, volume, Connections and data stay. | An Owner or Admin releasing it while the Agent Limit has a place; it stays stopped until started |
| Connection | Suspended: `enabled` false, `suspended_at` set, `suspension_reason` `tier` | Enabling it again, which the Platform check allows once the Tier covers it |
| Agent Webhook | Suspended: `enabled` false, `suspended_at` set, `suspension_reason` `tier`; its ingress refuses jobs at once | Enabling it again |
| Agent Memory | `memory_enabled` false, `agent.memory_suspended_at` set, `memory_suspension_reason` `tier`; stored memories are kept, as when memory is turned off | Turning memory on again |

**Who writes what.** Each domain owns its Suspension: the Agent, Connection and Agent Webhook models have `suspend` and `resume`, and the Agent has `suspend_memory` and `resume_memory`. The tiers domain decides what to hold and calls them, in one transaction with the audit Event; enabling a Connection, Webhook or memory again resumes it in its own domain.

**Running Agents.** A held Agent that runs is stopped once the hold commits. A kept Agent that runs with a native Connection the hold switched off (Slack, Discord, Teams, Telegram) is restarted, since its runtime only drops the Connection at a start. A start under way when a hold lands finishes, then stops the Agent if it was held, or starts it again if one of its native Connections was. Anything else holding the Agent's lifecycle lock at that moment is caught by the Tier sweep, which stops every held Agent still running.

**What is kept.** The Agents within the Agent Limit in force (the Organization's own limit, else its Tier's) are kept, oldest first; the rest are held. Agents already held stay held, so a further drop holds among the kept ones.

**Choosing what to keep.** Owners and Admins hold the Organization's Permission `tier_hold.manage`. Under **Settings → Tier** they see the Organization's Tier and every held Connection, Webhook and Agent Memory, and, once an Agent is held or the Organization runs more than its Tier covers, every live Agent, kept or held. While the Tier covers everything there is nothing to choose, so the Agent list is hidden. To keep a different Agent they put a kept one on hold, which frees its place, then release the held one; a release without a place is `409`. The same section re-enables a held Connection, Webhook or Agent Memory once the Tier covers it. Members see an Agent's hold (`tier_held_at` on the Agent read, an **On hold** badge, a disabled Start) but can't change it.

| Route | Does |
| --- | --- |
| `GET /api/v1/organizations/{id}/tier-holds` | The Organization's live Agents with their holds, and its held Connections, Webhooks and Agent Memory |
| `POST /api/v1/organizations/{id}/tier-holds/agents/{agent_id}/hold` | Holds and stops one Agent |
| `POST /api/v1/organizations/{id}/tier-holds/agents/{agent_id}/release` | Releases one held Agent when there is a place |

Each hold or release is audited as `organization.tier_holds.changed`, with `reason` `tier` or `choice`.

**Known limits.**

- An Agent in the middle of another lifecycle operation when its hold applies is recorded as held but isn't stopped; it can't start again, and its owner stops it.
- A held native Connection (Slack, Telegram with its own bot, Discord, Teams) is disabled at once, but a running Agent built with it keeps that configuration until it next starts.
- A choice saved before a downgrade takes effect needs a scheduled downgrade, which arrives with subscriptions.

## Free and sign-up

Free is the trial: a Trial Organization is an Organization on the Free Tier, and the trial's credit and Agent limit are Free's `one_time_credit_usd` and `agent_limit` ([Trial onboarding](trial-onboarding.md#trials)). **Signup & trials** edits the same two values as **Tiers**.

A Google sign-up ([Identity and Organizations](identity-and-organizations.md#google-sign-in-and-self-signup)) lands on:

- **Free**, when self-signup is on, Free is offered with credit above zero, the shared Telegram bot is configured, the inbox never had Free, and the cap on active trials has room. This happens even when the visitor came for a paid Tier: they subscribe from Free.
- **none**, when Free can't be granted but there is something to buy (subscriptions are available and a paid Tier is offered): an inbox that already had Free, or a visitor who came for a paid Tier while trials are full or Free is unavailable. The Organization is on Credit from $0 and runs nothing until it subscribes; its owner may create Organizations as usual, since they had no trial to protect.
- Otherwise the refusal it got before (`trial_used`, `trials_full`, `signup_closed`).

**Further Organizations.** Under the same condition (subscriptions are available and a paid Tier is offered), an Organization created on Credit through `POST /organizations` lands on none too, unless it is an invited member's first one, which is their trial on Free ([Trial onboarding](trial-onboarding.md#trials)). Each Organization subscribes on its own. Organizations created on the platform's budget, or while nothing can be bought, have no Tier, as before.

An Organization on none sees **Choose a tier** on its empty Team page, linking to Billing, and no credit banner, since it has nothing to run. Subscribing refreshes the signed-in user, so the selector offers **Create organization** as soon as the subscription ends the trial.

`/signup?tier=<key>` carries the key in the signed Google state; a key that isn't offered is dropped. Onboarding opens at `/onboarding?tier=<key>` and preselects it.

**Credit on Free and none.** Neither buys credit: the Billing read says `upgrade_required` and Checkout answers `403` `TIER_UPGRADE_REQUIRED`. What they hold stays spendable.

**Existing trials** moved onto Free with the migration `86bca32c95be`. A trial running more than Free covers got 14 days (`organization.tier_holds_due_at`, on the Organization read and in **Settings → Tier**) to choose what to keep; the Tier sweep then applies the holds. Choosing earlier, or any later Tier change, clears the deadline.

## Subscriptions

A subscription (`organization_subscription`) keeps an Organization on a paid Tier; at most one per Organization is live. Its provider takes the payment, behind `SubscriptionProvider` (`../../api/domains/subscriptions/provider.py`); everything else (Tiers, credit, holds, audit) stays in `SubscriptionService`.

- **Stripe** takes new subscriptions wherever the platform takes payments (**Take payments** on, with both Stripe secrets; [operations](../guidelines/operations.md#payments-stripe)). Subscribing sends the Owner to Stripe's hosted Checkout; the subscription starts when Stripe reports it paid. Each paid Tier's monthly Price is found by its lookup key, the Tier's key, and a subscription is refused (`409`) while that Price doesn't charge what the Tier shows. Stripe renews, retries failed payments and cancels; its events drive the rest ([below](#stripe-events)).
- The **demo provider** takes them otherwise, where the deployment sets `TIERS_MOCK_PAYMENTS` ([operations](../guidelines/operations.md#tier-subscriptions-and-the-tier-sweep)): subscribing succeeds at once and charges nothing, and the Tier sweep renews it every 30 days.

Only an Owner (`billing.manage`) subscribes, and only an Organization on Credit whose Tier a Platform Administrator didn't choose (`409` otherwise).

| What happens | Effect |
| --- | --- |
| Subscribing | The Organization goes onto the Tier (`organization.tier.changed`, `assigned_by_platform: false`), its trial ends and frees its place under the cap, the Tier's one-time credit is granted unless the Organization already had a trial or Tier credit (once per Organization), and the period's allowance is granted. Holds apply if the Tier covers less than it ran. `organization.subscription.started` |
| Moving to a bigger paid Tier | Applies at once. Stripe charges the prorated difference now, and a declined card (`402`) changes nothing. The period's allowance is topped up to the new Tier's. `organization.subscription.changed` (`change: tier`) |
| Moving to a smaller paid Tier | Waits for the period's end (`scheduled_tier` on the read; a Stripe subscription schedule). Then the Organization moves to it, holds apply, and the new period's allowance is the smaller Tier's. Choosing the current Tier again before then takes it back. `organization.subscription.changed` (`downgrade_scheduled`, `downgrade_withdrawn`, then `tier`) |
| Cancelling | Ends with the period; it can be taken back until then, here or in Stripe's customer portal. A scheduled downgrade is dropped. The Billing page asks to confirm first and lists what Free would put on hold. `organization.subscription.changed` (`cancel_scheduled`, `cancel_withdrawn`) |
| A period's end | What is left of the period's allowance expires (`allowance_expiry`), spend counted against the allowance first; purchased, trial and one-time credit never expire. Then a cancelled subscription ends, and a live one renews (`organization.subscription.renewed`) with a fresh allowance once the new period is paid for |
| A failed renewal | The subscription is past due (`past_due_since`, `grace_ends_at` on the read) and keeps its Tier through the [payment grace period](#payment-grace-period), without the new period's allowance until it is paid. `organization.subscription.changed` (`payment_failed`, `payment_recovered`) |
| Ending | The Organization drops to Free with its credit kept, and holds apply. `organization.subscription.ended` |

Spend in a period is the spend the Billing balance counts, as of the last snapshot, minus what it was when the period began; healing that lands after a period ended is accepted drift (see [the ADR](../adr/2026-11-08-tier-usage-is-credit.md)). Stripe's periods are its own; the demo provider's are 30 days.

The **Tier sweep** (`tier-sweep` CronJob, `make run-tier-sweep`) ends demo periods that have run out, ends past-due subscriptions whose grace period is over (cancelling them at Stripe), and applies holds whose deadline has passed. A Platform Administrator ends a demo subscription's period at once with **End period now** on its Platform page (`POST /platform/organizations/{id}/subscription/end-period`); a Stripe subscription's is refused (`409`).

### Stripe events

The billing webhook (`/api/v1/billing/stripe/webhook`) passes subscription events to `StripeSubscriptionSync` (`../../api/domains/subscriptions/stripe_sync.py`): a subscription-mode `checkout.session.completed`, `customer.subscription.created|updated|deleted`, and `invoice.paid|payment_failed` for a subscription's invoice. Stripe sends events out of order and more than once, so an event only names the subscription: it is read from Stripe as it is now and Agent Barn's copy brought in line with it, under a lock per Stripe subscription that an Owner's tier change takes too. A paid subscription with no copy yet starts one; a new period renews; another Price moves the Tier; `past_due` or `unpaid` marks it past due, and paid again recovers it; a cancellation set in the portal is noted; `canceled` ends it. Applying the same state twice changes nothing. A subscription without Agent Barn's Organization in its metadata, or on a Price no paid Tier's key names, is acknowledged and ignored. A refund or dispute of a subscription payment doesn't change the Tier.

| Route | Does |
| --- | --- |
| `GET /api/v1/tiers` | Public: the offered Tiers that run Agents, in catalog order |
| `GET /api/v1/organizations/{id}/subscription` | The live subscription, or null |
| `POST /api/v1/organizations/{id}/subscription` | `{"tier_key": …}`: subscribe, or move to another paid Tier. Answers `outcome: active`, or `redirect` with where to pay once a payment provider takes payments |
| `POST /api/v1/organizations/{id}/subscription/cancel`, `/resume` | Cancel at the period's end, or take that back |
| `POST /api/v1/organizations/{id}/subscription/portal` | A link to Stripe's customer portal for the card, billing details and invoices (`404` for a demo subscription). Billing permission |
| `GET /api/v1/organizations/{id}/subscription/preview?tier_key=` | What moving to Free (a cancellation) or an offered paid Tier (a switch) would put on hold now; changes nothing. Billing permission |
| `GET`, `POST …/end-period` under `/api/v1/platform/organizations/{id}/subscription` | Platform Administrators read it, or end its period now |

The Billing read adds `tier`, `subscriptions_available`, `subscription_provider` (`stripe` or `mock`), `tier_assigned_by_platform` and `subscription`. The **Billing** page shows the tier, renewal date and allowance left, a scheduled downgrade with **Keep**, a failed payment and when the grace period ends, **Manage payment** for Stripe's portal, cancelling, and the offered Tiers to subscribe or switch to (contact-only ones link to their contact page). Confirming a cancellation or a switch lists what the new Tier would put on hold. While anything is held, the Team page says what, and links Owners and Admins to **Settings → Tier**. Onboarding's **Choose your tier** step comes first while subscriptions are available, or for an Organization on none; it offers continuing on Free, subscribing, or booking a call.

## Payment grace period

`platform_billing_settings.payment_grace_days` (0–60, default 7) is how long a subscription whose payment failed will keep its Tier before the Organization drops to Free. It is edited with the other billing settings ([Credit](credit.md#buying-credit)) and audited as `platform.billing_settings.changed`. The Tier sweep ends a subscription that has been past due for longer, cancelling it at Stripe, and the Organization drops to Free with its credit. Stripe's own retry settings should give up after the same time ([operations](../guidelines/operations.md#payments-stripe)). The demo provider never fails a payment.

## API

Under `require_platform_admin`, which refuses writes from a read-only API key.

| Route | Does |
| --- | --- |
| `GET /api/v1/platform/tiers` | The catalog, by `sort_order` then name, the system's Tiers included, each with `is_system` |
| `POST /api/v1/platform/tiers` | Adds a paid or contact-only Tier (`201`); `409` for a key or name already taken |
| `PATCH /api/v1/platform/tiers/{id}` | A partial edit; `tagline`, `price_note`, `allowed_platform_keys` and `contact_url` may be sent as null |
| `DELETE /api/v1/platform/tiers/{id}` | Removes a Tier that is not the system's and no Organization is on (`204`) |
| `PUT /api/v1/platform/organizations/{id}/tier` | Puts an Organization on a Tier, or takes it off any, and applies its holds (see above) |

The web app edits the catalog under **Platform → Settings → Tiers**: a table of the catalog with an **Offered** switch per Tier, and a dialog to add or edit one, whose fields follow the Tier's activation.

## Source map

| Concern | Source |
| --- | --- |
| Model, DTOs, rules and seed | `../../api/domains/tiers/models.py` |
| Persistence and audit Events | `../../api/domains/tiers/repository.py` |
| Catalog rules and errors | `../../api/domains/tiers/service.py`, `../../api/domains/tiers/routes.py` |
| The usage guard and the Tier's policy | `../../api/domains/usage/guard.py`, `../../api/domains/tiers/usage_policy.py`, called from each gated service |
| The plan on reads (Organization and Billing reads, the Agent Limit's Tier layer) | `UsageGuard.summary` in `../../api/domains/tiers/usage_policy.py`; DTOs in `../../api/domains/usage/models.py` |
| Tier Holds | `../../api/domains/tiers/holds.py`, `../../api/domains/tiers/repository.py`; each domain's `suspend` and `resume` on its model; the start refusal in `../../api/domains/agents/service.py` |
| Subscriptions, the provider seam (`SubscriptionProviders` picks the provider and says whether a paid Tier can be bought), the Tier sweep | `../../api/domains/subscriptions/` |
| Stripe: the provider, its events, the account setup, and the API calls | `../../api/domains/subscriptions/stripe_provider.py`, `../../api/domains/subscriptions/stripe_sync.py`, `../../api/domains/subscriptions/stripe_setup.py`, `../../api/infrastructure/stripe/subscriptions.py` |
| A new Organization's Tier (sign-up onto Free or none, further Organizations onto none) and the trial's terms on the Free row | `../../api/domains/tiers/plans.py`, behind `OrganizationPlans`; asked by `../../api/domains/auth/google_sign_in.py`, `OrganizationService.create_organization_for_current_user` and `TrialSettingsRepository` |
| Assignment by a Platform Administrator | `../../api/domains/tiers/assignment.py`, `../../api/domains/tiers/routes.py` |
| Migrations | `../../api/migrations/versions/55e07653f502_add_tier_catalog.py`, `../../api/migrations/versions/9b0aec4da777_add_organization_tier.py`, `../../api/migrations/versions/53961518cfc3_add_tier_holds.py`, `../../api/migrations/versions/86bca32c95be_free_replaces_the_trial.py`, `../../api/migrations/versions/38de1199ae19_add_subscriptions_and_allowance.py`, `../../api/migrations/versions/0c24c221ee1e_tier_holds_become_suspensions.py`, `../../api/migrations/versions/fa0322c6cd7a_scheduled_subscription_tier.py` |
| Platform Settings section, entitlement hook | `../../ui/src/features/tiers/` |
| Platform Organization Tier card | `../../ui/src/features/organizations/components/tier-card.tsx` |
| Settings → Tier | `../../ui/src/features/tiers/components/tier-holds-panel.tsx` |
| Billing subscription panel, onboarding tier step | `../../ui/src/features/billing/components/subscription-panel.tsx`, `../../ui/src/features/onboarding/components/tier-step.tsx` |
| Tests | `../../api/tests/unit/test_tier_usage_policy.py`, `../../api/tests/unit/test_tier_boundary.py`, `../../api/tests/integration/test_platform_tiers.py`, `../../api/tests/integration/test_organization_tiers.py`, `../../api/tests/integration/test_tier_holds.py`, `../../api/tests/integration/test_free_tier_signup.py`, `../../api/tests/integration/test_subscriptions.py`, `../../api/tests/integration/test_stripe_subscriptions.py`, `../../api/tests/integration/test_tier_catalog_migration.py`, `../../ui/tests/e2e/platform-tiers.spec.ts`, `../../ui/tests/e2e/organization-tiers.spec.ts`, `../../ui/tests/e2e/tier-subscriptions.spec.ts` |

## Change impact

A new feature key or Platform needs the API enums (`TierFeature`, `CommunicationPlatform`) and the UI's lists in `../../ui/src/features/tiers/utils.ts` to move together. Changing a seeded Tier's values needs a migration; `SEED_TIERS` must then match it.

A new action that adds or enables something a Tier restricts needs a `UsageAction`, its rule in `_RULES`, a `usage.check` call after authorization, a row in the table above, an integration test, and the matching UI control hidden through `useTierEntitlements`. A new kind of thing a Tier restricts also needs `over_tier`'s computation (`TierRepository.coverage`), a hold in `TierRepository.apply_holds`, its release path, and a list in Settings → Tier.

Another payment provider implements `SubscriptionProvider`, registers in `SubscriptionProviders`, and drives `activate`, `renew_period`, `apply_tier`, `set_payment_failed`, `note_cancel_at_period_end` and `finish` from its verified events, as `StripeSubscriptionSync` does. Changing a paid Tier's price needs its Stripe Price changed too: `make stripe-setup-tiers` creates a Price at the new amount and moves the lookup key to it, and existing subscribers keep paying the old one. A new paid Tier needs the same run before it can be subscribed to.
