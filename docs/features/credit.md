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
- **Only the balance limits.** No Organization own limit, Agent limit or default Agent
  limit applies on Credit ([Costs](costs.md#runtime-limit-management)).
- **Spend the team never counted still counts.** Cost healing prices calls LiteLLM
  recorded as free, so its team spend leaves them out. On Credit, everything healing has
  found since the Organization began lowers the limit pushed to the team and is added to
  the spend read back (alerts, the spend-limit read, the Billing balance), exactly as
  legacy memory spend is (`MemoryBudgetAccounting.spend_outside_team`). Healed memory
  charges on the legacy shared keys are already legacy spend and are not counted twice.
  A renewing limit is unaffected.
- **A proxy failure never refuses a grant.** The ledger is authoritative; the
  reconciler applies the ceiling to LiteLLM on its next pass.

Buying credit is also what converts a trial ([Trial onboarding](trial-onboarding.md#trials)):
it ends the trial without touching the ledger or the one-off window, and clears an expiry.

Organizations created by a Platform Administrator stay on renewing limits and have no
ledger.

## Buying credit

Only with `PAYMENTS_ENABLED` on (see [operations](../guidelines/operations.md#payments-stripe)),
and only for an Organization on Credit, by its Owner (`billing.manage`):

- `GET /organizations/{id}/billing` — whether it can buy credit, its credit, spend and
  balance, the platform's purchase bounds, and its credit history, newest first.
- `POST /organizations/{id}/billing/checkout {credit_usd}` — within the platform's
  minimum and maximum; returns a Stripe Checkout URL. The charge is the credit divided
  by the credit rate, plus the purchase fee, rounded up to the cent. Each Organization
  pays as one Stripe Customer, created on its first purchase. Nothing is granted here.
- `POST /billing/stripe/webhook` — Stripe's signed events; unsigned or wrongly signed
  ones are refused (400). A paid Checkout Session grants the credit in its metadata
  (keyed by the payment intent) and converts a trial. A refund or a dispute's withdrawn
  funds take back the share of that purchase's credit the amount bought (keyed by the
  refund or dispute id); a failed refund or reinstated funds give it back. Events that
  aren't ours are acknowledged and ignored.
- `GET`/`PUT /platform/settings/billing` — Platform Administrators set the minimum and
  maximum purchase, the credit rate (1.0: credit at cost) and the purchase fee percent;
  each change is audited as `platform.billing_settings.changed`.

In the web app, the Owner of an Organization that can buy credit gets a Billing tab
(`/dashboard/[orgId]/billing`): the balance, a "Buy credit" dialog that previews the
charge and sends them to Stripe, and the credit history. The spend-limit banner says when
an Organization on Credit has used it all and links the Owner to buy more. Platform
Administrators edit the billing settings in a Billing section of the platform settings
page. On Credit, the Spend limits settings show the credit without any limit to set
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

## Source map

| Concern | Source |
| --- | --- |
| Ledger model and grant DTO | `../../api/domains/organizations/models.py` (`OrganizationCreditGrant`, `CreditGrantCreate`) |
| Granting credit | `../../api/domains/organizations/llm_budget_service.py` (`grant_credit`), `../../api/domains/organizations/repository.py` (`grant_credit_with_event`) |
| Trial Credit at signup | `../../api/domains/auth/google_sign_in.py` |
| Buying credit | `../../api/domains/billing/`, `../../api/infrastructure/stripe/client.py` |
| Billing UI | `../../ui/src/features/billing/`, `../../ui/src/app/dashboard/[orgId]/billing/page.tsx` |
| Migration and opening balances | `../../api/migrations/versions/c5e2a7d91f04_credit_ledger.py` |
| Tests | `../../api/tests/integration/test_billing.py`, `../../api/tests/integration/test_credit_ledger.py`, `../../api/tests/integration/test_credit_ledger_migration.py`, `../../api/tests/integration/test_credit_spend_limits.py` |

## Change impact

Anything that writes an Organization on Credit's ceiling must go through the ledger,
or the next grant will silently overwrite it with the ledger's sum.
