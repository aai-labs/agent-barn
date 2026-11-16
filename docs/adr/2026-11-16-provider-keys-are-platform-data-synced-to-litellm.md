# Provider keys are platform data synced to LiteLLM

Status: Accepted
Date: 2026-11-16
Origin: AF-447 planning with the maintainers; [LLM providers change log](../features/llm-providers/CHANGELOG.md)

LLM provider keys are kept by Platform Administrators in Platform Admin settings as [LLM Provider Connections](../features/llm-providers.md), not as deployment secrets. Saving a key checks it with the provider and registers it as a route in LiteLLM's model store, so Agents use it at once. The maintainers chose this for three reasons:

- Platform Administrators change or rotate a provider key themselves, at once, without GitHub secret access, a redeploy or a restart.
- Later AF-447 slices add Anthropic, OpenAI and other connections, each with its own models and prices; environment variables cannot hold an open-ended list.
- Who changed a key and when is recorded and shown, and the key is checked before it is used, which a GitHub secret never is.

## Considered alternatives

- **Keeping `OPENROUTER_API_KEY` as the deployment secret.** It is what existed, and it gives none of the three above.
- **Copying the environment key into the table at API startup.** Dropped: it only matters once per environment, until every environment has a saved key, and syncing it to LiteLLM at startup would make the API's readiness depend on the proxy being reachable, which [the API architecture](../architecture/api.md#startup-data) rules out. Each environment's key is saved by hand instead.

## Consequences

- `LITELLM_SALT_KEY` is a new required secret per environment, and it must never change: LiteLLM cannot decrypt the keys it stores under another value ([operations guide](../guidelines/operations.md#litellm-salt-key)).
- The key lives in two places: encrypted in the API's database, for the status, the audit trail and the API's own OpenRouter calls (credits, cost repair, the credits metric), and in LiteLLM's model store. LiteLLM is written first; if it applied a key the API then failed to store, saving the key again repairs it.
- `OPENROUTER_API_KEY` stays optional while environments move: LiteLLM keeps it as a config-file route at a higher `order` than the saved route, and the API falls back to it until a key is saved.
