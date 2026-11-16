# A Tier's usage is Credit, not a renewing spend limit

Status: Accepted
Date: 2026-11-08
Origin: Tiers planning with the maintainers; [Tiers change log](../features/tiers/CHANGELOG.md)

A paid Tier grants usage every month plus a one-time credit, and its Organization tops up beyond that in advance. LiteLLM gives a team one budget with one window ([Costs](../features/costs.md#runtime-limit-management)), so a renewing monthly limit cannot sit alongside top-ups that never expire. Every tiered Organization therefore runs on [Credit](../features/credit.md): the monthly usage and the one-time credit are ledger grants. The maintainers decided that unused monthly usage expires each month. That is recorded as a negative grant of what is left of that month's usage, so usage is spent before purchased credit.

## Considered alternatives

- **A renewing 30-day limit per Tier.** It renews by itself, but it can't hold credit that outlives the month, and the window can't be combined with a second budget.
- **Letting unused usage roll over.** It is simpler, needing only a grant each month, but the maintainers chose expiry to match "$20 of usage every month".

## Consequences

- Out-of-credit replies, healed spend, the Billing balance and the payment webhook already work on Credit and stay as they are.
- The expiry reads the month's spend when the month ends. Healing that prices calls afterwards can shift the expired amount by what it finds late; this is accepted.
- Revisit if LiteLLM gains more than one budget per team, or if usage should roll over.
