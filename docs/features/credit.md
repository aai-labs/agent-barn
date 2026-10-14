# Credit

## Read when

Read before changing how an Organization on Credit is granted, charged or limited: the
credit ledger, Trial Credit, purchases, refunds, or the limits allowed beneath Credit.

## Role in the system

An Organization on Credit pays for model spend in advance, as with OpenRouter credits.
Its Model Spend Limit is one-off (`once`, see [Costs](costs.md#runtime-limit-management)):
everything it has been granted, never renewed. Trial Organizations start on Credit; the
delivery state of buying it is tracked in the [Credit change log](credit/CHANGELOG.md).

## Invariants

- **The ledger adds up to the ceiling.** Every change to an Organization's Credit is an
  `organization_credit_grant` row, and the Organization's `llm_budget_usd` is their sum,
  written in the same transaction under the Organization's row lock. A Platform
  Administrator who sets the ceiling of an Organization on Credit records the difference
  as an adjustment rather than overwriting it.
- **The ceiling is never negative; the Credit Balance can be.** Spend is counted against
  the ceiling, so a chargeback of credit already spent leaves the balance below zero and
  the next grant pays that off first.
- **A payment is granted once.** A grant's `external_ref` is unique; a grant whose
  reference was already granted changes nothing.
- **Signs follow kinds.** A purchase adds credit, a refund or chargeback takes it off,
  Trial Credit is zero or more; an adjustment may go either way.
- **Only the balance limits spend.** No Organization own spend limit, per-Agent spend
  limit or default per-Agent spend limit applies on Credit
  ([Costs](costs.md#runtime-limit-management)). How many Agents it may run (its Agent
  limit, see [Identity and organizations](identity-and-organizations.md)) is separate and
  still applies.
- **Spend the team never counted still counts.** Cost healing prices calls LiteLLM
  recorded as free, so its team spend leaves them out. On Credit, everything healing has
  found since the Organization began lowers the limit pushed to the team and is added to
  the spend read back (alerts, the spend-limit read, the Billing balance), exactly as
  legacy memory spend is (`MemoryBudgetAccounting.spend_outside_team`). Healed memory
  charges on the legacy shared keys are already legacy spend and are not counted twice.
  The cost sync pushes the limit of each Organization on Credit it healed spend for as
  soon as its healing pass ends, rather than waiting for the reconciler. A renewing
  limit is unaffected.
- **A proxy failure never refuses a grant.** The ledger is authoritative; the
  reconciler applies the ceiling to LiteLLM on its next pass.

Buying credit is also what converts a trial ([Trial onboarding](trial-onboarding.md#trials)):
it ends the trial without touching the ledger or the one-off window, and clears an expiry.

Ending a trial (by a purchase, or by a Platform Administrator) lets its owner create
further Organizations. With self-signup on, only accounts a Platform Administrator set up
(`user.platform_provisioned_at`, set by `POST /platform/users` and for Platform
Administrators, and backfilled for every account that existed before and didn't sign
itself up) create Organizations on renewing limits. Everyone else's new Organizations,
whether they signed themselves up or were invited by an Organization, run on Credit. An
invited member whose address has never had a trial gets a trial as their first
Organization of their own (the trial credit and Agent limit, counted against the cap on
active trials, and their address recorded as having had its trial; refused with 409 when
no trials are available). Otherwise it starts with no credit (an opening adjustment of
$0): either way it spends only what it was given or bought, never the platform's budget. Without this, a trial's owner could invite an address
of their own and create Organizations on the platform's budget from it. With self-signup
off, every account traces back to a Platform Administrator or an Organization they set
up, so every Organization a user creates gets the platform's renewing limit, as before.

## Buying credit

New purchases need `PAYMENTS_ENABLED` on (see [operations](../guidelines/operations.md#payments-stripe)),
an Organization on Credit, and someone holding `billing.manage` (its Owner). With
payments off, the billing read still answers (`available: false`) and the webhook keeps
landing payments already made, refunds and disputes, as long as the deployment has a
webhook secret.

- `GET /organizations/{id}/billing` — whether it can buy credit (`available`), whether
  it runs on Credit at all (`on_credit`), its credit, spend and balance, the platform's
  purchase bounds, and its credit history, newest first, with who bought each purchase
  (null when the buyer can't be named).
- `POST /organizations/{id}/billing/checkout {credit_usd}` — within the platform's
  minimum and maximum; returns a Stripe Checkout URL. The charge is the credit divided
  by the credit rate, plus the purchase fee, rounded up to the cent, computed in exact
  fractions; a charge below Stripe's $0.50 minimum is refused (400), and Stripe failing
  is a 503 that says to try again. A second purchase updates the Stripe Customer's
  email to the current buyer, so receipts follow ownership changes. Each Organization
  pays as one Stripe Customer, created on its first purchase. The buyer's user id goes
  in the session's metadata with the Organization and the credit. Nothing is granted here.
- `POST /billing/stripe/webhook` — Stripe's signed events; unsigned or wrongly signed
  ones are refused (400). Stripe doesn't deliver events in order, so:
  - Checkout records every session it creates (`billing_checkout`: the credit, the
    charge, the Organization and the buyer). A paid Checkout Session grants what that
    record says, keyed by the payment intent, and converts a trial, but only when the
    session matches it: a one-off payment, in US dollars, with a payment intent, for the
    same Organization, for exactly the recorded charge. The session's own metadata is
    never trusted for the amount, since anyone with access to the Stripe account (or a
    leaked key) could write it. A session that doesn't match, one we never created, or
    one for an Organization no longer on Credit grants nothing and is recorded as
    `platform.credit_purchase.unapplied`, with the reason, for someone to refund.
  - Any refund event (`refund.created`, `refund.updated`, `refund.failed`) settles the
    refund on its status as Stripe has it now: credit taken back while it stands (its
    share of the purchase, keyed by the refund id), given back once it has failed or
    been cancelled.
  - A dispute's withdrawn funds take back their share; reinstated funds give back the
    reinstated share, after first taking back the withdrawal if that event hasn't
    arrived yet.
  - A refund or dispute for a credit purchase that hasn't been recorded yet is answered
    with a 409, so Stripe sends it again. Events that aren't ours (no credit purchase
    behind them) are acknowledged and ignored.
- `GET`/`PUT /platform/settings/billing` — Platform Administrators set the minimum and
  maximum purchase, the credit rate (1.0: credit at cost) and the purchase fee percent;
  each change is audited as `platform.billing_settings.changed`.
- `GET /platform/billing/credit-history?kind=&organization_id=&page=&page_size=` —
  Platform Administrators read every Organization's Credit Grants, newest first, with
  the Organization, who made each change and the payment reference.

In the web app, the Owner of an Organization that can buy credit gets a Billing tab
(`/dashboard/[orgId]/billing`): the balance, a "Buy credit" dialog that takes dollars and
cents, previews the charge and sends them to Stripe, and the credit history. Coming back
from paying, the page reads again every 5 seconds for a minute, says when the credit has
arrived (and refreshes the spend-limit banner), or that the payment is still being
processed; the address is cleaned, so a reload doesn't repeat the message. The spend-limit banner says when
an Organization on Credit has used it all and links the Owner to buy more. Platform
Administrators edit the billing settings in a Billing section of the platform settings
page, and read every Organization's credit history on the platform Billing page
(`/dashboard/platform/billing`), filtered by kind or Organization. On Credit, the Spend limits settings show the credit without any limit to set
beneath it.

When an Organization on Credit runs out with payments on, its Agents' reply says so and
names the remedy, on Hermes and OpenClaw alike: "This organization has used all its
credit, so this agent cannot reply right now. Ask the organization's owner to buy more
credit in Billing." The API starts each Agent's pod with `AGENTBARN_SPEND_LIMIT_KIND`
(`credit` or `limit`); both in-pod healthz proxies (`../../api/domains/agents/scripts/hermes/healthz-server.py`,
`../../api/domains/agents/scripts/openclaw/healthz-server.js`) pick the reply and record
`CREDIT_EXHAUSTED` instead of `SPEND_LIMIT_REACHED`, which
`../../api/domains/communications/error_details.py` turns into the same notice. The kind
is read when the pod starts, so an Organization that changes kind gets the new wording
on its Agents' next restart.

Card details never reach Agent Barn: payment happens on Stripe's page. Credit is
granted only by a verified event, never by the browser returning from Checkout.
Stripe can email receipts itself; the Billing page shows the credit history without
receipt links. Credit is in US dollars only.

## Accepted risks

- **A purchase later disputed still converts the trial.** Someone can buy the minimum,
  then dispute the charge: the chargeback takes the credit back, but the Organization
  stays converted (no longer a trial, the default Agent limit instead of the trial's,
  and its owner may create Organizations, which run on Credit from $0). Nothing here
  spends the platform's budget, since every one of those Organizations is held to its
  own credit, and the payment provider charges the dispute fee either way. Converting
  only after the dispute window (up to 120 days) would penalise every honest buyer.

## Source map

| Concern | Source |
| --- | --- |
| Ledger model and grant DTO | `../../api/domains/organizations/models.py` (`OrganizationCreditGrant`, `CreditGrantCreate`) |
| Granting credit | `../../api/domains/organizations/llm_budget_service.py` (`grant_credit`), `../../api/domains/organizations/repository.py` (`grant_credit_with_event`) |
| Trial Credit at signup | `../../api/domains/auth/google_sign_in.py` |
| Buying credit | `../../api/domains/billing/`, `../../api/infrastructure/stripe/client.py` |
| Billing UI | `../../ui/src/features/billing/`, `../../ui/src/app/dashboard/[orgId]/billing/page.tsx` |
| Migration and opening balances | `../../api/migrations/versions/c5e2a7d91f04_credit_ledger.py` |
| Tests | `../../api/tests/integration/test_billing.py`, `../../api/tests/integration/test_healed_credit_spend.py`, `../../api/tests/integration/test_credit_ledger.py`, `../../api/tests/integration/test_credit_ledger_migration.py`, `../../api/tests/integration/test_credit_spend_limits.py` |

## Change impact

Anything that writes an Organization on Credit's ceiling must go through the ledger,
or the next grant will silently overwrite it with the ledger's sum.
