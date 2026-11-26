# LLM Providers

## Read when

Read before changing where provider keys come from, the LLM providers section of Platform Admin settings, the `llm_provider_connection`, `llm_provider_connection_organization` or `llm_provider_model` table, which Organizations a connection is open to, an Agent key's model list (`AgentKeyModelService`), how a provider's key is checked (`LlmProviderKeyChecker`), the LiteLLM routes the API registers, `OpenRouterKeyLookup`, or anything that calls OpenRouter with the platform's key (credits, cost repair, the credits metric).

## Role in the system

Agents never hold a provider key. They call LiteLLM with their own virtual keys, and LiteLLM calls the provider with the platform's key. An **LLM Provider Connection** is one of those platform accounts: a provider and the key Agent Barn reaches it with. It is a Platform Resource that Platform Administrators keep in Platform Admin settings.

**OpenRouter** is seeded by migration `22b93965859f` with no key. A Platform Administrator can add one connection each to Anthropic, OpenAI, Gemini, xAI, DeepSeek, Fireworks and Novita, and any number of Azure and Custom connections, replace any connection's key, and delete any connection but OpenRouter. Agents can't use the other providers yet, because only OpenRouter's key reaches LiteLLM; models and prices per connection, and Agents using them, come in later slices of the AF-447 epic ([`llm-providers/CHANGELOG.md`](llm-providers/CHANGELOG.md)). Why keys are platform data rather than deployment secrets is in [its ADR](../adr/2026-11-16-provider-keys-are-platform-data-synced-to-litellm.md).

## The connection

- Stored in `llm_provider_connection`: a unique `slug`, `name`, `provider_type`, `api_key_encrypted`, `api_key_last4`, `base_url`, `updated_by`, `updated_at`, `deleted_at` and `organization_access`.
- `organization_access` is the connection's Provider Access: `all`, `none`, `all_except` or `only`, `all` unless set otherwise. Migration `7847fc32d19c` set every existing connection, OpenRouter included, to `all`. The Organizations ticked for `all_except` and `only` are rows of `llm_provider_connection_organization` (`connection_id`, `organization_id`), each pair once. The database removes a row when its connection row is hard-deleted or its Organization is deleted, and deleting a connection through the API removes its rows. Platform Administrators set them when adding a connection and read and replace them through the [API](#api). What the access allows and refuses is in [Provider Access](#provider-access).
- The provider types are `openrouter`, `anthropic`, `openai`, `gemini`, `xai`, `deepseek`, `fireworks`, `novita`, `azure` and `custom`. A known provider has at most one connection, whose slug is its provider type and which has no `base_url`. An Azure or Custom connection has a slug of its own, which can't be any provider type's name, and a `base_url`.
- The key is Fernet-encrypted with `AGENT_TOKEN_ENCRYPTION_KEY`, as other stored secrets are. Its last four characters are kept apart, so listing the connections never decrypts it.
- Deleting a connection removes its LiteLLM routes, then deletes its models, sets `deleted_at` and purges the key and its last four characters, all under the connection's lock; the row keeps its slug, name and `base_url`. OpenRouter can't be deleted.
- Adding a known provider whose connection was deleted brings that row back, with the same id and the new key. An Azure or Custom connection is never brought back: a slug used before, deleted or not, is refused.
- An Azure or Custom connection's name is chosen by the Platform Administrator, at most 64 characters. Its base URL is a public HTTPS address, at most 2048 characters, with no credentials, query or fragment, and stored without a trailing `/`.
- A slug stays unique among deleted connections too, so it is never reused. The database refuses a malformed slug, an unknown provider type, a key without its last four characters or the reverse, and a connection that breaks its provider type's slug or `base_url` rule.

## Provider Access

Each connection says which Organizations may use it, in `organization_access`:

- `all`: every Organization, including Organizations created later;
- `none`: no Organization;
- `all_except`: every Organization but the listed ones, including Organizations created later;
- `only`: only the listed Organizations.

`can_use` in `api/domains/llm_providers/access.py` is the rule, and `LlmProviderAccessLookup` in `lookup.py` answers it for the domains that use a connection for an Organization. A deleted connection is open to no Organization.

**Only OpenRouter's access is enforced yet.** Organizations use only OpenRouter today, so the Organization side checks OpenRouter's access alone. Every other connection's access is stored, shown and edited, and takes effect once Organizations can use other providers, which AF-474's later slices bring: runtimes ready for any provider, then the Organization pool. An Organization without OpenRouter access:

- is offered no models: `GET .../agents/models` answers `[]`, with or without `catalog`, and appends no default;
- can't save an allowlist with entries, can't set its own default model, and can't hire an Agent or add a Bot. Each answers `400` "This organization has no LLM provider. Ask a Platform Administrator." (`NO_LLM_PROVIDER`). Saving an empty allowlist and clearing its own default are allowed;
- starts with an empty allowlist when it is created while OpenRouter is `none` or `only`. Under `all` or `all_except` it starts with the platform default model. This holds for every way an Organization is created: password and Google sign-up, a user a Platform Administrator sets up, and an Organization a user creates.

So until Organizations can use other providers, an Organization without OpenRouter access can't run Agents. The model pickers offer it none; they show the two fallback models only while the list loads or after a failed read.

**In use.** OpenRouter can't be withdrawn from an Organization that still uses it. A change after which an Organization could no longer use OpenRouter is refused with `409` while that Organization has a non-empty allowlist, its own default model, or any Agent not deleted, Bots and suspended Agents included. Only Organizations that would lose access are checked. Other connections are never in use yet, so their access can always change. Because of this rule no running Agent loses OpenRouter.

**No race.** A change of access checks use and writes under the connection's advisory lock, taken exclusive. Each Organization-side write that starts using OpenRouter checks access again in its own transaction, under the same lock taken shared, which holds until that transaction ends: an allowlist save with entries, its own default save, the Agent or Bot insert, and each Organization creation. So a withdrawal and such a write can't both commit on what each read before the other. The allowlist, default and hire writes also check first without the lock, so a hire is refused before a LiteLLM key is made.

**Waits.** Saving OpenRouter's key writes its LiteLLM route while holding the exclusive lock, and a change of OpenRouter's access holds it while it checks use. While either runs, those Organization-side writes wait for it. OpenRouter's models aren't saved, so no models save holds it.

**Enforced by LiteLLM.** Each Agent's LiteLLM key, a Bot's included, carries a model list, and LiteLLM answers `403` (`key_model_access_denied`) to any model the key doesn't list. The list holds the names the runtimes ask for, which drop the first segment (`litellm/openrouter/<id>` is asked for as `openrouter/<id>`):

- the Agent's own model, or its Organization's or the platform's default when it has none;
- the model its running pod started on (`running_model`), until that pod stops;
- every `DECISION_MODELS` value and the Platform Playbook model, sent as they are.

It lists none of the rest of the Organization's allowlist, so switching model in chat to anything else is refused. `AgentKeyModelService` (`api/domains/agents/key_models.py`) works the list out and sets it under a per-Agent advisory lock, reading the Agent as stored:

- a new Agent's or Bot's key is created with it;
- every start sets it before the pod is created. A start whose list can't be set fails with `500 PROVISIONING_FAILED`; a Bot whose list can't be set fails alone, and its parent and the other Bots start;
- a decision that LiteLLM rejects sets it and asks once more if that changed it ([Decisions](decisions.md#calls-billing-and-failures)); a Playbook Extraction sets it before its first model call and goes on if that fails ([Playbooks](playbooks.md#model-and-billing));
- the 15-minute LLM budget reconciliation sets the list of every live Agent key ([Operations](../guidelines/operations.md#organization-llm-budgets)).

Saving an allowlist, an Organization default, a decision model or the Playbook model doesn't touch keys. A changed default reaches an inheriting Agent's key at its next start, or at the next reconciliation. The allowlist and Provider Access are still checked in Agent Barn's API, when it offers models and when an allowlist, a default or an Agent is saved.

## Models

- Stored in `llm_provider_model`, added by migration `bc817a73bb6d`: the `connection_id`, a `model_id`, four per-token prices (`input_cost_per_token`, `output_cost_per_token`, `cache_read_input_token_cost`, `cache_creation_input_token_cost`, each `NUMERIC(24,18)`), a `price_source` and a `litellm_price_key`. The price columns carry LiteLLM's own route field names.
- A connection carries a model once; two connections may carry the same `model_id`. A `model_id` is 1 to 200 characters of `[A-Za-z0-9._:/-]`, so it can't hold `*`.
- `price_source` is `litellm` for a price read from LiteLLM's price list, with the key it was read under in `litellm_price_key`, or `manual` for a typed price, with no key.
- The database refuses an input or output price of zero or less, a negative cache price, a missing price, an unknown price source, a key that doesn't match the price source, a malformed `model_id` and a model of no connection.
- The API lists a connection's stored models and the models its provider lists ([Listing a provider's models](#listing-a-providers-models)), and saves them ([Saving models](#saving-models)); deleting a connection deletes its models. An Azure connection's models are its deployments, each named as in Azure and priced from the model it runs ([Azure deployments](#azure-deployments)).
- A connection holds at most 50 models (`MAX_MODELS_PER_CONNECTION`), which bounds how long a save holds the connection's lock. A new model's row id is `uuid5(connection id, model id)`, so a retried save writes the same route id.

## Invariants

- **Nobody reads the key back.** The list reports whether each connection has a key saved, its last four characters, who saved it and when, never the key. A refused request's `422` never echoes the body (`CredentialSafeRoute`), and the audit event carries no part of the key.
- **A key is checked before it is used.** The provider must accept it first ([Checking a key](#checking-a-key)). A key it refuses is `422` and no answer `503`; an Azure or Custom base URL that is not a public address, or does not answer like a model API, is `422`. A refused or unchecked key never reaches LiteLLM or the database.
- **LiteLLM first, then the database.** Under a per-connection advisory lock, the API writes the connection's LiteLLM routes and only then stores the encrypted key with its event, in one transaction. OpenRouter's key goes to its one route; any other connection's key is written to the route of each of its models, with the new base URL for Azure or Custom, and routes under its prefix with no model are removed. A LiteLLM failure is `503` and leaves the stored key and the event log unchanged. When a connection other than OpenRouter fails part-way, the API rewrites its routes with the stored key and base URL before answering, best effort, so no route keeps a key that was not saved. If that rewrite fails too, or LiteLLM applied a write the API saw fail (a timeout after the write, or a failed commit afterwards), LiteLLM holds a key the database does not; saving the key again repairs it, and leaves one route per model. Saving the connection's models repairs it too, since each route carries a fingerprint of its key.
- **Routes go before the rows.** Deleting a connection removes every LiteLLM route under its prefix under the same lock, before its models and key are deleted in one transaction with the event. LiteLLM drops a deleted route from its own database at once but from its running router a moment later, so for about a second after the delete answers, a call can still reach the route (seen at v1.108.6: still served at 0.8 s, gone by 1.8 s); a replaced key takes over in the same window. A LiteLLM failure is `503` and deletes nothing; a key replacement that takes the lock after a delete finds the connection gone, `404`, and writes no route.
- **No restart.** Saving a key registers or updates the connection's LiteLLM routes in the same request, so Agents use the new key at once. Adding a provider writes no route, since a new or revived connection has no models.
- **A base URL changes only with a new, checked key.** A replaced Azure or Custom key is checked at the new base URL if one is sent, else at the stored one. If the stored base URL changed while the key was checked, nothing is stored and the API answers `409`.
- **API startup does not sync keys to LiteLLM**, so the API's readiness never depends on the proxy being reachable ([API architecture](../architecture/api.md#startup-data)). Nothing copies `OPENROUTER_API_KEY` into the table; each environment's key is saved by hand (see [Moving off the environment key](#moving-off-the-environment-key)).

## Checking a key

OpenRouter's key is checked by `OpenRouterClient.check_key` with `GET {openrouter_base_url}/key` (`https://openrouter.ai/api/v1/key` by default).

Every other key is checked by `LlmProviderKeyChecker` (`api/infrastructure/llm_provider_keys/`). It sends one `GET` (a Custom endpoint may take two more, below), pinned to a checked public address, with redirects off and a 10-second timeout, and reads only the status and headers, never the body.

| Provider | Request | Key header |
| --- | --- | --- |
| Anthropic | `GET https://api.anthropic.com/v1/models` | `x-api-key`, with `anthropic-version: 2026-10-21` |
| OpenAI | `GET https://api.openai.com/v1/models` | `Authorization: Bearer` |
| Gemini | `GET https://generativelanguage.googleapis.com/v1beta/models` | `x-goog-api-key` |
| xAI | `GET https://api.x.ai/v1/models` | `Authorization: Bearer` |
| DeepSeek | `GET https://api.deepseek.com/models` | `Authorization: Bearer` |
| Fireworks | `GET https://api.fireworks.ai/v1/accounts` | `Authorization: Bearer` |
| Novita | `GET https://api.novita.ai/v3/user` | `Authorization: Bearer` |
| Azure | `GET {base_url}/openai/v1/models`, the base URL being the resource endpoint such as `https://<resource>.openai.azure.com` | `api-key` |
| Custom | `GET {base_url}/models` | `Authorization: Bearer` |

`200` accepts the key. `401` or `403` refuses it, and for Gemini and xAI so does `400`. Any other answer, or none, means the provider could not be reached. For Azure and Custom, a base URL whose host is not a public address is refused before any request, and a redirect, a `404`, or a `200` whose `Content-Type` is not `application/json` or `+json` means the base URL does not answer like a model API. A Custom server whose `/models` also answers `200` without any key, as OpenRouter's does, proves nothing about the key with it, so the checker then sends `POST {base_url}/chat/completions` with the key and an empty JSON body `{}`. Servers check the key before the body, so nothing is generated: `401` or `403` refuses the key, `400` or `422` (the missing input) or a `2xx` accepts it, `404` means the base URL does not answer like a model API, and anything else means it could not be reached. A server that needs no key at all answers `400` and is accepted, as any key works there. Why Fireworks, Gemini, Azure, Novita and xAI are checked this way is in the [change log](llm-providers/CHANGELOG.md) (slice 2, PR 2 and the review fixes).

## Listing a provider's models

`LlmProviderCatalogue` (`api/infrastructure/llm_provider_catalogue/`) reads a provider's model list with the connection's stored key. Like the key check, it resolves the host once, pins every request to that public address, and sends them with redirects off and a 10-second timeout.

| Provider | Request | Key header | Ids |
| --- | --- | --- | --- |
| Anthropic | `GET https://api.anthropic.com/v1/models?limit=1000`, then `after_id` while `has_more` | `x-api-key`, with `anthropic-version: 2026-10-21` | `data[].id` |
| OpenAI | `GET https://api.openai.com/v1/models` | `Authorization: Bearer` | `data[].id` |
| Gemini | `GET https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000`, then `pageToken` | `x-goog-api-key` | `models[].name` without `models/`, only where `supportedGenerationMethods` has `generateContent` |
| xAI | `GET https://api.x.ai/v1/language-models` | `Authorization: Bearer` | `models[].id` |
| DeepSeek | `GET https://api.deepseek.com/models` | `Authorization: Bearer` | `data[].id` |
| Fireworks | `GET https://api.fireworks.ai/v1/accounts/fireworks/models?filter=supports_serverless=true&pageSize=200`, then `pageToken` | `Authorization: Bearer` | the full `models[].name`, only where `conversationConfig` is set |
| Novita | `GET https://api.novita.ai/openai/v1/models` | `Authorization: Bearer` | `data[].id` |
| Custom | `GET {base_url}/models` | `Authorization: Bearer` | `data[].id` |

OpenRouter's models are not stored, and Azure deployments are added by name, so neither is listed. A listing asks for an uncompressed body and reads at most 5 pages, each up to 2 MiB, and at most 1,000 entries in all, within 30 seconds overall. Ids a model row can't hold are left out, and the rest come back sorted, each once. `401` or `403` refuses the key, and for Gemini and xAI so does `400`, since that is how both refuse an invalid key; `429` says the provider is limiting requests; any other answer, none, or a listing still arriving after 30 seconds means the provider could not be reached; a body that is not a model list, is compressed, or is over a cap, can't be read.

`GET .../{slug}/model-catalogue` pairs each listed id with LiteLLM's built-in price list (`LiteLLMClient.get_model_prices()`), looking it up under `litellm_price_key()`: the bare id for OpenAI and Anthropic, and `gemini/`, `xai/`, `deepseek/`, `fireworks_ai/` or `novita/` before the id for the rest. Only an entry whose `mode` is `chat` gives prices; Custom models never have a key, so they get none. Each price is rounded to 18 decimal places, ties away from zero, as `NUMERIC(24,18)` stores it (https://www.postgresql.org/docs/current/datatype-numeric.html), and a cache price the list doesn't give is the input price. `prices_differ` marks a stored model that has those prices but stores any of the four differently, compared as decimals. A stored model the provider no longer lists is not in the answer; `GET .../{slug}/models` has it.

## Saving models

`PUT .../{slug}/models` takes every model the connection should have, `{"models": [{"model_id", "price"}]}`; a stored model left out is removed. `price` is one of:

- `"litellm"`: LiteLLM's chat price, as `model-catalogue` shows it, stored with `price_source` `litellm` and its `litellm_price_key`;
- `"stored"`: the model's stored prices, unchanged, for a model already stored;
- the four per-token prices as decimal strings, stored as `manual`.

After finding the connection, refused as for `model-catalogue`, the API checks the body and refuses, with a fixed `422` naming the rule, more than 50 models, a model given twice, an id a model row can't hold, a price choice it doesn't know, a typed price that is missing, not a number, 1,000,000 or more, or has more than 18 decimal places, an input or output price of 0 or less, and a negative cache price. It then refuses `"stored"` for a model not stored, reads the provider's list with the stored key, refuses a model the list doesn't have, and, only if a model asks for `"litellm"`, reads LiteLLM's price list and refuses a model without a chat price there. Custom models have no price key, so they take typed prices only. The provider's and LiteLLM's failures give the same statuses as `model-catalogue`. Azure differs; see [Azure deployments](#azure-deployments).

Under the connection's lock, the save is refused with `409` if the stored key or base URL is no longer the one the provider's list was read with, or a model to keep is no longer stored, and with `404` if the connection was deleted. LiteLLM's routes are reconciled first: a wanted route is written only when LiteLLM lists it differently, and the connection's routes with no model are removed. Then the rows are written and `platform.llm_provider.models_changed` is staged in one transaction. A LiteLLM failure is `503` and stores nothing; saving again repairs the routes. A save that adds, removes and reprices nothing stores nothing and records no event, though it still writes any route LiteLLM is missing.

## Azure deployments

Azure gives no list of deployments for an `api-key`, so a Platform Administrator types each deployment's name, which is its `model_id` and its route's `azure/<deployment>`. A name is 1 to 64 characters of `[A-Za-z0-9._-]` (`AZURE_DEPLOYMENT_PATTERN`); Microsoft states no rule, so this one is ours. The provider is never asked, so a name that doesn't exist in Azure is saved and only fails when the route is called.

A deployment priced from LiteLLM sends `"price": "litellm"` with `runs_model`, the model it runs as LiteLLM's price list names it without `azure/`, such as `gpt-4o` or `eu/gpt-4o`; it takes the `azure/<runs_model>` chat price, stored under that `litellm_price_key`. `"stored"` and typed prices take no `runs_model`. `"litellm"` without `runs_model`, `runs_model` with any other price or on another provider, and a `runs_model` with no chat price are each refused with a fixed `422`. Changing the model a deployment runs changes its price key, so it is repriced.

For Azure, `GET .../{slug}/model-catalogue` lists the models a deployment can run instead of asking the provider: every `azure/` chat entry in LiteLLM's price list with an input and output price above 0, sorted, with `model_id` the name without `azure/` and the prices as for other providers. `stored` is true when a stored deployment is priced from that entry's key, and `prices_differ` when such a deployment stores other prices; a deployment with typed prices matches no entry. The UI matches deployments to entries by `litellm_price_key`.

## LiteLLM routes

LiteLLM's model store is on (`store_model_in_db: true`), so routes the API registers persist in LiteLLM's database with their keys encrypted under `LITELLM_SALT_KEY`. That value must never change; see the [operations guide](../guidelines/operations.md#litellm-salt-key).

| Route | Comes from | Order |
| --- | --- | --- |
| `agentbarn:openrouter` (`openrouter/*`, `https://openrouter.ai/api/v1`, background health check off) | Saved by a Platform Administrator; written with `LiteLLMClient.upsert_model_deployment` | 1 |
| Config-file `openrouter/*` | `OPENROUTER_API_KEY`, rendered only while it is set | 2 |

LiteLLM sends a request to the lowest-order healthy route, so once a key is saved the config-file route is used only while the saved route is unavailable.

A replaced key applies at once only on LiteLLM v1.101.0 or later. Earlier versions never removed a wildcard route's replaced entry from their router, so the old key kept serving `openrouter/*` until LiteLLM restarted.

Each LLM Provider Model of a connection other than OpenRouter gets a route of its own, built by `build_model_deployment` in `api/domains/llm_providers/litellm_deployments.py`. Saving the connection's models writes the routes LiteLLM lists differently and removes those with no model ([Saving models](#saving-models)), replacing the key rewrites them all, and deleting the connection removes them. A route is named `<slug>/<model_id>`, its id is `agentbarn:model:<connection id>:<model row id>`, its background health check is off, and it carries the connection's key and all four of the model's prices, sent as floats because LiteLLM holds route prices as floats. LiteLLM lists a route without its key, so the route's `model_info` also carries `key_fingerprint`, the first 16 hex characters of the key's SHA-256 (`key_fingerprint()`); a save compares it to tell a route left on another key from a current one. The reconcile lists the connection's routes before writing, so each write tells `upsert_model_deployment` whether the route exists and costs one LiteLLM call.

| Provider | `model` | Also sent |
| --- | --- | --- |
| OpenAI, Anthropic, Gemini, xAI | `openai/<id>`, `anthropic/<id>`, `gemini/<id>`, `xai/<id>` | — |
| DeepSeek | `deepseek/<id>` | `api_base` `https://api.deepseek.com`; LiteLLM's own default is `https://api.deepseek.com/beta` |
| Fireworks | `fireworks_ai/<id>` | — |
| Novita | `novita/<id>` | `api_base` `https://api.novita.ai/openai`; LiteLLM's own default is `https://api.novita.ai/v3/openai` |
| Azure | `azure/<deployment>` | `api_base` the stored resource endpoint and `api_version` `v1`, so LiteLLM calls `{api_base}/openai/v1/` |
| Custom | `openai/<id>` | `api_base` the stored base URL, unchanged |

### How LiteLLM serves and bills these routes

`api/tests/integration/test_provider_model_routes_litellm_contract.py` checks this against LiteLLM v1.108.6:

- A route serves with its connection's key, and `x-litellm-response-cost` uses the route's four prices, not the ones LiteLLM's list has for the model. A cache price of 0 stays 0, also after a save sets it; LiteLLM fills in only the cache prices a route leaves unset (`router.py:9541-9567`).
- A save that changes nothing writes no route, so the routes `/model/info` lists compare equal to the ones the API builds.
- A replaced key serves the next request.
- A name with no route, whether never ticked, unknown or removed, is refused with `400` and never reaches the provider.
- Two connections can save the same model, and `<slug>/<model_id>` reaches only that connection's route. A request for the raw LiteLLM model string, such as `openai/gpt-4o`, is matched against each route's `model` (`router.py:13641-13645`) and served by one of the routes that have it, with that route's key and price. Teams carry no model list (`LiteLLMClient._create_team`), but an Agent key lists only its own models and the platform's ([Provider Access](#provider-access)), so an Agent reaches a connection's model this way only when that string is on its key.
- Routes leave LiteLLM's price list as it was, so `model-catalogue` still shows LiteLLM's own price for a model a route prices differently.
- LiteLLM copies onto a route, from its own list, the rates the route doesn't set: the priority and flex tier rates, the 1-hour cache-write rate, and the cache rates for prompts over 200k tokens (`router.py:9541-9567,9594-9617,10834-10849`). A response served at the priority tier is billed at LiteLLM's priority rates instead of the stored prices; the test checks this. A prompt over 200k tokens has its cached tokens billed at LiteLLM's rate for that size (`litellm_core_utils/llm_cost_calc/utils.py:657-799`). In v1.108.6's bundled list, 279 chat models have a priority input rate, 213 a 1-hour cache-write rate and 78 a cache-read rate above 200k tokens.

## The API's own OpenRouter calls

`OpenRouterKeyLookup.api_key()` returns the saved key, else `OPENROUTER_API_KEY`, else empty. The platform credit balance, cost repair (`CostSynchronizer`) and the `agentbarn_openrouter_credits_remaining` metric resolve it each time they run, so a new key reaches them without a restart; the metric polls again at once when the key changes and reports `scrape_ok` 0 when the key cannot be read. The model catalogue is fetched without a key. See [Costs](costs.md).

## API

Every route is under `require_platform_admin`, which refuses writes from a read-only API key.

| Route | Does |
| --- | --- |
| `GET /api/v1/platform/settings/llm-providers` | Lists the connections that are not deleted, OpenRouter first and then by name. Each has `slug`, `name`, `provider_type`, `base_url`, the key status (`has_api_key`, `api_key_last4`, `updated_at`, `updated_by`), its Provider Access (`organization_access`, and `organization_count`, how many Organizations it lists), `env_key_configured`, which is true only for OpenRouter while `OPENROUTER_API_KEY` is set, and `env_key_last4`, the variable's last four characters on OpenRouter while it is set and longer than 8 characters, and otherwise `null`; the variable itself is never returned |
| `POST /api/v1/platform/settings/llm-providers` | Adds a known provider, `{provider_type, api_key}`, or an Azure or Custom connection, `{provider_type, slug, name, base_url, api_key}`; the key is trimmed and at most 512 characters. Either may also carry `organization_access` (`all` unless sent) and `organization_ids`, under the same rules as `PUT .../{slug}/organizations`, whose breaches are `400` with the same messages; a deleted known provider brought back takes the access sent. Answers `201` with the connection. A provider already connected, OpenRouter, or an Azure or Custom slug used before is `409`; a slug, name or base URL that breaks its rule is `422` with a fixed message naming the rule. These and the access `400`s are refused before the key is checked. A refused key or base URL is `422` and no answer `503`, and nothing is stored |
| `PUT /api/v1/platform/settings/llm-providers/{slug}/key` | Replaces a connection's key, `{api_key}`, trimmed and at most 512 characters, with an optional new `base_url` for Azure or Custom; answers with the connection. OpenRouter's key is checked by OpenRouter, any other by `LlmProviderKeyChecker`; either is routed in LiteLLM before it is stored. An unknown or deleted slug is `404`; a base URL for any other provider, or one that breaks its rule, is `422` before the key is checked. A refused key or base URL is `422`, no answer or a LiteLLM failure `503`, and a stored base URL that changed meanwhile `409`; nothing is stored |
| `GET /api/v1/platform/settings/llm-providers/{slug}/models` | Lists the connection's stored models by `model_id`. Each has `model_id`, the four per-token prices `input_cost_per_token`, `output_cost_per_token`, `cache_read_input_token_cost` and `cache_creation_input_token_cost`, each a decimal string with 18 places such as `"0.000003000000000000"`, `price_source` (`litellm` or `manual`) and `litellm_price_key`. An unknown or deleted slug is `404`; OpenRouter, whose models are not stored, `409` |
| `GET /api/v1/platform/settings/llm-providers/{slug}/model-catalogue` | Lists the models the provider lists for the stored key, by `model_id`. Each has `model_id`, `stored` (whether this connection stores it), `litellm_price_key` and the four per-token prices from LiteLLM's chat prices, all `null` when there are none, and `prices_differ`. For Azure it lists LiteLLM's Azure chat models instead, by the model a deployment runs ([Azure deployments](#azure-deployments)). An unknown or deleted slug is `404`; OpenRouter and a connection without a key `409`. The provider refusing the stored key is `409`, no answer `503` and an unreadable list `502`; LiteLLM's price list failing is `503`. Nothing is stored |
| `PUT /api/v1/platform/settings/llm-providers/{slug}/models` | Makes the connection's models exactly `{"models": [{"model_id", "price"}]}`, `price` being `"litellm"`, `"stored"` or four typed prices ([Saving models](#saving-models)), and for an Azure deployment priced from LiteLLM a `runs_model` ([Azure deployments](#azure-deployments)); answers with the stored models as `GET .../{slug}/models` does. A body that breaks a rule, a model the provider doesn't list, or one LiteLLM has no chat price for is `422`; an unknown or deleted slug `404`; OpenRouter, a connection without a key, or a key or base URL changed meanwhile `409`; the provider's failures as for `model-catalogue`; and a LiteLLM failure `503`, with nothing stored |
| `GET /api/v1/platform/settings/llm-providers/{slug}/organizations` | Answers the connection's Provider Access, `{organization_access, organizations: [{id, name}]}`, its listed Organizations sorted by name. An unknown or deleted slug is `404` |
| `PUT /api/v1/platform/settings/llm-providers/{slug}/organizations` | Replaces the connection's Provider Access with `{organization_access, organization_ids}` and answers as `GET` does. The ids are listed only for `all_except` and `only`, at most 1000, each once (a repeated id counts once); `all` and `none` clear the list. These answer `400` with a fixed message: an unknown mode, more than 1000 ids, ids sent with `all` or `none`, and an id that is not an Organization. An unknown or deleted slug is `404`. For OpenRouter, the write is refused with `409` when an Organization that would lose access still uses it, that is, when it has a non-empty allowlist, its own default model, or any Agent not deleted (Bots and suspended Agents included). The message names up to 10 such Organizations, by name, with what each uses, and counts the rest. Other connections are never in use yet. The check and the write run under the connection's lock, which Organization-side writes take shared ([Provider Access](#provider-access)). The key's `updated_at` doesn't change |
| `DELETE /api/v1/platform/settings/llm-providers/{slug}` | Removes the connection's LiteLLM routes, then deletes its models, its listed Organizations and the connection and purges its key; answers `204`. OpenRouter is `409`, an unknown or already deleted slug `404`, and a LiteLLM failure `503` with nothing deleted |

A saved key records `platform.llm_provider.changed`, Platform scope, projected to Security Audit. Its payload is the connection id and slug, whether a key was replaced, the provider type, the base URL before and after, and display names. An added provider records `platform.llm_provider.created` the same way, with the provider type, base URL and whether a deleted connection was brought back. A deleted connection records `platform.llm_provider.deleted`, with the provider type, base URL and whether a key was purged. A models save that adds, removes or reprices a model records `platform.llm_provider.models_changed`, with the provider type, the number added, removed and repriced, up to 20 ids of each and whether any list was cut; a model is repriced when any of its prices, its price source or its LiteLLM price key changes. A change to a connection's Provider Access records `platform.llm_provider.organizations_changed`, with the mode before and after, the number of listed Organizations added and removed, up to 20 ids of each and whether any list was cut; a save that changes nothing records none. An added connection whose access isn't `all` records it after `platform.llm_provider.created`, as a change from `all`. See [domain events](domain-events.md).

## UI

Platform Admin settings → **LLM providers** (`/dashboard/platform/settings?section=llm-providers`, `ui/src/features/llm-providers/`) reads every connection from `GET /platform/settings/llm-providers`; a failed read can be retried. "Providers · X of Y connected" heads a grid of cards, three columns wide from the `md` breakpoint and one column below it, in this order: OpenRouter; Google, Anthropic, OpenAI, xAI, DeepSeek, Fireworks and Novita, connected or not; each Azure connection, then each Custom connection, in the API's order; then an "Azure OpenAI" card with "Add key" and a dashed "Custom endpoint" card with "Add endpoint". A provider is named by its title in `PROVIDER_TYPE_LABELS` (Gemini as "Google", Azure as "Azure OpenAI", Custom as "Custom endpoint") on its card, in dialog titles and labels, and in toasts; an Azure or Custom connection is named by its own name, with "Azure OpenAI · {base URL}" or "Custom endpoint · {base URL}" below it. Every other card has the subtitle in `PROVIDER_SUBTITLES`. Y counts OpenRouter while it is in the grid, the seven known providers and Azure; X counts those with a connection holding a saved key. Custom counts in neither.

A card with a saved key says "Connected", shows the key masked as `*******` plus its last four characters, OpenRouter's as `sk-*******` (other providers' keys don't all start with `sk-`), and "Saved" with the date and time it was saved. Otherwise it says "Not connected": OpenRouter's Manage menu then offers "Save a key", and a known provider with no connection offers "Add key".

While `OPENROUTER_API_KEY` is set (`env_key_configured`), OpenRouter's card is not in the grid, and Y doesn't count it. It is the one card under "Set by this deployment", above the grid, marked "Environment". It names `OPENROUTER_API_KEY` with `sk-*******` and the variable's last four characters (`env_key_last4`), and any saved key with who changed it when. Its status is "In use" while no key is saved, since LiteLLM then serves the variable through its config-file route, and "Fallback" once one is, since that route is then used only while the saved key's route is unavailable ([LiteLLM routes](#litellm-routes)). "Save a key" or "Replace key" in its Manage menu opens the key dialog below. Without the variable, the section is not shown and OpenRouter is the first card in the grid.

"Add key" on a known provider's card, "Add key" on the Azure OpenAI card and "Add endpoint" on the Custom endpoint card open a dialog titled "Add {title}" for that provider; there is no other way to add one, and OpenRouter can't be added. Azure and Custom also ask for a name, slug and base URL. The key is a password field. A refused add keeps the dialog open with the API's message; an empty key is not sent.

Every connection's card, OpenRouter's in the grid or under "Set by this deployment" included, has only "Manage", which opens a menu from the button, as the other Platform settings rows do. OpenRouter's menu has "Organizations" and "Replace key" ("Save a key" while it has none). Every other connection's has "Models" while a key is saved, "Organizations", "Replace key" ("Save a key" while it has none) and "Delete", in the menu's destructive style. Choosing one closes the menu and opens that action's own dialog.

"Replace key" opens a dialog with a password field and sends `PUT /platform/settings/llm-providers/{slug}/key`. For Azure and Custom the dialog also shows the base URL, filled in with the stored one; it is sent with the key only when it was changed. A refused or failed save keeps the dialog open with the API's message; an empty key is not sent. "Delete" asks for confirmation before it sends `DELETE /platform/settings/llm-providers/{slug}`; for Azure and Custom the confirmation says the slug can't be used again. A refused delete keeps the confirmation open with the API's message.

"Models" opens a dialog that reads `GET .../{slug}/model-catalogue` and `GET .../{slug}/models` each time it opens, and shows the models only once both reads made for that opening have answered, so a model another administrator saved since it was last opened is shown, ticked; it shows either read's failure with the API's message and Retry. Prices are shown per 1M tokens, shifted from the API's decimal strings as text rather than through floats. Typed prices are per 1M tokens too, shifted to per-token text before they are sent: up to 12 digits and 12 decimal places, input and output above 0, cache 0 or more; until every typed price keeps that rule, Save is disabled and the dialog says how to type them. "Save models" sends `PUT .../{slug}/models`; a refused or failed save keeps the dialog open with the API's message.

For the known providers and Custom, the dialog lists the models the provider lists, which can be filtered by id, and no more than 50 can be ticked (`MAX_MODELS_PER_CONNECTION`). For the known providers, "Select all priced" ticks every model the filter shows that LiteLLM prices, in list order until 50 are ticked, and says how many the limit left unticked; Custom has no LiteLLM prices, so it doesn't show it. A stored model starts ticked with its own prices. When LiteLLM's price for it changed, each differing price shows LiteLLM's beside it, and "Use LiteLLM's price" makes the save take LiteLLM's. A ticked model LiteLLM has no price for, and a stored model with typed prices, takes typed prices. A stored model the provider no longer lists is named apart, as removed by saving. The save sends each ticked model: `"litellm"` for a new model LiteLLM prices or an accepted LiteLLM price, `"stored"` for a stored model otherwise unchanged, and its typed prices when they are new or changed.

For Azure, the dialog lists the stored deployments as "{name} deployments". "Add deployment" adds a row whose name is typed; a name that breaks `AZURE_DEPLOYMENT_PATTERN` or repeats another says so and keeps Save disabled. A saved deployment's name can't be changed, so renaming one is removing it and adding another. Each row chooses the model it runs from the catalogue, or "Other (type prices)", which takes typed prices; a stored deployment is shown on the entry with its `litellm_price_key`, and one with typed prices, or priced from a model the catalogue no longer has, on Other with its stored prices. A stored deployment whose LiteLLM price changed shows and takes it as above. "Remove" leaves a deployment out of the save, and a row with no model chosen keeps Save disabled. The save sends `"stored"` for a stored deployment left as it was, `"litellm"` with `runs_model` for a newly chosen model or an accepted LiteLLM price, and its typed prices on Other when they are new or changed.

Each card shows its Provider Access under the key: "All organizations", "No organizations", "All except N" or "Only N", where N is `organization_count`. "Organizations" opens a dialog that reads `GET .../{slug}/organizations` each time it opens and shows its failure with the API's message and Retry. It offers All organizations, No organizations, All organizations except the ticked ones, and Only the ticked organizations. The last two list the platform's Organizations from `GET /platform/organizations`, 12 at a time with "Show more", filtered by that endpoint's search, with the stored ones ticked and a count of how many are ticked. "Save organizations" sends `PUT .../{slug}/organizations`, with no ids for All or None; a refusal, such as the `409` naming the Organizations that still use OpenRouter, keeps the dialog open with the API's message. The Add dialog has the same options under "Organizations", starting on All organizations, and sends `organization_access` and `organization_ids` only when another option is chosen.

When the Models, Organizations or Replace key dialog closes, focus returns to the Manage button it was opened from.

An added provider, a saved key, saved models, saved Organizations and a deleted connection are each confirmed by a toast.

## Moving off the environment key

`OPENROUTER_API_KEY` is optional. While it is set, LiteLLM serves it through the config-file route and the API falls back to it. Each environment's key is saved in Platform Admin settings before its GitHub secret is deleted; staging and k3s share one secret. The steps are in the [operations guide](../guidelines/operations.md#openrouter-key). Deleting a secret before its environments have a saved key leaves LiteLLM with no OpenRouter route.
