# Memory spend counts against the Organization's limit, and Agents reach memory through a proxy

Status: Accepted
Date: 2026-09-29
Origin: [AF-338](https://aai-labs.atlassian.net/browse/AF-338)
Supersedes: the *Tenant isolation* and *Enforcing per-pool cost (deferred)* sections of [2026-09-21 — Agent memory is shared in pools](2026-09-21-shared-memory-pools-via-groups.md)

Memory model calls run on Honcho's single LiteLLM key, which is in no team and carries no Organization identity, so an Organization's LLM budget neither saw nor capped them. Memory spend now counts against that budget by **lowering the team's ceiling** by the memory spent this window, and an Organization that reaches its limit has its memory **suspended**. Suspension has to bite on running Agents that may have copied their credentials, and Honcho cannot revoke a key, so Agents stop holding Honcho credentials at all: they reach memory through a **memory proxy** we own, with a per-Agent key we can revoke.

## Budget side

LiteLLM has no supported way to add spend to a team ([#30783](https://github.com/BerriAI/litellm/issues/30783)), and a synthetic key's spend does not roll up to its team. Lowering the ceiling to `limit − memory` reaches the same crossing point (`agents + memory ≥ limit`) on the side LiteLLM lets us write. A `max_budget`-only team update does not move the renewal date: LiteLLM (v1.96.2, `_set_budget_reset_at`) reschedules only when `budget_duration` is sent, and the client sends changed fields only.

The lowered ceiling is one model property, `Organization.enforced_llm_budget_usd`, that every team write uses (limit changes, team provisioning, reconciliation, enforcement). Anything less and the reconciler, which pushes the stored limit every run, would undo enforcement within one interval.

A dedicated CronJob measures memory, pushes the ceiling and trips the suspension, rather than a step of the reconciler (repairs drift, reads no spend) or the alerts pass (informational by contract). The trip is keyed to the window and limit because the apportioned figure is relative to every other pool and can fall; without the key an Organization would flap in and out of suspension.

## Access side

Honcho v3.2.0 keys are stateless HS256 JWTs: `verify_jwt` checks only the signature, the optional `exp` and the scope claims, and there is no revoke endpoint. A pod that copied its pool token — onto its volume, or anywhere else — keeps full read/write access after suspension, after leaving its group, forever. The same scope also lets any pool member rewrite the pool's configuration (`PUT /v3/workspaces/{id}`), including our deriver instructions.

The proxy is a separate Deployment built from the API image. Each Agent's bearer is a per-Agent memory key, `<agent id>.<secret>` (the key, not the URL, names the Agent: OpenClaw's Honcho SDK drops any path on the base URL), stored encrypted, replaced on every start and cleared on stop. Every request is checked against the Agent's status, its group, and its Organization's suspension, and forwarded with a token scoped to that Agent's pool, so Honcho still enforces the workspace boundary if the proxy is wrong. Workspace-level writes, key minting and workspace listing are refused.

## Considered alternatives

- **Restart the Organization's Agents with memory off.** Only works if the Agent cooperates: a copied token survives the restart.
- **NetworkPolicy on Honcho.** Effectiveness depends on the cluster's network plugin, which the product cannot verify on self-hosted installs. Policies are allow-only and already-open connections usually survive a relabel.
- **Short-lived tokens with a refresh endpoint.** Access ends only at expiry, and both runtimes read the token once at start, so each would need a new refresh path.
- **Patch our own Honcho image** (per-pool LiteLLM keys and key revocation). The strongest budget story — memory would become ordinary team spend, capped at request time — but a patch to reapply on every Honcho upgrade on code (`src/security.py`) that upstream is actively changing. Revisit if upstream accepts key revocation or per-workspace LLM identity.

## Revisit when

- Upstream Honcho gains key revocation, or identity on its outbound LLM requests.
- A per-Organization memory cap must be a hard request-time guarantee rather than bounded by the enforcement interval.
