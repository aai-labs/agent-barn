# LLM providers in Platform Admin settings — change log

Status: Active
Epic: AF-447
Related context: [`../llm-providers.md`](../llm-providers.md), [`../../adr/2026-11-16-provider-keys-are-platform-data-synced-to-litellm.md`](../../adr/2026-11-16-provider-keys-are-platform-data-synced-to-litellm.md), [`../costs.md`](../costs.md), [`../agent-settings.md`](../agent-settings.md), [`../../guidelines/operations.md`](../../guidelines/operations.md)

## Current state

- Delivered: slice 1, the OpenRouter key in Platform Admin settings ([feature doc](../llm-providers.md)). A Platform Administrator can read the OpenRouter key status and replace the key; saving it registers the `agentbarn:openrouter` LiteLLM route at `order: 1`. The credit balance, cost repair and the credits metric use the saved key. LiteLLM persists database routes with their provider keys encrypted under `LITELLM_SALT_KEY`; its config-file OpenRouter route is at `order: 2`, so a healthy route with a lower order is used instead.
- In transition: until a Platform Administrator saves a key, LiteLLM serves `OPENROUTER_API_KEY` through its config-file route and the API falls back to it. Each environment moves its key by hand; see the operations guide's OpenRouter key section. Keys saved for other providers are not synced to LiteLLM until slice 3, so Agents can't use them yet.
- Delivered: slice 2, connections to other providers ([feature doc](../llm-providers.md)). In Platform Admin settings and through the API, a Platform Administrator can add one connection each to Anthropic, OpenAI, Gemini, xAI, DeepSeek, Fireworks and Novita, and any number of Azure and Custom connections. Any connection's key can be replaced, with a new base URL for Azure or Custom, and any connection but OpenRouter deleted. Each key is checked with its provider before it is stored, and every addition, replacement and deletion is audited. OpenRouter's key is read from the connection list and replaced through `PUT .../openrouter/key`; the OpenRouter-only routes are gone.
- Next: the demo of slices 1 and 2 on local k3d; slice 3, models and prices per connection, with their LiteLLM routes and the LiteLLM egress NetworkPolicy.
- Blockers: `LITELLM_SALT_KEY`, `STAGING_LITELLM_SALT_KEY` and `PUBLIC_LITELLM_SALT_KEY` GitHub secrets must exist before the next deploy.

## Changes

### 2026-11-17 — AF-447 — slice 2, provider list follow-up

- Changed: Platform Admin settings → LLM providers shows every connection, OpenRouter first, in one list with a card each, replacing the OpenRouter card and the **Other providers** card. "Add provider" sits above the cards, as "Add size" does in Agent sizes. An added provider, a saved key and a deleted connection are confirmed by a toast instead of a line inside a card. `provider-card.tsx` replaces `llm-provider-connection-list.tsx`, and `platform-llm-provider-settings.tsx` holds the add, key and delete dialogs. `platform-llm-providers.spec.ts` and its page object find cards in the provider list and check the toasts. [`llm-providers.md`](../llm-providers.md) describes the list.

### 2026-11-17 — AF-447 — slice 2, PR 13

- Delivered: slice 2 is complete. [`llm-providers.md`](../llm-providers.md) has a section on how each provider's key is checked, and its read-when, role and invariants cover every connection rather than OpenRouter alone.
- Changed: `docs/INDEX.md` routes `api/infrastructure/llm_provider_keys/` and key checking to the feature doc. `CONTEXT.md` is unchanged: its LLM Provider Connection definition already fits a connection to any provider.
- Follow-up: the demo of slices 1 and 2 on local k3d, then slice 3.

### 2026-11-17 — AF-447 — slice 2, PR 12

- Removed: `GET` and `PUT /api/v1/platform/settings/llm-providers/openrouter`, with `OpenRouterConnectionRead`, `OpenRouterKeyUpdate` and the service's `read_openrouter` and `replace_openrouter_key`. OpenRouter's key status is its entry in `GET /platform/settings/llm-providers`, and its key is replaced through `PUT .../openrouter/key`, which checks it with OpenRouter and writes the LiteLLM route first as before. Both old paths now answer `405`, because `DELETE .../{slug}` matches them, and reach nothing.
- Changed: `test_platform_llm_providers.py` reads OpenRouter's entry from the list and saves through `PUT .../openrouter/key`, and checks that the old paths change nothing. `test_openrouter_route_litellm_contract.py` saves through `PUT .../openrouter/key` and passes against LiteLLM. `operations-v1.json`, the RBAC brief and [`llm-providers.md`](../llm-providers.md) drop the two routes.
- Release impact: an API client still calling `GET` or `PUT .../openrouter` gets `405`; the UI stopped calling them in PR 11.
- Follow-up: PR 13 brings the feature doc, `docs/INDEX.md` and this change log up to slice 2 delivered.

### 2026-11-17 — AF-447 — slice 2, PR 11

- Delivered: every card in Platform Admin settings → LLM providers has "Replace key" ("Save a key" while it has none), opening one dialog for any connection that sends `PUT /platform/settings/llm-providers/{slug}/key`. For Azure and Custom the dialog shows the stored base URL and sends a new one only when it was changed. Every card but OpenRouter's has "Delete", which sends `DELETE /platform/settings/llm-providers/{slug}` only after a confirmation; for Azure and Custom it says the slug can't be used again. A refused save or delete keeps its dialog open with the API's message; for a delete answered `404` that is the API's own text rather than the generic not-found message. A saved key's notice shows in its card, and an added or deleted provider's below the list.
- Changed: the OpenRouter card is built from the connection list and saves through `PUT .../openrouter/key`, so the UI no longer calls `GET` or `PUT .../openrouter`, and one failed read replaces the separate OpenRouter and list errors. `use-openrouter-connection.ts` and `openrouter-key-dialog.tsx` are removed; `useLlmProviderActions` holds the add, replace and delete mutations, each invalidating every LLM provider query, and `provider-key-dialog.tsx` replaces the OpenRouter dialog. `platform-llm-providers.spec.ts`, its page object and its data support mock only the list, `.../{slug}/key` and `DELETE .../{slug}`, and cover replacing keys, deleting and refusals. [`llm-providers.md`](../llm-providers.md) describes the cards.
- Follow-up: PR 12 removes the `/openrouter` routes from the API.

### 2026-11-17 — AF-447 — slice 2, PR 10

- Delivered: Platform Admin settings → LLM providers shows an **Other providers** card below OpenRouter. It lists each other live connection from `GET /platform/settings/llm-providers`, its key masked as `*******` plus the last four characters, who changed it when, and for Azure and Custom the provider and base URL. "Add provider" opens a dialog: a provider select offering the known providers not yet connected, Azure and Custom (never OpenRouter), a name, slug and base URL for Azure and Custom, and a password field for the key. It sends `POST /platform/settings/llm-providers`; a refusal keeps the dialog open with the API's message, and a missing provider or empty key is not sent. A failed list read can be retried on its own.
- Changed: `ui/src/features/llm-providers/` gains the connection schema, `useLlmProviderConnections`, the list and the add dialog. Replacing the OpenRouter key now invalidates every LLM provider query. `platform-llm-providers.spec.ts`, its page object and its data support cover the list, adding a known provider and an Azure connection, and refusals. [`llm-providers.md`](../llm-providers.md) describes the card.
- Follow-up: PR 11 adds replacing keys and deleting connections to the UI.

### 2026-11-17 — AF-447 — slice 2, PR 9

- Delivered: `DELETE /api/v1/platform/settings/llm-providers/{slug}` deletes a connection and answers `204`. Under the per-slug advisory lock it sets `deleted_at`, purges the encrypted key and its last four characters, and records `platform.llm_provider.deleted` in the same transaction, with `key_purged` saying whether a key was stored. The row keeps its slug, name and base URL. OpenRouter is `409`, and an unknown or already deleted slug `404`. A read-only Personal API Key is refused. Afterwards a known provider can be added again, bringing the same row back, while an Azure or Custom slug stays refused, and the deleted connection's key can't be replaced. No LiteLLM route is removed, because only OpenRouter has one and it can't be deleted.
- Changed: `operations-v1.json`, the RBAC brief, [`llm-providers.md`](../llm-providers.md) and [`domain-events.md`](../domain-events.md) describe the route and that the event is now emitted.
- Follow-up: PR 10 adds the connection list and add dialog to the UI.

### 2026-11-17 — AF-447 — slice 2, PR 8

- Delivered: the Platform-scoped `platform.llm_provider.deleted` event, version 1, projected by `security_audit.projection` and by no other handler. Its payload is `connection_id`, `slug`, `provider_type`, `base_url` (null for a known provider), `key_purged` (whether a stored key was removed) and the actor and subject display names. Any other field is refused, so no part of the key can be added to it. Nothing emits it yet.
- Changed: [`domain-events.md`](../domain-events.md) describes the event.
- Follow-up: PR 9 emits it when a Platform Administrator deletes a connection.

### 2026-11-17 — AF-447 — slice 2, PR 7

- Delivered: `PUT /api/v1/platform/settings/llm-providers/{slug}/key` with `{api_key, base_url?}` replaces any live connection's key and answers with the connection. OpenRouter's key is checked by `OpenRouterClient.check_key` and written to the LiteLLM route before it is stored, as before. Any other key is checked by `LlmProviderKeyChecker` and only stored. An Azure or Custom key is checked at the new base URL when one is sent, which follows PR 6's rules and is stored with the key, else at the stored base URL. A base URL for any other provider is `422` before the key is checked. An unknown or deleted slug is `404`. A refused key or base URL is `422` and no answer `503`. Under the lock, a stored base URL that changed while the key was checked is `409`, even when a new one was sent, and a connection deleted meanwhile is `404`. In every refusal nothing is stored.
- Changed: `platform.llm_provider.changed` stays version 1 and gains optional `provider_type`, `previous_base_url` and `base_url`, so events recorded before them stay valid. The event registry stores every field, so `PUT .../openrouter` now records them too, with null base URLs; decided with the maintainer, `test_platform_llm_providers.py` expects them. `PUT .../openrouter` now runs through the same service method, so its `404` says "That connection does not exist."; its other answers are unchanged. `operations-v1.json`, the RBAC brief, [`llm-providers.md`](../llm-providers.md) and [`domain-events.md`](../domain-events.md) describe the route and the fields. `test_openrouter_route_litellm_contract.py` passes against LiteLLM.
- Follow-up: PR 8 registers the `platform.llm_provider.deleted` event.

### 2026-11-17 — AF-447 — slice 2, PR 6

- Delivered: `POST /api/v1/platform/settings/llm-providers` adds an Azure or Custom connection with `{provider_type, slug, name, base_url, api_key}`. The slug follows the slug pattern, is at most 32 characters and can't be any provider type's name. The name is trimmed, 1 to 64 characters. The base URL is a public HTTPS address of at most 2048 characters with no credentials, query or fragment, stored without a trailing `/`. Each broken rule is `422` with a fixed message that names the rule and never echoes the request. A slug used before, deleted connections included, is `409` before the key is checked and again under the lock; an Azure or Custom connection is never brought back. The key is checked at the base URL, then stored with `platform.llm_provider.created` carrying the base URL, and the API answers `201`. A known provider with a slug, name or base URL, or Azure or Custom without all three, gets the fixed `422`.
- Changed: `LlmProviderKeyChecker` raises `BaseUrlNotAnApi` when an Azure or Custom base URL answers with a redirect, a `404`, or a `200` whose `Content-Type` is not `application/json` or `+json`. Before, a redirect or `404` raised `LlmProviderUnreachable`, and any `200` accepted the key. The service turns it, and `BaseUrlNotPublic`, into `422`. Known providers are checked as before. The checker still reads only the status and headers, never the body. Decided with the maintainer: Azure and Custom take an admin-chosen name, and "not an API" is judged by status and content type. `LlmProviderRepository` gains `slug_used`, and its `add` takes the base URL. [`llm-providers.md`](../llm-providers.md) and the RBAC brief describe the request and its rules.
- Follow-up: PR 7 replaces any connection's key.

### 2026-11-17 — AF-447 — slice 2, PR 5

- Delivered: `POST /api/v1/platform/settings/llm-providers` with `{provider_type, api_key}` adds a known provider's connection, with its slug equal to the provider type and a fixed name. A provider already connected, or OpenRouter, is `409` before the key is checked. `LlmProviderKeyChecker` then checks the key: a refused key is `422` and no answer `503`, and nothing is stored. Under the per-slug advisory lock the API checks for a live connection again, then stores the encrypted key with `platform.llm_provider.created` in one transaction and answers `201` with the connection. A deleted connection with that slug is brought back with the same id, and the event says `revived: true`. No LiteLLM route is written. A read-only Personal API Key is refused, and Azure, Custom or a malformed request get the fixed `422`.
- Changed: `LlmProviderRepository.replace_key` shares the lock and event staging with the new `add`; its behaviour is unchanged, and `test_platform_llm_providers.py` and `test_openrouter_route_litellm_contract.py` pass. `operations-v1.json`, the RBAC brief, [`llm-providers.md`](../llm-providers.md) and [`domain-events.md`](../domain-events.md) describe the route and the event.
- Follow-up: PR 6 adds Azure and Custom connections.

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
