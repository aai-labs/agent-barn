# LLM Providers

## Read when

Read before changing where provider keys come from, the LLM providers section of Platform Admin settings, the `llm_provider_connection` or `llm_provider_model` table, how a provider's key is checked (`LlmProviderKeyChecker`), the LiteLLM routes the API registers, `OpenRouterKeyLookup`, or anything that calls OpenRouter with the platform's key (credits, cost repair, the credits metric).

## Role in the system

Agents never hold a provider key. They call LiteLLM with their own virtual keys, and LiteLLM calls the provider with the platform's key. An **LLM Provider Connection** is one of those platform accounts: a provider and the key Agent Barn reaches it with. It is a Platform Resource that Platform Administrators keep in Platform Admin settings.

**OpenRouter** is seeded by migration `22b93965859f` with no key. A Platform Administrator can add one connection each to Anthropic, OpenAI, Gemini, xAI, DeepSeek, Fireworks and Novita, and any number of Azure and Custom connections, replace any connection's key, and delete any connection but OpenRouter. Agents can't use the other providers yet, because only OpenRouter's key reaches LiteLLM; models and prices per connection, and Agents using them, come in later slices of the AF-447 epic ([`llm-providers/CHANGELOG.md`](llm-providers/CHANGELOG.md)). Why keys are platform data rather than deployment secrets is in [its ADR](../adr/2026-11-16-provider-keys-are-platform-data-synced-to-litellm.md).

## The connection

- Stored in `llm_provider_connection`: a unique `slug`, `name`, `provider_type`, `api_key_encrypted`, `api_key_last4`, `base_url`, `updated_by`, `updated_at` and `deleted_at`.
- The provider types are `openrouter`, `anthropic`, `openai`, `gemini`, `xai`, `deepseek`, `fireworks`, `novita`, `azure` and `custom`. A known provider has at most one connection, whose slug is its provider type and which has no `base_url`. An Azure or Custom connection has a slug of its own, which can't be any provider type's name, and a `base_url`.
- The key is Fernet-encrypted with `AGENT_TOKEN_ENCRYPTION_KEY`, as other stored secrets are. Its last four characters are kept apart, so listing the connections never decrypts it.
- Deleting a connection removes its LiteLLM routes, then deletes its models, sets `deleted_at` and purges the key and its last four characters, all under the connection's lock; the row keeps its slug, name and `base_url`. OpenRouter can't be deleted.
- Adding a known provider whose connection was deleted brings that row back, with the same id and the new key. An Azure or Custom connection is never brought back: a slug used before, deleted or not, is refused.
- An Azure or Custom connection's name is chosen by the Platform Administrator, at most 64 characters. Its base URL is a public HTTPS address, at most 2048 characters, with no credentials, query or fragment, and stored without a trailing `/`.
- A slug stays unique among deleted connections too, so it is never reused. The database refuses a malformed slug, an unknown provider type, a key without its last four characters or the reverse, and a connection that breaks its provider type's slug or `base_url` rule.

## Models

- Stored in `llm_provider_model`, added by migration `bc817a73bb6d`: the `connection_id`, a `model_id`, four per-token prices (`input_cost_per_token`, `output_cost_per_token`, `cache_read_input_token_cost`, `cache_creation_input_token_cost`, each `NUMERIC(24,18)`), a `price_source` and a `litellm_price_key`. The price columns carry LiteLLM's own route field names.
- A connection carries a model once; two connections may carry the same `model_id`. A `model_id` is 1 to 200 characters of `[A-Za-z0-9._:/-]`, so it can't hold `*`.
- `price_source` is `litellm` for a price read from LiteLLM's price list, with the key it was read under in `litellm_price_key`, or `manual` for a typed price, with no key.
- The database refuses an input or output price of zero or less, a negative cache price, a missing price, an unknown price source, a key that doesn't match the price source, a malformed `model_id` and a model of no connection.
- Nothing adds models yet; deleting a connection deletes its models. Slice 3's later PRs add the API ([change log](llm-providers/CHANGELOG.md)).

## Invariants

- **Nobody reads the key back.** The list reports whether each connection has a key saved, its last four characters, who saved it and when, never the key. A refused request's `422` never echoes the body (`CredentialSafeRoute`), and the audit event carries no part of the key.
- **A key is checked before it is used.** The provider must accept it first ([Checking a key](#checking-a-key)). A key it refuses is `422` and no answer `503`; an Azure or Custom base URL that is not a public address, or does not answer like a model API, is `422`. A refused or unchecked key never reaches LiteLLM or the database.
- **LiteLLM first, then the database.** Under a per-connection advisory lock, the API writes the connection's LiteLLM routes and only then stores the encrypted key with its event, in one transaction. OpenRouter's key goes to its one route; any other connection's key is written to the route of each of its models, with the new base URL for Azure or Custom, and routes under its prefix with no model are removed. A LiteLLM failure is `503` and leaves the stored key and the event log unchanged. If LiteLLM applied a write but the API saw a failure (a failure part-way, a timeout after the write, or a failed commit afterwards), LiteLLM holds a key the database does not; saving the key again repairs it, and leaves one route per model.
- **Routes go before the rows.** Deleting a connection removes every LiteLLM route under its prefix under the same lock, before its models and key are deleted in one transaction with the event. A LiteLLM failure is `503` and deletes nothing; a key replacement that takes the lock after a delete finds the connection gone, `404`, and writes no route.
- **No restart.** Saving a key registers or updates the connection's LiteLLM routes in the same request, so Agents use the new key at once. Adding a provider writes no route, since a new or revived connection has no models.
- **A base URL changes only with a new, checked key.** A replaced Azure or Custom key is checked at the new base URL if one is sent, else at the stored one. If the stored base URL changed while the key was checked, nothing is stored and the API answers `409`.
- **API startup does not sync keys to LiteLLM**, so the API's readiness never depends on the proxy being reachable ([API architecture](../architecture/api.md#startup-data)). Nothing copies `OPENROUTER_API_KEY` into the table; each environment's key is saved by hand (see [Moving off the environment key](#moving-off-the-environment-key)).

## Checking a key

OpenRouter's key is checked by `OpenRouterClient.check_key` with `GET {openrouter_base_url}/key` (`https://openrouter.ai/api/v1/key` by default).

Every other key is checked by `LlmProviderKeyChecker` (`api/infrastructure/llm_provider_keys/`). It sends one `GET`, pinned to a checked public address, with redirects off and a 10-second timeout, and reads only the status and headers, never the body.

| Provider | Request | Key header |
| --- | --- | --- |
| Anthropic | `GET https://api.anthropic.com/v1/models` | `x-api-key` |
| OpenAI | `GET https://api.openai.com/v1/models` | `Authorization: Bearer` |
| Gemini | `GET https://generativelanguage.googleapis.com/v1beta/models` | `x-goog-api-key` |
| xAI | `GET https://api.x.ai/v1/models` | `Authorization: Bearer` |
| DeepSeek | `GET https://api.deepseek.com/models` | `Authorization: Bearer` |
| Fireworks | `GET https://api.fireworks.ai/v1/accounts` | `Authorization: Bearer` |
| Novita | `GET https://api.novita.ai/v3/user` | `Authorization: Bearer` |
| Azure | `GET {base_url}/openai/v1/models`, the base URL being the resource endpoint such as `https://<resource>.openai.azure.com` | `api-key` |
| Custom | `GET {base_url}/models` | `Authorization: Bearer` |

`200` accepts the key. `401` or `403` refuses it, and for Gemini and xAI so does `400`. Any other answer, or none, means the provider could not be reached. For Azure and Custom, a base URL whose host is not a public address is refused before any request, and a redirect, a `404`, or a `200` whose `Content-Type` is not `application/json` or `+json` means the base URL does not answer like a model API. A Custom server whose `/models` does not check the key accepts any key. Why Fireworks, Gemini, Azure, Novita and xAI are checked this way is in the [change log](llm-providers/CHANGELOG.md) (slice 2, PR 2 and the review fixes).

## LiteLLM routes

LiteLLM's model store is on (`store_model_in_db: true`), so routes the API registers persist in LiteLLM's database with their keys encrypted under `LITELLM_SALT_KEY`. That value must never change; see the [operations guide](../guidelines/operations.md#litellm-salt-key).

| Route | Comes from | Order |
| --- | --- | --- |
| `agentbarn:openrouter` (`openrouter/*`, `https://openrouter.ai/api/v1`, background health check off) | Saved by a Platform Administrator; written with `LiteLLMClient.upsert_model_deployment` | 1 |
| Config-file `openrouter/*` | `OPENROUTER_API_KEY`, rendered only while it is set | 2 |

LiteLLM sends a request to the lowest-order healthy route, so once a key is saved the config-file route is used only while the saved route is unavailable.

A replaced key applies at once only on LiteLLM v1.101.0 or later. Earlier versions never removed a wildcard route's replaced entry from their router, so the old key kept serving `openrouter/*` until LiteLLM restarted.

Each LLM Provider Model of a connection other than OpenRouter gets a route of its own, built by `build_model_deployment` in `api/domains/llm_providers/litellm_deployments.py`. Replacing the connection's key rewrites them and deleting the connection removes them; nothing adds a model yet. A route is named `<slug>/<model_id>`, its id is `agentbarn:model:<connection id>:<model row id>`, its background health check is off, and it carries the connection's key and all four of the model's prices, sent as floats because LiteLLM holds route prices as floats.

| Provider | `model` | Also sent |
| --- | --- | --- |
| OpenAI, Anthropic, Gemini, xAI | `openai/<id>`, `anthropic/<id>`, `gemini/<id>`, `xai/<id>` | — |
| DeepSeek | `deepseek/<id>` | `api_base` `https://api.deepseek.com`; LiteLLM's own default is `https://api.deepseek.com/beta` |
| Fireworks | `fireworks_ai/<id>` | — |
| Novita | `novita/<id>` | `api_base` `https://api.novita.ai/openai`; LiteLLM's own default is `https://api.novita.ai/v3/openai` |
| Azure | `azure/<deployment>` | `api_base` the stored resource endpoint and `api_version` `v1`, so LiteLLM calls `{api_base}/openai/v1/` |
| Custom | `openai/<id>` | `api_base` the stored base URL, unchanged |

## The API's own OpenRouter calls

`OpenRouterKeyLookup.api_key()` returns the saved key, else `OPENROUTER_API_KEY`, else empty. The platform credit balance, cost repair (`CostSynchronizer`) and the `agentbarn_openrouter_credits_remaining` metric resolve it each time they run, so a new key reaches them without a restart; the metric polls again at once when the key changes and reports `scrape_ok` 0 when the key cannot be read. The model catalogue is fetched without a key. See [Costs](costs.md).

## API

Every route is under `require_platform_admin`, which refuses writes from a read-only API key.

| Route | Does |
| --- | --- |
| `GET /api/v1/platform/settings/llm-providers` | Lists the connections that are not deleted, OpenRouter first and then by name. Each has `slug`, `name`, `provider_type`, `base_url`, the key status (`has_api_key`, `api_key_last4`, `updated_at`, `updated_by`) and `env_key_configured`, which is true only for OpenRouter while `OPENROUTER_API_KEY` is set |
| `POST /api/v1/platform/settings/llm-providers` | Adds a known provider, `{provider_type, api_key}`, or an Azure or Custom connection, `{provider_type, slug, name, base_url, api_key}`; the key is trimmed and at most 512 characters. Answers `201` with the connection. A provider already connected, OpenRouter, or an Azure or Custom slug used before is `409`; a slug, name or base URL that breaks its rule is `422` with a fixed message naming the rule. Both are refused before the key is checked. A refused key or base URL is `422` and no answer `503`, and nothing is stored |
| `PUT /api/v1/platform/settings/llm-providers/{slug}/key` | Replaces a connection's key, `{api_key}`, trimmed and at most 512 characters, with an optional new `base_url` for Azure or Custom; answers with the connection. OpenRouter's key is checked by OpenRouter, any other by `LlmProviderKeyChecker`; either is routed in LiteLLM before it is stored. An unknown or deleted slug is `404`; a base URL for any other provider, or one that breaks its rule, is `422` before the key is checked. A refused key or base URL is `422`, no answer or a LiteLLM failure `503`, and a stored base URL that changed meanwhile `409`; nothing is stored |
| `DELETE /api/v1/platform/settings/llm-providers/{slug}` | Removes the connection's LiteLLM routes, then deletes its models and the connection and purges its key; answers `204`. OpenRouter is `409`, an unknown or already deleted slug `404`, and a LiteLLM failure `503` with nothing deleted |

A saved key records `platform.llm_provider.changed`, Platform scope, projected to Security Audit. Its payload is the connection id and slug, whether a key was replaced, the provider type, the base URL before and after, and display names. An added provider records `platform.llm_provider.created` the same way, with the provider type, base URL and whether a deleted connection was brought back. A deleted connection records `platform.llm_provider.deleted`, with the provider type, base URL and whether a key was purged. See [domain events](domain-events.md).

## UI

Platform Admin settings → **LLM providers** (`/dashboard/platform/settings?section=llm-providers`, `ui/src/features/llm-providers/`) reads every connection from `GET /platform/settings/llm-providers`; a failed read can be retried. It lists every live connection in the API's order, OpenRouter first, each in its own card with its name, who changed its key when, and for Azure and Custom the provider and base URL. A saved key is masked as `*******` plus its last four characters, and OpenRouter's as `sk-*******` (other providers' keys don't all start with `sk-`). OpenRouter's card also says:

- with no key: whether Agents are using `OPENROUTER_API_KEY` meanwhile, or that they cannot call OpenRouter models until a key is saved;
- with a saved key while `OPENROUTER_API_KEY` is still set: that the secret can be deleted once every environment sharing it has a saved key.

"Add provider", above the cards, opens a dialog that offers the known providers not yet connected, Azure and Custom, never OpenRouter. Azure and Custom also ask for a name, slug and base URL. The key is a password field. A refused add keeps the dialog open with the API's message; a missing provider or empty key is not sent.

Every card has "Replace key" ("Save a key" while it has none), which opens a dialog with a password field and sends `PUT /platform/settings/llm-providers/{slug}/key`. For Azure and Custom the dialog also shows the base URL, filled in with the stored one; it is sent with the key only when it was changed. A refused or failed save keeps the dialog open with the API's message; an empty key is not sent. Every card but OpenRouter's has "Delete", which asks for confirmation before it sends `DELETE /platform/settings/llm-providers/{slug}`; for Azure and Custom the confirmation says the slug can't be used again. A refused delete keeps the confirmation open with the API's message.

An added provider, a saved key and a deleted connection are each confirmed by a toast.

## Moving off the environment key

`OPENROUTER_API_KEY` is optional. While it is set, LiteLLM serves it through the config-file route and the API falls back to it. Each environment's key is saved in Platform Admin settings before its GitHub secret is deleted; staging and k3s share one secret. The steps are in the [operations guide](../guidelines/operations.md#openrouter-key). Deleting a secret before its environments have a saved key leaves LiteLLM with no OpenRouter route.
