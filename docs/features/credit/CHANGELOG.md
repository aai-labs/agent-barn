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
  banner that links to buying more; the out-of-credit reply on Hermes and OpenClaw; and
  healed spend counted against credit.
- In transition: built on the AF-368 trial-onboarding branch, which is not yet on staging.
- Next: review, then rebase onto staging once AF-368 merges; manual sandbox testing.
- Blockers: none. A Stripe sandbox exists for manual testing.

## Changes

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
  section on the platform settings page; the spend-limit banner speaks of credit and
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
