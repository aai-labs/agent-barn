# LLM Providers

## Read when

Read before changing where provider keys come from, the LLM providers section of Platform Admin settings, the `llm_provider_connection` table, the LiteLLM routes the API registers, `OpenRouterKeyLookup`, or anything that calls OpenRouter with the platform's key (credits, cost repair, the credits metric).

## Role in the system

Agents never hold a provider key. They call LiteLLM with their own virtual keys, and LiteLLM calls the provider with the platform's key. An **LLM Provider Connection** is one of those platform accounts: a provider and the key Agent Barn reaches it with. It is a Platform Resource that Platform Administrators keep in Platform Admin settings.

Today there is one connection, **OpenRouter**, seeded by migration `22b93965859f` with no key. More providers are being added as the AF-447 epic ([`llm-providers/CHANGELOG.md`](llm-providers/CHANGELOG.md)). Why keys are platform data rather than deployment secrets is in [its ADR](../adr/2026-11-16-provider-keys-are-platform-data-synced-to-litellm.md).

## The connection

- Stored in `llm_provider_connection`: a unique `slug`, `name`, `provider_type`, `api_key_encrypted`, `api_key_last4`, `updated_by`, `updated_at` and `deleted_at`.
- The key is Fernet-encrypted with `AGENT_TOKEN_ENCRYPTION_KEY`, as other stored secrets are. Its last four characters are kept apart, so the status never decrypts it.
- A slug stays unique among deleted connections too, so it is never reused. The database refuses a malformed slug, an unknown provider type, and a key without its last four characters or the reverse.

## Invariants

- **Nobody reads the key back.** The status reports whether a key is saved, its last four characters, who saved it and when, never the key. A refused request's `422` never echoes the body (`CredentialSafeRoute`), and the audit event carries no part of the key.
- **A key is checked before it is used.** OpenRouter's `GET /key` must accept it: a key it refuses (401 or 403) is `422`, no answer is `503`. A refused or unchecked key never reaches LiteLLM or the database.
- **LiteLLM first, then the database.** Under a per-connection advisory lock, the API writes the LiteLLM route and only then stores the encrypted key with its event, in one transaction. A LiteLLM failure is `503` and leaves the stored key and the event log unchanged. If LiteLLM applied the write but the API saw a failure (a timeout after the write, or a failed commit afterwards), LiteLLM holds a key the database does not; saving the key again repairs it.
- **No restart.** Saving registers or updates the LiteLLM route in the same request, so Agents use the new key at once.
- **API startup does not sync keys to LiteLLM**, so the API's readiness never depends on the proxy being reachable ([API architecture](../architecture/api.md#startup-data)). Nothing copies `OPENROUTER_API_KEY` into the table; each environment's key is saved by hand (see [Moving off the environment key](#moving-off-the-environment-key)).

## LiteLLM routes

LiteLLM's model store is on (`store_model_in_db: true`), so routes the API registers persist in LiteLLM's database with their keys encrypted under `LITELLM_SALT_KEY`. That value must never change; see the [operations guide](../guidelines/operations.md#litellm-salt-key).

| Route | Comes from | Order |
| --- | --- | --- |
| `agentbarn:openrouter` (`openrouter/*`, `https://openrouter.ai/api/v1`, background health check off) | Saved by a Platform Administrator; written with `LiteLLMClient.upsert_model_deployment` | 1 |
| Config-file `openrouter/*` | `OPENROUTER_API_KEY`, rendered only while it is set | 2 |

LiteLLM sends a request to the lowest-order healthy route, so once a key is saved the config-file route is used only while the saved route is unavailable.

## The API's own OpenRouter calls

`OpenRouterKeyLookup.api_key()` returns the saved key, else `OPENROUTER_API_KEY`, else empty. The platform credit balance, cost repair (`CostSynchronizer`) and the `agentbarn_openrouter_credits_remaining` metric resolve it each time they run, so a new key reaches them without a restart; the metric polls again at once when the key changes and reports `scrape_ok` 0 when the key cannot be read. The model catalogue is fetched without a key. See [Costs](costs.md).

## API

Both routes are under `require_platform_admin`, which refuses writes from a read-only API key.

| Route | Does |
| --- | --- |
| `GET /api/v1/platform/settings/llm-providers/openrouter` | The status: `has_api_key`, `api_key_last4`, `updated_at`, `updated_by` (a name) and `env_key_configured` (whether `OPENROUTER_API_KEY` is set) |
| `PUT /api/v1/platform/settings/llm-providers/openrouter` | Replaces the key, `{api_key}`, trimmed and at most 512 characters; answers with the status |

A saved key records `platform.llm_provider.changed`, Platform scope, projected to Security Audit. Its payload is the connection id and slug, whether a key was replaced, and display names. See [domain events](domain-events.md).

## UI

Platform Admin settings → **LLM providers** (`/dashboard/platform/settings?section=llm-providers`, `ui/src/features/llm-providers/`) shows an OpenRouter card:

- a saved key: masked as `sk-*******` plus its last four characters, and who changed it when;
- no key: whether Agents are using `OPENROUTER_API_KEY` meanwhile, or that they cannot call OpenRouter models until a key is saved;
- a saved key while `OPENROUTER_API_KEY` is still set: a note that the secret can be deleted once every environment sharing it has a saved key.

"Save a key" or "Replace key" opens a dialog with a password field. A refused or failed save keeps the dialog open with the API's message; an empty key is not sent.

## Moving off the environment key

`OPENROUTER_API_KEY` is optional. While it is set, LiteLLM serves it through the config-file route and the API falls back to it. Each environment's key is saved in Platform Admin settings before its GitHub secret is deleted; staging and k3s share one secret. The steps are in the [operations guide](../guidelines/operations.md#openrouter-key). Deleting a secret before its environments have a saved key leaves LiteLLM with no OpenRouter route.
