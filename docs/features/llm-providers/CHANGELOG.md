# LLM providers in Platform Admin settings — change log

Status: Active
Epic: AF-447
Related context: [`../llm-providers.md`](../llm-providers.md), [`../../adr/2026-11-16-provider-keys-are-platform-data-synced-to-litellm.md`](../../adr/2026-11-16-provider-keys-are-platform-data-synced-to-litellm.md), [`../costs.md`](../costs.md), [`../agent-settings.md`](../agent-settings.md), [`../../guidelines/operations.md`](../../guidelines/operations.md)

## Current state

- Delivered: slice 1, the OpenRouter key in Platform Admin settings ([feature doc](../llm-providers.md)). A Platform Administrator can read the OpenRouter key status and replace the key; saving it registers the `agentbarn:openrouter` LiteLLM route at `order: 1`. The credit balance, cost repair and the credits metric use the saved key. LiteLLM persists database routes with their provider keys encrypted under `LITELLM_SALT_KEY`; its config-file OpenRouter route is at `order: 2`, so a healthy route with a lower order is used instead.
- In transition: until a Platform Administrator saves a key, LiteLLM serves `OPENROUTER_API_KEY` through its config-file route and the API falls back to it. Each environment moves its key by hand; see the operations guide's OpenRouter key section.
- In progress: slice 2, connections to other providers. The table accepts Anthropic, OpenAI, Gemini, xAI, DeepSeek, Fireworks, Novita, Azure and Custom connections (migration `91ad0093c626`), but nothing creates them yet; OpenRouter is still the only connection. `LlmProviderKeyChecker` can check their keys, but nothing calls it yet. `GET /api/v1/platform/settings/llm-providers` lists the connections. The `platform.llm_provider.created` event is registered, but nothing emits it yet.
- Next: the slice 1 demo on local k3d; slice 2, PR 5, adding a known provider.
- Blockers: `LITELLM_SALT_KEY`, `STAGING_LITELLM_SALT_KEY` and `PUBLIC_LITELLM_SALT_KEY` GitHub secrets must exist before the next deploy.

## Changes

### 2026-11-17 — AF-447 — slice 2, PR 4

- Delivered: the Platform-scoped `platform.llm_provider.created` event, version 1, projected by `security_audit.projection` and by no other handler. Its payload is `connection_id`, `slug`, `provider_type`, `base_url` (null for a known provider), `revived` (whether a deleted connection came back) and the actor and subject display names. Any other field is refused, so no part of the key can be added to it. Nothing emits it yet.
- Changed: [`domain-events.md`](../domain-events.md) describes the event.
- Follow-up: PR 5 emits it when a Platform Administrator adds a known provider.

### 2026-11-17 — AF-447 — slice 2, PR 3

- Delivered: `GET /api/v1/platform/settings/llm-providers`, for Platform Administrators only, lists the connections that are not deleted, OpenRouter first and then by name. Each item has `slug`, `name`, `provider_type`, `base_url`, `has_api_key`, `api_key_last4`, `updated_at`, `updated_by` and `env_key_configured`, never the key or its ciphertext. `updated_at` and `updated_by` are set only while a key is saved, as on the OpenRouter status. `env_key_configured` is true only for OpenRouter while `OPENROUTER_API_KEY` is set, so the UI keeps that warning once PR 12 removes `GET .../openrouter`.
- Changed: `operations-v1.json`, the RBAC brief and [`llm-providers.md`](../llm-providers.md) list the route.
- Follow-up: PR 4 registers the `platform.llm_provider.created` event.

### 2026-11-17 — AF-447 — slice 2, PR 2

- Delivered: `LlmProviderKeyChecker` in `api/infrastructure/llm_provider_keys/` asks a provider whether it accepts a key. It sends one `GET`, pinned to a checked public address, with redirects off and a 10-second timeout, and uses only the status code; it never reads the body. `200` accepts the key; `401` or `403` refuses it, and for Gemini so does `400`; any other answer, or none, raises `LlmProviderUnreachable`. An Azure or Custom base URL that is not a public HTTPS address raises `BaseUrlNotPublic` before any request. Error messages are fixed and never carry the key. OpenRouter keys are still checked by `OpenRouterClient.check_key`. Nothing calls the checker yet.
- Changed: each provider is checked at this endpoint, checked against its official docs on 2026-11-17:

  | Provider | Request | Key header | Bad-key answer in the docs |
  | --- | --- | --- | --- |
  | Anthropic | `GET https://api.anthropic.com/v1/models` | `x-api-key` | `401` `authentication_error`; `403` `permission_error` |
  | OpenAI | `GET https://api.openai.com/v1/models` | `Authorization: Bearer` | `401`; `403` is an unsupported country or region |
  | Gemini | `GET https://generativelanguage.googleapis.com/v1beta/models` | `x-goog-api-key` | `400` `INVALID_ARGUMENT` (`API_KEY_INVALID`); `403` for a wrong, blocked or leaked key |
  | xAI | `GET https://api.x.ai/v1/models` | `Authorization: Bearer` | `401` |
  | DeepSeek | `GET https://api.deepseek.com/models` | `Authorization: Bearer` | `401` |
  | Fireworks | `GET https://api.fireworks.ai/v1/accounts` | `Authorization: Bearer` | `401`, `403` (inference error codes; the accounts endpoint documents only `200`) |
  | Novita | `GET https://api.novita.ai/openai/v1/models` | `Authorization: Bearer` | `401` `FAILED_TO_AUTH`; `403` `INVALID_API_KEY` |
  | Azure | `GET {base_url}/openai/v1/models`, the base URL being the resource endpoint such as `https://<resource>.openai.azure.com` | `api-key` | Not documented |
  | Custom | `GET {base_url}/models` | `Authorization: Bearer` | — |

  Decided with the maintainer where the docs did not settle it: Fireworks uses the account list, because its model list needs an account id; Gemini's `400` refuses the key, because the request is a fixed `GET` with no body; an Azure base URL is the resource endpoint; and Novita's model list path follows its documented OpenAI-compatible base `https://api.novita.ai/openai`. Gemini's model list reference passes the key as a `key=` query parameter; the checker sends the `x-goog-api-key` header that Gemini's API key page documents for the same host, so the key stays out of the URL.
- Follow-up: PR 5 calls the checker when a known provider is added.

### 2026-11-17 — AF-447 — slice 2, PR 1

- Delivered: migration `91ad0093c626` adds the provider types `anthropic`, `openai`, `gemini`, `xai`, `deepseek`, `fireworks`, `novita`, `azure` and `custom`, and a nullable `base_url` column. Nothing reads or writes them yet.
- Changed: the database refuses a base URL on a known provider and its absence on Azure or Custom; a known provider whose slug is not its provider type; and an Azure or Custom slug that is any provider type's name. `ProviderType` and the model's checks follow, and the migration test compares the model with the head revision. [`llm-providers.md`](../llm-providers.md) lists the provider types and their slug and base URL rules.
- Release impact: the upgrade changes no rows. The downgrade deletes every connection that is not OpenRouter, deleted ones included, with their stored keys, then drops `base_url` and restores the OpenRouter-only check.
- Follow-up: PR 2 checks each provider's key before it is stored.

### 2026-11-16 — AF-447 — slice 1, PR 13

- Fixed: a replaced OpenRouter key kept serving the old key until LiteLLM restarted. PR 12's contract test caught it in CI. LiteLLM v1.96.2 never removed a wildcard route's replaced entry from its router; v1.101.0 does (BerriAI/litellm#39664).
- Changed: LiteLLM is pinned to v1.101.6 in the Helm values, Compose and both LiteLLM contract helpers. All six LiteLLM contract tests pass on it: the OpenRouter route test, the one-off spend limit tests and the memory budget tests. The endpoints, Prometheus metric names and config keys the platform uses are unchanged.
- Release impact: LiteLLM applies 24 new migrations to its own database when the new image starts. Pinning v1.96.2 again does not undo them.

### 2026-11-16 — AF-447 — slice 1, PR 12

- Delivered: `test_openrouter_route_litellm_contract.py` saves keys through the API against the pinned LiteLLM image running the repository's `docker/litellm/config.yaml`, with a stub in place of OpenRouter that records the key each request carries. It checks that `OPENROUTER_API_KEY` serves until a key is saved, a saved key outranks it, a replacement applies at once, the saved route survives a LiteLLM restart, and `/model/info` returns none of the keys. OpenRouter's key check stays mocked and the route's `api_base` points at the stub.
- Changed: `api/tests/helpers/litellm_model_store.py` starts that LiteLLM with its model store, salt key and own database, and restarts it.
- Follow-up: the test has not run to completion yet; CI is its first run. It uses host networking like the existing LiteLLM contract helper, which Docker Desktop on Windows does not provide.

### 2026-11-16 — AF-447 — slice 1, key display follow-up

- Changed: the OpenRouter card shows a saved key as `sk-*******` plus its last four characters instead of "Key ending in …". The API still returns only the last four characters; the prefix is fixed UI text. `platform-llm-providers.spec.ts` and [`llm-providers.md`](../llm-providers.md) follow.

### 2026-11-16 — AF-447 — slice 1, PR 11

- Delivered: slice 1 is complete. [`llm-providers.md`](../llm-providers.md) documents the LLM Provider Connection, its invariants, the LiteLLM routes, the API and UI, and the move off `OPENROUTER_API_KEY`; the [ADR](../../adr/2026-11-16-provider-keys-are-platform-data-synced-to-litellm.md) records why provider keys are platform data synced to LiteLLM.
- Changed: `docs/INDEX.md` routes the feature doc and this change log; `CONTEXT.md` defines LLM Provider Connection.
- Follow-up: the k3d demo and read-only LiteLLM checks listed under Current state.

### 2026-11-16 — AF-447 — slice 1, PR 10

- Delivered: Platform Admin settings has an LLM providers section (`?section=llm-providers`) with an OpenRouter card. It shows the key's last four characters and who changed it when, or that no key is saved and whether Agents are using `OPENROUTER_API_KEY` meanwhile. "Save a key" or "Replace key" opens a dialog with a password field; a refused or failed save keeps the dialog open with the API's message, and an empty key is not sent. While a key is saved and `OPENROUTER_API_KEY` is still set, the card says the secret can be deleted once every environment sharing it has a saved key.
- Changed: `ui/tests/e2e/platform-llm-providers.spec.ts` with its page object and data support; the navigation spec counts nine settings sections.
- Follow-up: PR 11 adds the feature doc, the `docs/INDEX.md` route, the `CONTEXT.md` term and the ADR.

### 2026-11-16 — AF-447 — slice 1, PR 9

- Delivered: `OPENROUTER_API_KEY` is optional. Helmfile, the LiteLLM chart's Secret, `run.sh`, `k3d-up.sh` and the public deploy no longer require it; without it LiteLLM renders no config-file route.
- Changed: `operations.md` gains an OpenRouter key section with the order for moving each environment's key into Platform Admin settings before its secret is deleted; `.env.spec`, `.env.deploy.spec` and the README call the key optional. The API chart's values comment, the `OpenRouterCreditsUnknown` alert and the platform Costs page's credits warning point to the key saved in Platform Admin settings instead of only `OPENROUTER_API_KEY`.
- Follow-up: PR 10 adds the OpenRouter section to Platform Admin settings.

### 2026-11-16 — AF-447 — slice 1, PR 8

- Delivered: the platform credit balance, cost repair and the `agentbarn_openrouter_credits_remaining` metric read the key through `OpenRouterKeyLookup`: the saved key, else `OPENROUTER_API_KEY`. The metric polls again at once when the key changes instead of waiting out its cache, and reports `scrape_ok` 0 when the key cannot be read rather than failing `/metrics`.
- Changed: `key_source` is removed from the table (migration `22b93965859f` edited in place; it has not shipped), the status response and the `platform.llm_provider.changed` payload. Only a Platform Administrator sets the key, so it carried nothing.
- Follow-up: PR 9 makes `OPENROUTER_API_KEY` optional in deployment.

### 2026-11-16 — AF-447 — slice 1, PR 6

- Delivered: `PUT /api/v1/platform/settings/llm-providers/openrouter` replaces the key. OpenRouter checks it first (`GET /key`; 401 or 403 gives `422`, no answer gives `503`). Under a per-connection advisory lock, the API writes the `agentbarn:openrouter` LiteLLM route (`openrouter/*`, order 1) and only then stores the encrypted key with a `platform.llm_provider.changed` event. A LiteLLM failure gives `503`. Every failure leaves the stored key and the event log unchanged, and a refused or unchecked key never reaches LiteLLM. LiteLLM can still hold a key the database does not when it applied the write but the API saw a failure (a timeout after the write, or a failed commit afterwards).
- Changed: `OpenRouterClient.check_key`; a credential-safe route class whose `422` never echoes the body; `operations-v1.json`, the RBAC brief and `domain-events.md`.
- Follow-up: saving the key again re-applies it to LiteLLM, which repairs that mismatch.

### 2026-11-16 — AF-447 — slice 1, PR 5

- Delivered: `GET /api/v1/platform/settings/llm-providers/openrouter`, for Platform Administrators only, reports `has_api_key`, `api_key_last4`, `key_source`, `updated_at`, `updated_by` and `env_key_configured`, never the key. `OpenRouterKeyLookup.api_key()` returns the stored key, else `OPENROUTER_API_KEY`, else empty; nothing calls it yet.
- Changed: `operations-v1.json` and the RBAC brief list the route.
- Follow-up: PR 6 lets a Platform Administrator replace the key.

### 2026-11-16 — AF-447 — slice 1, PR 4

- Delivered: table `llm_provider_connection` (migration `22b93965859f`), seeded with the `openrouter` connection and no key. Nothing reads or writes it yet.
- Changed: the database refuses a slug that is taken (deleted connections included), malformed, or contains a slash; an unknown provider type or key source; and a key without its last four characters and source, or the reverse. The test reset re-seeds the row.
- Follow-up: PR 5 reads the row to report the key status.

### 2026-11-16 — AF-447 — slice 1, PR 3

- Delivered: `OpenRouterClient` no longer reads the key from Config. `get_credits` and `get_generation` take it per call, and the credit cache is held per key. The catalogue is fetched without a key; OpenRouter's `/models` returned the full catalogue unauthenticated when checked on 2026-11-16.
- Changed: `PlatformCostService` passes `Config.openrouter_api_key`; `CostSynchronizer` takes a required `openrouter_api_key` source, resolved once per healing run and wired to the same Config key.
- Follow-up: PR 8 resolves the stored key instead, and moves the credits metric in `api/core/metrics.py`, which calls OpenRouter itself rather than through this client.

### 2026-11-16 — AF-447 — slice 1, PR 2

- Delivered: LiteLLM's model store is on (`store_model_in_db: true`). The config-file `openrouter/*` route is at `order: 2` and is rendered only while `OPENROUTER_API_KEY` is set.
- Changed: new required `LITELLM_SALT_KEY`, kept in its own `litellm-salt` Secret that the API does not read; wired through Helmfile, both deploy workflows, Compose, `run.sh` and `k3d-up.sh`. LiteLLM chart 0.5.0.
- Follow-up: PR 3 passes the OpenRouter key to the client per call.

### 2026-11-16 — AF-447 — slice 1, PR 1

- Delivered: `LiteLLMClient.upsert_model_deployment` creates a route LiteLLM does not have (`/model/new`) and updates one it has (`/model/update`), looked up by `model_info.id`; `delete_model_deployment` removes a route and reports one that is already gone.
- Changed: failures raise `LiteLLMError` with a fixed message and no exception chain, so the provider key in the request body never reaches a log or traceback.
- Follow-up: PR 2 turns on LiteLLM's model store so these routes persist.
