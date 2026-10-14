# Prepaid credit top-ups — change log

Status: Active (all slices delivered on the branch; awaiting review)
Epic: [AF-381](https://aai-labs.atlassian.net/browse/AF-381)
Related context: [Credit](../credit.md), [Costs](../costs.md), [Trial onboarding](../trial-onboarding.md)

## Current state

- Delivered: Organizations on Credit are limited by their balance alone; a credit
  ledger whose sum is their ceiling, with Trial Credit recorded at signup; an Agent
  Limit for every Organization; trial expiry when Trial Credit runs out, and a
  system-triggered trial conversion for the payment provider to call; buying credit
  through Stripe, with a Billing page, platform billing settings and an out-of-credit
  banner that links to buying more; the out-of-credit reply on Hermes and OpenClaw;
  healed spend counted against credit; a platform default Agent limit; and the review
  fixes of 2026-10-14.
- In transition: none; rebased onto staging, which now includes AF-368.
- Next: the PR into staging.
- Blockers: none. A Stripe sandbox exists for manual testing.

## Changes

### 2026-10-14 — AF-381 — Third review fixes (PR pending)

- Delivered:
  - Web Chat shows running out of credit as a failure under the person's message, as it
    does a spent limit, on both runtimes.
  - An invited member whose inbox took its trial while their first Organization was
    being created is told to try again (409), and the retry starts on credit.
  - A payment that granted no credit goes on the platform audit log once, and its refund
    or dispute is acknowledged instead of being sent again for days.
  - The deploy comments say an empty `ORGANIZATION_DEFAULT_AGENT_LIMIT` means 10.
- Changed: migration `d4a7c2e9f150_billing_unapplied_payments`.
- Accepted: a trial recorded before addresses were normalised blocks only its exact
  spelling (staging data only).

### 2026-10-14 — AF-381 — First Organization trial for invited members (PR pending)

- Delivered: with self-signup on, an invited member whose address has never had a trial
  gets a trial as their first Organization of their own, counted against the cap and
  recorded against their address; when no trials are available they're told so. After
  that, or with an address that had a trial, Organizations start on credit at $0.
- Changed: `OrganizationRepository.create_for_user` takes the opening credit's kind and a
  hook that runs in its transaction.
- Decided: a purchase later charged back still converts the trial (accepted risk, see
  [Credit](../credit.md#accepted-risks)).

### 2026-10-14 — AF-381 — Credit rule only with self-signup (PR pending)

- Delivered: Organizations of accounts the platform didn't set up run on credit only
  when self-signup is on; deployments without it keep the platform's renewing limit for
  every Organization a user creates.
- Upgrade note for operators: every Organization that isn't a trial now has an Agent
  limit. It defaults to 10 (was unlimited when `ORGANIZATION_DEFAULT_AGENT_LIMIT` was
  unset); change it in Platform Settings → Organizations or with the variable.
- Follow-up: none.

### 2026-10-14 — AF-381 — Security review fixes (PR pending)

- Delivered:
  - Only accounts a Platform Administrator set up create Organizations on the
    platform's budget; everyone else's run on Credit from $0, closing the route where a
    trial's owner invited an address of their own.
  - Checkout records every session it creates, and the webhook grants only what that
    record says, after checking the payment is a one-off, in US dollars, for the same
    Organization and exactly the recorded charge, with a payment reference.
  - A webhook secret without the secret key refuses to boot, and a missing key at
    runtime answers 503 so Stripe retries rather than dropping refunds.
  - The webhook reads its body in a stream and stops at 256 KB.
  - Receipts go to the current buyer.
  - The platform billing settings ask for confirmation before saving, and warn when
    credit would sell below cost.
- Changed: migrations `b8e5f3a1c207_platform_provisioned_users` and
  `c9f6a4b2d318_billing_checkouts`; `platform.credit_purchase.unapplied` carries a
  `reason`.
- Follow-up: a request body limit for the whole API at the ingress.

### 2026-10-14 — AF-381 — Review fixes (PR pending)

- Delivered:
  - Organizations created by a self-signed-up user once their trial ends run on Credit,
    starting with none, so a $5 purchase no longer unlocks Organizations on the
    platform's budget.
  - Exact checkout pricing (no extra cent); a $0.50 minimum; Stripe failures at checkout
    are a 503 that says to try again; payments on without both Stripe secrets refuses to
    boot.
  - The webhook stays served while payments are off, settles refunds on their current
    status (including `refund.updated`), retries refunds and disputes that arrive before
    their purchase, gives back only the reinstated share of a dispute, and records a
    payment for an Organization no longer on Credit as `platform.credit_purchase.unapplied`.
  - A default Agent limit of 10 when `ORGANIZATION_DEFAULT_AGENT_LIMIT` is unset, and a
    platform setting that replaces it (`/platform/settings/organizations`).
  - Healing pushes credit limits as soon as it finds spend; the trial-expiry backfill
    uses the 100% alert, as the live handler does.
  - Billing page: dollars and cents accepted; what happened after paying (arrived, still
    processing), shown once; no balance for an Organization on a renewing limit; empty
    states; a plain message for anyone without access; the payment provider's name no
    longer shown.
  - Billing no longer imports Organizations models, and sign-up opens trial credit
    through a service.
- Changed: migration `a7d4e2c9b816_platform_organization_settings`; Stripe webhook events
  (add `refund.updated`); a restricted Stripe key also needs read access to Refunds and
  PaymentIntents.
- Follow-up: none.

### 2026-10-13 — AF-381 — Healed spend on credit (PR pending)

- Delivered: on Credit, spend that cost healing found but LiteLLM's team never counted
  lowers the team's limit and counts in spend, alerts and the balance.
- Changed: `CostRepository.healed_spend`, `MemoryBudgetAccounting.spend_outside_team`
  (replacing `legacy_spend` at its four call sites); docs (`credit.md`).
- Follow-up: none.

### 2026-10-13 — AF-381 — Out-of-credit reply (PR pending)

- Delivered: on Hermes and OpenClaw, an Agent of an Organization on Credit that has run
  out tells the person chatting to have the owner buy more credit.
- Changed: runtime (`AGENTBARN_SPEND_LIMIT_KIND` pod env; both healthz proxies;
  `CREDIT_EXHAUSTED` in `error_details.py`); docs (`credit.md`).
- Follow-up: a change of kind reaches running Agents on restart.

### 2026-10-13 — AF-381 — Billing UI (PR pending)

- Delivered: the Owner's Billing tab and page (balance, buy credit, history with who
  bought each purchase; it re-reads for a minute after a payment); a Billing
  section on the platform settings page; a platform Billing page listing every
  Organization's credit history (`GET /platform/billing/credit-history`); the spend-limit banner speaks of credit and
  links the Owner to buy more.
- Changed: UI (`ui/src/features/billing/`, top nav, spend-limit banner, platform
  settings); docs (`credit.md`).
- Follow-up: receipt links on the history (Stripe emails receipts meanwhile).

### 2026-10-13 — AF-381 — Stripe backend (PR pending)

- Delivered: `PAYMENTS_ENABLED`; billing platform settings (purchase bounds, credit
  rate, purchase fee); the Owner-only `billing.manage` Permission; Stripe Checkout for
  credit; the signed Stripe webhook granting purchases and taking back refunds and
  disputes.
- Changed: schema (migration `f1c7e3a92b05`: `platform_billing_settings`,
  `organization_billing_customer`, the `billing.manage` Permission); API (billing,
  checkout, webhook and platform billing settings routes); dependency (`stripe[async]`
  15.6); deployment (`PAYMENTS_ENABLED` and the Stripe secrets in Helm, the deploy
  workflows and both spec files); docs (`credit.md`, `operations.md`).
- Follow-up: the UI.

### 2026-10-13 — AF-381 — Trial expiry (PR pending)

- Delivered: a trial whose credit runs out is expired and no longer counts toward the
  active-trial cap; `OrganizationService.convert_trial` ends a trial while it stays on
  Credit.
- Changed: schema (migration `e4a9c2d7b318`, `organization.trial_expired_at`, backfilled
  for trials already out of credit); events (`organization.trial.expired`, and
  `OrganizationTrialExpiryHandler` on `organization.llm_budget.exhausted`); API
  (`trial_expired_at` on the Organization and platform reads); docs.
- Follow-up: the buy-credit prompt for expired trials comes with the Billing page.

### 2026-10-13 — AF-381 — Agent Limit (PR pending)

- Delivered: an Agent Limit for every Organization — its own (set by a Platform
  Administrator), else the trial setting or `ORGANIZATION_DEFAULT_AGENT_LIMIT`; the hire
  dialog says so at the limit; a Platform Administrator card to set or clear it.
- Changed: schema (migration `d8b3f1a6c925`, `organization.agent_limit`); API
  (`PUT /platform/organizations/{id}/agent-limit`, `agent_limit` on the Organization read,
  `agent_limit_in_force` on the platform read; `AgentLimitReached` replaces
  `TrialAgentLimitReached`); deployment (`ORGANIZATION_DEFAULT_AGENT_LIMIT` in Helm, the
  deploy workflows and both spec files); docs (`identity-and-organizations.md`, `CONTEXT.md`).
- Follow-up: none.

### 2026-10-13 — AF-381 — (PR pending)

- Delivered: credit ledger (`organization_credit_grant`), `grant_credit`, Trial Credit
  as the first grant, platform ceiling edits on Credit recorded as adjustments; no own,
  Agent or default Agent limit on Credit.
- Changed: schema (migration `c5e2a7d91f04`, opening balances for Organizations already
  on Credit); docs (`credit.md`, `costs.md`, `CONTEXT.md`).
- Follow-up: the payment provider, trial expiry and the Billing page build on `grant_credit`.
