# LLM providers in Platform Admin settings — change log

Status: Active
Epic: AF-447
Related context: [`../llm-providers.md`](../llm-providers.md), [`../../adr/2026-11-16-provider-keys-are-platform-data-synced-to-litellm.md`](../../adr/2026-11-16-provider-keys-are-platform-data-synced-to-litellm.md), [`../costs.md`](../costs.md), [`../agent-settings.md`](../agent-settings.md), [`../../guidelines/operations.md`](../../guidelines/operations.md)

## Current state

- Delivered: slice 1, the OpenRouter key in Platform Admin settings ([feature doc](../llm-providers.md)). A Platform Administrator can read the OpenRouter key status and replace the key; saving it registers the `agentbarn:openrouter` LiteLLM route at `order: 1`. The credit balance, cost repair and the credits metric use the saved key. LiteLLM persists database routes with their provider keys encrypted under `LITELLM_SALT_KEY`; its config-file OpenRouter route is at `order: 2`, so a healthy route with a lower order is used instead.
- In transition: until a Platform Administrator saves a key, LiteLLM serves `OPENROUTER_API_KEY` through its config-file route and the API falls back to it. Each environment moves its key by hand; see the operations guide's OpenRouter key section. Keys saved for other providers are not synced to LiteLLM until slice 3, so Agents can't use them yet.
- Delivered: slice 2, connections to other providers ([feature doc](../llm-providers.md)). In Platform Admin settings and through the API, a Platform Administrator can add one connection each to Anthropic, OpenAI, Gemini, xAI, DeepSeek, Fireworks and Novita, and any number of Azure and Custom connections. Any connection's key can be replaced, with a new base URL for Azure or Custom, and any connection but OpenRouter deleted. Each key is checked with its provider before it is stored, and every addition, replacement and deletion is audited. OpenRouter's key is read from the connection list and replaced through `PUT .../openrouter/key`; the OpenRouter-only routes are gone.
- Delivered: slice 3, PRs 1 to 16. LiteLLM uses the price list bundled in its image, so it changes only on a LiteLLM upgrade. The `llm_provider_model` table holds each connection's models with their prices. `GET .../{slug}/models` lists them with exact prices, and `PUT .../{slug}/models` saves them for every provider but OpenRouter, Azure's as deployments priced from the model each runs, writing each model's LiteLLM route under the connection's lock and recording `platform.llm_provider.models_changed`. `GET .../{slug}/model-catalogue` lists the models the provider lists for the stored key, read by `LlmProviderCatalogue`, with LiteLLM's chat prices from `LiteLLMClient.get_model_prices()`, and marks which are stored and whose stored prices differ. Under the connection's lock, replacing a key rewrites the LiteLLM route of each of the connection's models before the key is stored, and deleting a connection removes its routes before its models and key. A contract test checks how a real LiteLLM serves and bills these routes. In the UI, every connection but OpenRouter has a Models dialog: it ticks a provider's models, priced by LiteLLM or by typed prices, edits Azure deployments with the model each runs or typed prices, and takes a changed LiteLLM price once accepted.
- Next: slice 3, PR 17, the feature doc for slice 3 delivered and its known limits.
- Delivered: providers page layout, PRs 1 to 4. `GET .../llm-providers` reports `env_key_last4`, the last four characters of `OPENROUTER_API_KEY`, on OpenRouter while the variable is set. While it is set, the settings page shows OpenRouter's card under "Set by this deployment", with the variable's last four, any saved key, and "In use" or "Fallback". Below it, "Providers · X of Y connected" is a grid with a card per provider, connected or not, one per Azure or Custom connection, and cards to add Azure and Custom connections; providers are named by their titles, Gemini as "Google". OpenRouter's card has only its key button; every other connection's card has only "Manage", whose menu leads to Models, Replace key and Delete. The providers page layout is complete.
- In progress: AF-474, Provider Access per Organization, PR 1 of 14. Each connection stores `organization_access` (`all`, `none`, `all_except` or `only`; every existing connection is `all`) and the Organizations listed for it; nothing reads them yet. Next: PR 2, the access rule, its lookup and the shared lock.
- Blockers: `LITELLM_SALT_KEY`, `STAGING_LITELLM_SALT_KEY` and `PUBLIC_LITELLM_SALT_KEY` GitHub secrets must exist before the next deploy.

## Changes

### 2026-11-24 — AF-474 — provider access, PR 1

- Delivered: migration `7847fc32d19c` adds `llm_provider_connection.organization_access`, a non-native string enum of `all`, `none`, `all_except` or `only` with the CHECK `ck_llm_provider_connection_organization_access_known` and `server_default` `all`, so every existing connection, OpenRouter included, stays open to all Organizations. It adds `llm_provider_connection_organization` (`connection_id`, `organization_id`), whose primary key is both columns and whose foreign keys both cascade, as `organization_agent_sizes` does, with an index on `organization_id` for the cascade from an Organization delete, since PostgreSQL does not index referencing columns itself (https://www.postgresql.org/docs/current/ddl-constraints.html#DDL-CONSTRAINTS-FK). `OrganizationAccess` and `LlmProviderConnectionOrganization` are in `api/domains/llm_providers/models.py`. [`llm-providers.md`](../llm-providers.md) describes both; `CONTEXT.md` defines Provider Access.
- Unchanged: `database_is_clean` (`api/tests/steps/database.py`). Its connection delete cascades to the listed Organizations, and its OpenRouter insert gets `all` from the server default.
- Release impact: the upgrade only adds; the downgrade drops the mode and every listed Organization.
- Verification: `test_llm_provider_connection_migration.py` covers existing connections (a live, a deleted and OpenRouter) becoming `all` with nothing listed, the default, each mode, unknown modes refused by the CHECK, a pair listed twice, an unknown connection or Organization, both cascades, the downgrade, and a reset that leaves OpenRouter at `all` with nothing listed. 13 of the 14 new or changed tests were run before the change and failed; the default test was not in that run. All 61 tests in the file pass in four `-k` batches. ruff, ruff format, `ty` and `make check-migrations` pass.

### 2026-11-24 — AF-447 — review follow-ups for slice 3 and the providers page

- Fixed: a key replacement that failed part-way left the routes it had already written on the new key while the database kept the old one, until a later save repaired them through the key fingerprint (review fixes 2). The API now rewrites the connection's routes with the stored key and base URL before answering `503`, best effort.
- Fixed: `LlmProviderCatalogue` asks for an uncompressed list and refuses a compressed one instead of inflating it, gives up on a listing after 30 seconds overall (`LIST_DEADLINE_SECONDS`), and reports a `429` as "{name} is limiting requests. Try again in a minute." instead of unreachable. Gemini's and xAI's `400` still refuses the key, since that is how both refuse an invalid one.
- Fixed: `env_key_last4` is `null` for an `OPENROUTER_API_KEY` of 8 characters or fewer, whose last four would show most of it.
- Fixed: the Models dialog read the provider's list again on every page refresh after it closed, and once more after each save. It now reads only while open and marks its lists stale on save. Focus returns to the card's Manage button when it closes, which is now a non-modal menu named "Manage {title}". Unnamed Azure deployments are labelled by position ("new deployment 3"), and a model stored at typed prices says "LiteLLM has a price for it" instead of "LiteLLM's price has changed".
- Fixed (found on a local stack with a real OpenRouter key): a Custom endpoint whose `/models` answers without a key, as OpenRouter's does, accepted any key, and a bad one was then written to every model route, whose calls failed `401`. `LlmProviderKeyChecker` now sends such an endpoint an empty chat request with the key: `401`/`403` refuses it, `400`/`422` accepts it, and nothing is generated.
- Fixed: the key dialog gave focus to the page after a real key check, which takes about a second with Save disabled; it now returns focus to Manage, as the Models dialog does.
- Fixed: at phone width, model ids and deployment names wrapped a few letters a line; the tables now scroll sideways instead.
- Documented: LiteLLM keeps serving a deleted route for about a second after the delete answers.
- Verification: new tests for each fix, and each guard mutated once to see its test fail. `test_platform_llm_provider_connections.py`, the catalogue unit tests, and all 59 tests in `ui/tests/e2e/platform-llm-providers.spec.ts` pass. A click-through on a local stack (this API, LiteLLM v1.108.6, Postgres, the Next UI, real OpenRouter) added a Custom endpoint, listed 230 models, saved one at typed prices and billed a real call at exactly those prices.

### 2026-11-24 — AF-447 — slice 3, review fixes 2

- Fixed: a key replacement that failed part way left some routes on the new key, which was never stored, and a Models save did not rewrite them, because LiteLLM lists a route without its key and the save compared everything else. Each model route's `model_info` now carries `key_fingerprint`, the first 16 hex characters of its key's SHA-256, so the save rewrites a route left on another key.
- Changed: reconciling a connection's routes tells each write whether LiteLLM already lists the route, instead of `upsert_model_deployment` looking it up, so a write is one LiteLLM call instead of two while the connection's lock is held: 50 calls rather than about 100 for a 50-model key replacement.
- Changed: deleting a connection now says its models are removed with its key.
- Restored: `test_llm_provider_connection_migration.py`, removed in PR 2, as you asked; it passes unchanged. It now covers migration `bc817a73bb6d` too: the table starts empty, a typed and a LiteLLM-priced model are accepted with prices down to 1e-18, each check constraint refuses its row, a repeated model or one without its connection is refused, the model matches the migration, and the downgrade drops the table and keeps the connections.
- Verification: the connections, migration, LiteLLM client, deployment and domain event tests pass, as does the contract test against a real LiteLLM v1.108.6, which shows LiteLLM lists `key_fingerprint` back, so an unchanged save writes no route. `ui/tests/e2e/platform-llm-providers.spec.ts` passes. New tests fail when the fingerprint is dropped, when `exists` is inverted, and when a migration check constraint is removed.

### 2026-11-23 — AF-447 — providers page layout, PR 4 follow-up

- Changed: "Manage" opens a dropdown menu instead of a dialog, as you chose, because the PR 4 dialog didn't match the rest of the app. Agent sizes (`agent-sizes-settings.tsx`), Tiers (`tiers-settings.tsx`) and workflow cards (`workflow-card.tsx`) put an item's actions in the shared `DropdownMenu`, and no other page uses a dialog that only lists actions. `manage-provider-menu.tsx` replaces `manage-provider-dialog.tsx`: the menu opens from the card's button with Models (while a key is saved), Replace key or Save a key, and Delete as a `destructive` item. Each item opens the same dialog as before. The card takes the menu as its `manage` slot, and the settings page no longer keeps Manage state.
- Verification: in `ui/tests/e2e/platform-llm-providers.spec.ts`, the Manage tests now look for a menu and its items. They check that Manage has `aria-haspopup="menu"` and opens no dialog, that Delete is the destructive item, and that Manage still opens after a dialog it led to is closed. Three tests failed before the change. While the menu is open, Radix hides everything outside it from the accessibility tree (`hideOthers`, `@radix-ui/react-menu` `dist/index.mjs:137`; the dropdown is modal by default, `@radix-ui/react-dropdown-menu` `dist/index.mjs:31`). The test therefore checks the trigger's `aria-haspopup` before opening rather than its `aria-expanded` while open. The whole spec (51 tests) passes in four shards of two workers, and `tsc --noEmit` and eslint pass. A screenshot of the open menu matches the other Platform settings menus.

### 2026-11-23 — AF-447 — providers page layout, PR 4

- Delivered: the Manage dialog (`manage-provider-dialog.tsx`). Every connection's card but OpenRouter's has only "Manage", which opens "Manage {title}" with the card's subtitle and stacked actions: "Models" while a key is saved, "Replace key" ("Save a key" without one) and "Delete" in the error colour. Choosing one closes Manage and opens the existing models dialog, key dialog or delete confirmation. OpenRouter's card, in the grid or under "Set by this deployment", has only "Replace key" or "Save a key". The dialog's title, description, button style and Delete's colour are my choices, made without a mockup to check against.
- Fixed: since slice 3, the add, key and models dialogs were keyed by separate counters, so two of them could share a React key. After opening Models and then a key dialog, Cancel no longer closed the key dialog. The keys are now prefixed (`add-`, `key-`, `models-`).
- Changed: the page object opens Replace key, Delete and Models through Manage (`openReplaceKey`, `openDelete`, `openModels`) in place of the removed card-button locators.
- Verification: `ui/tests/e2e/platform-llm-providers.spec.ts` now checks four things. A connected card has only "Manage", which lists Models, Replace key and Delete. Each action closes Manage and opens its own dialog. Manage offers Models on Anthropic, Azure and Custom connections. OpenRouter has only its key button. Before the change, 8 new or changed tests failed. The whole spec (51 tests) passes in four shards of two workers, and `tsc --noEmit` and eslint pass.

### 2026-11-23 — AF-447 — providers page layout, PR 3

- Delivered: the providers grid. "Providers · X of Y connected" heads cards three columns wide from `md` and one column on a phone: OpenRouter while `OPENROUTER_API_KEY` is unset; Google, Anthropic, OpenAI, xAI, DeepSeek, Fireworks and Novita, connected or not; each Azure and then each Custom connection; then an "Azure OpenAI" card with "Add key" and a dashed "Custom endpoint" card with "Add endpoint", always shown. Each card has an initials tile, its title and subtitle, and a dot with "Connected" (the masked key and "Saved" with the date) or "Not connected". Y counts OpenRouter while it is in the grid, the seven known providers and Azure; X counts those with a saved key; Custom counts in neither, as you chose.
- Changed: "Add provider" and its provider select are gone. "Add key" or "Add endpoint" on a card opens the add dialog for that provider, titled "Add {title}". Connected cards keep Models, Replace key and Delete until PR 4, as you chose, and show "Saved {date}" without who saved it, as you chose. OpenRouter's "Agents cannot call OpenRouter models until a key is saved." became "Not connected".
- Changed: `PROVIDER_TYPE_LABELS` holds the titles (Gemini is "Google", Azure "Azure OpenAI", Custom "Custom endpoint"), and `PROVIDER_SUBTITLES` and `PROVIDER_INITIALS` are new. `providerTitle()` in `utils.ts` names a connection by its title, or Azure and Custom by their own names, in the cards, the add, key, models and delete dialogs and the toasts, as you chose. Stored names are unchanged. "Set by this deployment" takes its subtitle and initials from the same constants.
- Verification: `ui/tests/e2e/platform-llm-providers.spec.ts` covers the cards, their order, subtitles, statuses and add buttons, the count with and without OpenRouter in the grid, three columns on a desktop and one at 390px, adding from a card with no provider select, Google named on the card, in the dialogs and in toasts, and a deleted provider shown again as not connected. The 14 new or changed tests failed before the change. The whole spec (49 tests) passes in three shards of two workers, with `tsc --noEmit` and eslint.

### 2026-11-23 — AF-447 — providers page layout, PR 2

- Delivered: while `OPENROUTER_API_KEY` is set, OpenRouter's card leaves the list for a "Set by this deployment" section above it (`deployment-provider-card.tsx`). The card has an initials tile, the "Environment" badge, the subtitle "Models from many providers", `OPENROUTER_API_KEY` masked to `sk-*******` and its last four, any saved key with who changed it when, a status dot with "In use" (no saved key) or "Fallback" (a saved key), and "Save a key" or "Replace key". This is the layout you confirmed. Without the variable, the section isn't shown and OpenRouter stays the first card in the list.
- Changed: the two notes about `OPENROUTER_API_KEY` are gone from OpenRouter's list card; with the variable set, that card is no longer shown. Its no-key sentence, "Agents cannot call OpenRouter models until a key is saved.", stays until PR 3, as you chose. The `sk-*******` prefix moved to `constants.ts` so both cards share it, and the subtitle is a constant in the new card until PR 3 moves the subtitles to `constants.ts`, as you chose.
- Verification: `ui/tests/e2e/platform-llm-providers.spec.ts` covers the section with no saved key (In use, Save a key, OpenRouter out of the list), saving a key from it (Fallback, Replace key), a saved key with the variable set (both keys, no note), and no section without the variable. The first three failed before the change. The whole spec passes in three shards of two workers, with `tsc --noEmit` and eslint.

### 2026-11-23 — AF-447 — providers page layout, PR 1

- Delivered: each connection in `GET /api/v1/platform/settings/llm-providers` has `env_key_last4`. On OpenRouter, while `OPENROUTER_API_KEY` is set, it holds the variable's last four characters as set, the value `OpenRouterKeyLookup.api_key()` falls back to; on every other connection, and while the variable is empty, it is `null`. The variable itself is never returned. As with `api_key_last4`, a key of four characters or fewer would be shown whole, as you chose.
- Verification: `test_platform_llm_provider_connections.py` checks the last four on OpenRouter only, `null` without the variable, and that no other field carries the end of the key; the two tests that compare OpenRouter's whole entry expect the new field.

### 2026-11-23 — AF-447 — slice 3, review fixes

- Fixed: reopening the Models dialog showed the models from the previous opening while its reads ran again, and both editors kept that first snapshot, so a model or Azure deployment another administrator saved in between was left unticked and saving removed it. `useLlmProviderModels` now reports loading until both reads made after the dialog mounts have answered (`isFetchedAfterMount`, true after a success or a failure: `@tanstack/query-core` 5.101.4 `src/queryObserver.ts:580-582`), so each editor starts from what the API holds now.
- Unchanged: `test_llm_provider_connection_migration.py`, removed in PR 2, stays removed, as you chose, against `docs/guidelines/testing.md`'s migration-coverage rule.
- Verification: `ui/tests/e2e/platform-llm-providers.spec.ts` reopens the dialog after the stored models change, for a known provider and for Azure, and checks the newly stored model is shown and kept on save; both failed before the fix. The whole spec passes in two runs of two workers, with `tsc --noEmit` and eslint.

### 2026-11-23 — AF-447 — slice 3, PR 16 follow-up

- Delivered: "Select all priced" in the Models dialog of the known providers, as you asked. It ticks every model the filter shows that LiteLLM prices, in list order until 50 are ticked, and says how many the limit left unticked; models without a LiteLLM price and those already ticked are left alone, and the ticked models save as `"litellm"`. Custom doesn't show it, having no LiteLLM prices.
- Verification: `ui/tests/e2e/platform-llm-providers.spec.ts` covers ticking only priced models and the saved body, the filter, the 50 limit and its note, and the button's absence on Custom; the whole spec passes, with `tsc --noEmit` and eslint.

### 2026-11-23 — AF-447 — slice 3, PR 16

- Delivered: "Models" on Azure and Custom cards too, every card but OpenRouter's while a key is saved. Custom models, and known-provider models LiteLLM has no price for, can be ticked with four prices typed per 1M tokens, shifted to per-token text; Save stays disabled until input and output are above 0 and cache 0 or more, with at most 12 digits and 12 decimal places. A stored model with typed prices shows them for editing and is sent as `"stored"` unless they change.
- Delivered: a stored model whose LiteLLM price changed shows LiteLLM's beside each differing price, compared as decimals, and "Use LiteLLM's price" makes the save send `"litellm"` for it, saved with the rest by "Save models", as you chose. The dialog re-reads prices each time it opens, so it has no Refresh button.
- Delivered: Azure's dialog lists deployments. "Add deployment" adds a named row, checked against `AZURE_DEPLOYMENT_PATTERN` and the other names; each row picks the model it runs from LiteLLM's Azure models or "Other (type prices)", and "Remove" leaves it out of the save. A saved deployment's name is fixed, as you chose. A new or changed model is sent as `"litellm"` with `runs_model`.
- Changed: the Models dialog is a shell over `listed-models-picker.tsx` and `azure-deployments-editor.tsx`, sharing `model-price-cells.tsx`, `runs-model-combobox.tsx` and `save-models-footer.tsx`; the price helpers moved to `utils.ts`.
- Verification: `ui/tests/e2e/platform-llm-providers.spec.ts` covers typed prices for an unpriced and a Custom model with exact per-token bodies, a changed typed price, accepting a changed LiteLLM price, which cards have Models, and Azure adding, choosing a model, Other, bad and repeated names, a missing model, removing and accepting a changed price; the whole spec passes, with `tsc --noEmit` and eslint.
- Follow-up: PR 17, the feature doc for slice 3 delivered.

### 2026-11-23 — AF-447 — slice 3, PR 15

- Delivered: "Models" on the cards of Anthropic, OpenAI, Gemini, xAI, DeepSeek, Fireworks and Novita while a key is saved. Its dialog reads `model-catalogue` and `models`, lists the provider's models with a filter by id and their four prices per 1M tokens (a stored model's own, else LiteLLM's), shifted from the API's decimal strings as text rather than through floats. Stored models start ticked; a model without a LiteLLM price, and a 51st model, can't be ticked. "Save models" sends `"stored"` for a stored model and `"litellm"` for a new one, and a toast confirms it.
- Delivered: a stored model whose LiteLLM price changed says so, and a stored model the provider no longer lists is named apart as removed by saving, as you chose. A failed read shows the API's message with Retry; a refused save keeps the dialog open with the API's message, a `404` included.
- Changed: the delete confirmation's message helper is now `failureMessage` in `ui/src/features/llm-providers/utils.ts`, shared with the dialog. The models' query keys extend the feature's `llmProvidersKey.detail(slug)`, so `ui/src/shared/query-keys.ts` is unchanged.
- Verification: `ui/tests/e2e/platform-llm-providers.spec.ts` covers ticking and saving with exact prices and body, unticking, an unpriced model, the filter, the 50 limit, a refused save, a refused read and its retry, a model no longer listed, and which cards have Models; the whole spec passes, with `tsc --noEmit` and eslint.
- Follow-up: PR 16 adds Azure deployments, typed prices and accepting a changed LiteLLM price.

### 2026-11-23 — AF-447 — slice 3, PR 14

- Delivered: `test_provider_model_routes_litellm_contract.py` saves Custom models through the API into the pinned LiteLLM v1.108.6, with the connections seeded directly so their base URL can be the loopback stub, and the provider's list and key check mocked. It shows that a route serves with its connection's key at its four stored prices rather than LiteLLM's, that a cache price set to 0 stays 0 after the route is updated, that an unchanged save writes no route, that a replaced key serves the next request, that a never-ticked, unknown or removed name is refused with `400` without reaching the provider, and that LiteLLM's price list keeps its own price.
- Found: two connections saving the same model keep their own `<slug>/<model_id>` routes, but a request for the raw string (`openai/gpt-4o`) is served by one of them with its key and price. LiteLLM also copies its own priority and flex rates, 1-hour cache-write rate and over-200k cache rates onto a route, so a priority-tier response is billed at LiteLLM's rates instead of the stored ones. Both are recorded in [`llm-providers.md`](../llm-providers.md#how-litellm-serves-and-bills-these-routes) and left for PR 17's known limits; fixing the inherited rates would change the route shape and needs its own PR.
- Changed: `api/tests/helpers/litellm_model_store.py`'s stub is now `ChatCompletionsStub`, recording each request's key and model and sending the reply a test sets, and the pinned LiteLLM runs with `LITELLM_LOCAL_MODEL_COST_MAP=true` as the chart and Compose do. `test_openrouter_route_litellm_contract.py` uses the new name.
- Verification: both new tests and `test_openrouter_route_litellm_contract.py` pass locally, one at a time.
- Follow-up: PR 15, the Models dialog.

### 2026-11-23 — AF-447 — slice 3, PR 13

- Delivered: Azure deployments through `PUT .../{slug}/models`. A deployment's name is its `model_id`, 1 to 64 characters of `[A-Za-z0-9._-]`, the plan's own rule since Microsoft states none. `"litellm"` takes `runs_model`, the model the deployment runs as LiteLLM's price list names it without `azure/` (`gpt-4o`, `eu/gpt-4o`), and prices it from that `azure/` chat entry, stored as its `litellm_price_key`. `"stored"` and typed prices work as for other providers. Fixed `422`s refuse a bad deployment name, `"litellm"` without `runs_model`, `runs_model` with another price or on another provider, and a `runs_model` with no chat price. The provider is never asked, since Azure lists no deployments for an `api-key`, so a deployment that doesn't exist fails only when its route is called.
- Delivered: for Azure, `GET .../{slug}/model-catalogue` lists every `azure/` chat entry in LiteLLM's price list, sorted, by the name without `azure/`, with `stored` when a deployment is priced from it and `prices_differ` when such a deployment stores other prices, as you chose (option A). At v1.108.6 the bundled list has 197 such entries with an input and output price above 0, 109 of them with a region part such as `eu/`; the longest name is 36 characters.
- Removed: the `409` "Azure deployments are added by name." from both routes.
- Verification: `test_platform_llm_provider_connections.py` covers an Azure save with `runs_model` and typed prices (rows, routes with `api_version` `v1`, the event), switching the model a deployment runs, each new refusal, `runs_model` on Anthropic, and the Azure catalogue; the provider is asked in none of them. [`llm-providers.md`](../llm-providers.md) has an Azure deployments section and the [RBAC brief](../rbac/IMPLEMENTATION-BRIEF.md) notes the Azure catalogue.
- Follow-up: PR 14 checks the routes against a real LiteLLM; PR 16's UI matches Azure deployments to catalogue entries by `litellm_price_key`.

### 2026-11-23 — AF-447 — slice 3, PR 12

- Delivered: `PUT /api/v1/platform/settings/llm-providers/{slug}/models`, for Platform Administrators only, refusing a read-only Personal API Key. It takes every model the connection should have, each with `price` `"litellm"` (LiteLLM's chat price as `model-catalogue` shows it), `"stored"` (keep the stored prices) or four typed per-token prices as decimal strings (`manual`), and answers with the stored models. A stored model left out is removed.
- Delivered: fixed `422`s, as slice 2's slug, name and base-URL rules have, for more than 50 models, a model twice, an id a model row can't hold, an unknown price choice, a typed price that is missing, not a number, 1,000,000 or more (which `NUMERIC(24,18)` can't hold) or with more than 18 decimal places, an input or output price of 0 or less, a negative cache price, `"stored"` for a model not stored, a model the provider doesn't list, and `"litellm"` for a model without a chat price. The checks are in the service, because `CredentialSafeRoute` turns every schema `422` into its generic key message (`api/domains/llm_providers/routes.py:21-30`). OpenRouter, Azure and a connection without a key are `409` before anything is read, and the provider's and LiteLLM's failures give `model-catalogue`'s statuses.
- Delivered: `LlmProviderRepository.replace_models` takes the connection's lock, refuses with `ConnectionChanged` (`409`) when the stored key ciphertext or base URL is no longer the one read before the provider's list was, or a model to keep is gone, then calls the service's callback with the models the connection will have before it writes the rows and stages the event in one transaction. A LiteLLM failure is `503` "The model proxy could not be updated. Your models were not changed." and stores nothing.
- Delivered: on a models save, a route is written only when LiteLLM lists it differently: its `model_name`, every `litellm_params` field sent but the key, and every `model_info` field must match. At v1.108.6 LiteLLM keeps a route as `LiteLLM_Params.model_validate(...)` then `to_json(exclude_none=True)` (`litellm/router.py:9697-9794`), whose params allow extra fields and have no validator that rewrites `model`, `api_base`, `api_version` or the prices (`litellm/types/router.py:589-675`), so prices come back as the floats sent; `/model/info` renames only team routes (`litellm/proxy/proxy_server.py:16906-16930`), pops `api_key` and masks only keys with no `cost` segment (`litellm/proxy/common_utils/openai_endpoint_utils.py:32`, `litellm/litellm_core_utils/sensitive_data_masker.py:50,90-91`). The key isn't listed, so a stale key on a route isn't seen; replacing a key still rewrites every route.
- Delivered: a new model's row id is `uuid5(connection id, model id)`, as the plan specified; PR 2 left it the default `uuid7`. A retried save writes the same route id.
- Delivered: `platform.llm_provider.models_changed` is recorded when a save adds, removes or reprices a model, a model being repriced when a price, its price source or its LiteLLM price key changes. Each id list is sorted, then cut to 20, with `model_ids_truncated` set when one was cut. A save that changes nothing stores nothing and records no event, though it still writes a route LiteLLM is missing.
- Delivered: the ADR [one LiteLLM route per provider model, with explicit prices](../../adr/2026-11-23-one-litellm-route-per-model-with-explicit-prices.md) records the agreed decision and the accepted DNS-rebinding risk; `docs/INDEX.md` routes it. Its LiteLLM citations were checked again in v1.108.6 on 2026-11-23.
- Changed: Custom connections save typed prices here, as you chose; PR 13 adds Azure deployments only.
- Verification: `test_platform_llm_provider_connections.py` covers an Organization owner, a read-only key, a save with each price choice (with the routes and the event), a removal, a repricing that writes only its route, a price source change that writes no route, a save that changes nothing, one that restores a missing route, ids cut to 20, every body rule, a model the provider or LiteLLM can't back, each provider failure, LiteLLM's price list failing, a LiteLLM failure part-way and its retry, a missing or deleted slug, OpenRouter, Azure and a keyless connection, a key replaced, a model removed and the connection deleted while the provider's list was read, and Custom. [`llm-providers.md`](../llm-providers.md), [`domain-events.md`](../domain-events.md), the [RBAC brief](../rbac/IMPLEMENTATION-BRIEF.md) and `api/developer_docs/operations-v1.json` describe the route.
- Follow-up: PR 13 adds Azure deployments; PR 14 checks the route comparison against a real LiteLLM.

### 2026-11-23 — AF-447 — slice 3, PR 11

- Delivered: `GET /api/v1/platform/settings/llm-providers/{slug}/model-catalogue`, for Platform Administrators only, a read-only Personal API Key included. It decrypts the stored key, lists the provider's models with `LlmProviderCatalogue` (a Custom connection at its base URL), reads LiteLLM's price list, and answers each listed id, sorted, with `stored`, `litellm_price_key`, the four per-token prices and `prices_differ`. Nothing is stored and no lock is taken.
- Delivered: prices fill in only from a price-list entry whose `mode` is `chat`, looked up under `litellm_price_key()`; Custom has no price key, so its models get none. Each price is rounded to 18 decimal places with ties away from zero, as Postgres rounds `numeric` ("rounds ties away from zero", https://www.postgresql.org/docs/current/datatype-numeric.html), so what is shown is what `NUMERIC(24,18)` would store. A cache price the list doesn't give is shown as the input price, as the plan stores it. `prices_differ` is true for a stored model with chat prices whose stored prices differ in any of the four, compared as decimals.
- Delivered: OpenRouter is `409` "OpenRouter's models are not stored.", Azure `409` "Azure deployments are added by name." (PR 13 changes this), and a connection without a key `409`, all before the provider is asked. The database allows a live connection without a key, but the API never makes one: adding stores a key, and deleting purges it only as it soft-deletes (`repository.py:174-179,225-227`). The provider refusing the stored key is `409`, since the stored key, not the request, is the conflict, and `docs/guidelines/code.md:46-51` keeps `422` for schema validation. No answer is `503`, and an unreadable list `502`, as for other upstream answers the API can't read (`agent_memory/view_client.py:51`, `custom_api/gateway.py:105`). LiteLLM's price list failing is `503`. Every message is fixed and carries no key.
- Changed: checked against v1.108.6's bundled list on 2026-11-23: no chat price rounds to 0 at 18 places, none lands on an exact tie, and none reaches 1,000,000 per token, which `NUMERIC(24,18)` can't hold.
- Changed: a stored model the provider no longer lists is not in the answer; `GET .../{slug}/models` has it, for PR 15's dialog to merge.
- Verification: `test_platform_llm_provider_connections.py` covers an Organization owner (`403`), no sign-in (`401`), a read-only key, the exact body (a chat model, a non-chat entry, an unknown id, a missing cache price, a tie rounded away from zero, a stored model matching and one differing, and a model stored only by another connection), a difference in each of the four prices, a Custom connection, each provider failure, LiteLLM failing, a missing or deleted slug, and OpenRouter, Azure and a keyless connection refused before the provider is asked. [`llm-providers.md`](../llm-providers.md) describes the listing, the [RBAC brief](../rbac/IMPLEMENTATION-BRIEF.md) and `api/developer_docs/operations-v1.json` list the route.
- Follow-up: PR 12 saves models, storing the prices this answer shows.

### 2026-11-23 — AF-447 — slice 3, PR 10

- Delivered: `GET /api/v1/platform/settings/llm-providers/{slug}/models` lists a connection's stored models by `model_id`, for Platform Administrators only; a read-only Personal API Key may read them. Each price is the stored `NUMERIC(24,18)` value as a fixed-point string with 18 places, so `0` is `"0.000000000000000000"`, not Pydantic's `"0E-18"`. An unknown or deleted slug is `404`; OpenRouter is `409` "OpenRouter's models are not stored.". [`llm-providers.md`](../llm-providers.md), the [RBAC brief](../rbac/IMPLEMENTATION-BRIEF.md) and `api/developer_docs/operations-v1.json` list the route.
- Verification: `test_platform_llm_provider_connections.py` covers an Organization owner (`403`), no sign-in (`401`), a read-only key, the exact body with another connection's model left out, a connection without models, a missing or deleted slug, and OpenRouter.
- Follow-up: PR 11 adds the provider's list with prices.

### 2026-11-23 — AF-447 — slice 2, Anthropic key check fix

- Fixed: `LlmProviderKeyChecker` now sends `anthropic-version: 2026-10-21` with an Anthropic key check, the version the catalogue sends (`ANTHROPIC_VERSION` in `api/infrastructure/llm_provider_catalogue/catalogue.py`). Anthropic's docs require the header on every request (https://platform.claude.com/docs/en/api/versioning). Found while checking those docs for PR 9; slice 2's live check sent only an obviously fake key, which Anthropic refused with `401`, so a valid key was never tried without the header. [`llm-providers.md`](../llm-providers.md) shows the header.

### 2026-11-23 — AF-447 — slice 3, PR 9

- Delivered: `LlmProviderCatalogue.list_models()` reads the paged lists:
  - Anthropic: `GET https://api.anthropic.com/v1/models?limit=1000` with `x-api-key` and `anthropic-version: 2026-10-21`; while `has_more` is true, the next page passes `after_id` set to `last_id`; every entry's `id` (https://platform.claude.com/docs/en/api/models/list, `limit` 1 to 1000);
  - Gemini: `GET https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000` with `x-goog-api-key`; `nextPageToken` becomes `pageToken`; only entries whose `supportedGenerationMethods` has `generateContent`, by `name` without `models/` (https://aistudio.google.com/api-reference/models/list-models, at most 1000 per page; https://aistudio.google.com/api-reference for the header);
  - Fireworks: `GET https://api.fireworks.ai/v1/accounts/fireworks/models?filter=supports_serverless=true&pageSize=200` with a Bearer key; `nextPageToken` becomes `pageToken`; only entries with a `conversationConfig`, which "If set, the Chat Completions API will be enabled for this model", by their full `name` (https://docs.fireworks.ai/api-reference/list-models, at most 200 per page; the filter is from https://docs.fireworks.ai/faq-new/models-inference/how-to-check-if-a-model-is-available-on-serverless).
- Delivered: a listing resolves and pins the host once for all its pages. It reads at most 5 pages, the 2 MiB cap applies to each page, and the 1,000-entry cap to the whole listing, counted before filtering. A sixth page, a `has_more` without a `last_id`, a page token that is not a string, or a page without its list is unreadable. `401` and `403` refuse the key, and Gemini's `400` too, as in the key checker; Anthropic's documented `400`s for an organization on hold or a removed key creator are unreachable, as there.
- Changed: Anthropic's docs now require `anthropic-version` on every request (https://platform.claude.com/docs/en/api/versioning), which slice 2's key checker does not send, and name `Authorization: Bearer` the primary auth with `x-api-key` a "legacy fallback, still supported" (https://platform.claude.com/docs/en/api/overview). The catalogue sends `x-api-key`, as the key checker does.
- Follow-up: PR 10 adds the stored models API; PR 11 calls the catalogue.

### 2026-11-23 — AF-447 — slice 3, PR 8

- Delivered: `LlmProviderCatalogue.list_models()` in the new `api/infrastructure/llm_provider_catalogue/` reads a provider's model list with the connection's key, each with a Bearer key and the ids under each entry's `id`:
  - OpenAI: `GET https://api.openai.com/v1/models`, list in `data` (https://developers.openai.com/api/reference/resources/models/methods/list);
  - xAI: `GET https://api.x.ai/v1/language-models`, list in `models`, "all chat and image understanding models" (https://docs.x.ai/developers/rest-api-reference/inference/models);
  - DeepSeek: `GET https://api.deepseek.com/models`, list in `data` (https://api-docs.deepseek.com/api/list-models);
  - Novita: `GET https://api.novita.ai/openai/v1/models`, list in `data` (https://docs.novita.ai/api-reference/model-apis-llm-list-models);
  - Custom: `GET {base_url}/models`, list in `data`, as slice 2's key check asks.
  None of those pages mentions paging.
- Delivered: the host is resolved in a worker pool and given 5 seconds, then the request is pinned to the checked public address (`public_http`), with no redirects and a 10-second timeout. The body is read up to 2 MiB once decoded, so a small compressed body can't decode into more, and the list up to 1,000 entries; both caps are ours. Ids a model row can't hold (more than 200 characters, or outside `[A-Za-z0-9._:/-]`) and entries without a string id are left out; the rest come back sorted, each once.
- Delivered: `401` and `403`, and xAI's `400`, raise `ProviderListRefused`; no answer, a non-public address, a redirect or another status `ProviderListUnreachable`; a body that is not a model list or is over a cap `ProviderListUnreadable`. Each message is fixed and none carries the key.
- Changed: checked on 2026-11-23 by sending an obviously fake key to `https://api.x.ai/v1/language-models`: it answered `400` `invalid-argument` ("Incorrect API key provided"), as `/v1/models` did in slice 2, and `401` with no key. xAI's docs say `401` (https://docs.x.ai/developers/debugging).
- Changed: Novita's list endpoint is now in its API reference, so the plan's known limit for it no longer holds; PR 17's feature doc leaves it out.
- Follow-up: PR 9 adds the paged lists; PR 11 uses the catalogue and describes it in [`llm-providers.md`](../llm-providers.md).

### 2026-11-20 — AF-447 — slice 3, PR 7

- Delivered: the Platform-scoped `platform.llm_provider.models_changed` event, version 1, projected by `security_audit.projection`. Its payload is the connection id, slug and provider type, the number of models added, removed and repriced, up to 20 ids of each, `model_ids_truncated`, and display names; it refuses any other field, so it can't carry a key or a price. [`domain-events.md`](../domain-events.md) describes it.
- Changed: the plan's 50 ids per list could not fit the 16 KB payload cap (`api/domains/events/registry.py:136-138`): at 200 characters an id costs 203 bytes of compact JSON, so three lists of 50 reach 30,450 bytes. At 20 per list, three full lists of 200-character ids with a 32-character slug and a 64-character name come to 12,559 bytes before the actor's name, which has no length limit, leaving it 3,825 bytes.
- Verification: `test_domain_events.py` covers the fields, a missing or extra field, a list over 20 ids, an id over 200 characters and a payload at every limit; `test_event_handler_registry_wiring.py` checks the event reaches only the security audit.
- Follow-up: PR 12 records the event when models are saved; it must cut each list to 20 ids and set `model_ids_truncated` when it does.

### 2026-11-20 — AF-447 — slice 3, PR 6

- Delivered: `LlmProviderRepository.replace_key` calls its callback under the connection's lock with the connection, already carrying the new base URL, and its models; `delete` calls its callback with the connection before it deletes the models, soft-deletes the connection and purges the key in one transaction. If the callback raises, nothing is stored or deleted.
- Delivered: replacing the key of any connection but OpenRouter lists LiteLLM's routes under the connection's prefix once, writes the route of each of its models with the new key and base URL, then removes the listed routes with no model. Deleting a connection removes every route under its prefix. A LiteLLM failure is `503`: "Your key was not changed." for a key, "Nothing was deleted." for a delete. A failure part-way leaves some routes on the new key while the old one is stored; saving the key again leaves one route per model. OpenRouter's key still goes to its one route. [`llm-providers.md`](../llm-providers.md) states the invariants.
- Changed: every route the connection should have is written on each key replacement, whether or not it changed.
- Verification: `test_platform_llm_provider_connections.py` seeds models and routes and covers a new key, a new Azure base URL, a failure part-way and its retry, a delete, a delete that LiteLLM fails, and a key replacement racing a delete; the OpenRouter route and another connection's route stay untouched.
- Follow-up: PR 12 writes only the routes that differ, comparing prices as floats (see PR 4), and adds the tests for a model save racing a delete or a key replacement.

### 2026-11-20 — AF-447 — slice 3, PR 5

- Delivered: `build_model_deployment` in `api/domains/llm_providers/litellm_deployments.py` turns a connection, one of its models and the connection's key into the LiteLLM route body: `model_name` `<slug>/<model_id>`, the provider's model string, the key, all four prices as floats, and `model_info` with the route id `agentbarn:model:<connection id>:<model row id>` and the background health check off, as the OpenRouter route has. OpenRouter and a model of another connection are refused. `model_route_prefix` gives the prefix `list_model_deployments` takes. [`llm-providers.md`](../llm-providers.md) lists each provider's route.
- Changed: DeepSeek routes send `api_base` `https://api.deepseek.com`, to which LiteLLM appends `/chat/completions`, in place of its default `https://api.deepseek.com/beta` (`llms/deepseek/chat/transformation.py:358-381` at v1.108.6). Novita routes send `https://api.novita.ai/openai` in place of LiteLLM's `https://api.novita.ai/v3/openai` (`litellm_core_utils/get_llm_provider_logic.py:854-856`). Azure routes send the stored resource endpoint with `api_version` `v1`, for which LiteLLM calls `{api_base}/openai/v1/` (`llms/azure/common_utils.py:552-580`); slice 2 checks Azure keys at `{base_url}/openai/v1/models`, so the stored base URL is that endpoint.

### 2026-11-20 — AF-447 — slice 3, PR 4

- Delivered: `LiteLLMClient.list_model_deployments(id_prefix)` asks LiteLLM's `GET /model/info` once with the master key and returns the routes whose `model_info.id` starts with the prefix. At v1.108.6 that call lists every route, database routes included, for a key with no model, team or agent limits (`proxy/proxy_server.py:16842-16861,17093-17096`), and strips `api_key` from each route's `litellm_params` (`proxy/common_utils/openai_endpoint_utils.py:32`). A failed request or a body without a `data` list raises `LiteLLMError` without the key, and nothing is logged.
- Follow-up: LiteLLM holds route prices as floats (`types/utils.py:3934-3939`), so `/model/info` returns the prices sent as floats, not the stored decimals. PR 6's reconcile compares them in the same form, or every route would look changed.

### 2026-11-20 — AF-447 — slice 3, PR 3

- Delivered: `LiteLLMClient.get_model_prices()` reads LiteLLM's built-in price list from `GET /public/litellm_model_cost_map?catalog_only=true`, which needs no key and leaves out entries LiteLLM registers for its routes (`proxy/public_endpoints/public_endpoints.py:498-512`, `proxy/_types.py:739` at v1.108.6). Each entry gives its key, `mode` and four per-token prices as exact decimals; an entry whose input or output price is missing, zero or not a number is left out, and a missing or negative cache price is unset. A failed request or a body that is not an object raises `LiteLLMError`.
- Delivered: `litellm_price_key()` gives the key a model is priced under: the bare id for OpenAI and Anthropic; `gemini/`, `xai/`, `deepseek/`, `fireworks_ai/`, `novita/` or `azure/` and the id for the rest, an Azure deployment using the model it runs; none for OpenRouter and Custom.
- Changed: checked against v1.108.6's bundled list, 3,090 entries give a price, 2,791 of them chat models. 13 chat entries of our providers are priced 0 and 6 have no price, so they get none here.
- Follow-up: 43 entries, 20 of them for our providers and mostly Novita, have prices with more than 18 decimal places, such as `0.000015000020000000002`, which `NUMERIC(24,18)` rounds. PR 11's service rounds list prices to 18 decimal places before it shows, stores or compares them; the client keeps LiteLLM's values as they are.

### 2026-11-18 — AF-447 — slice 3, PR 2

- Delivered: migration `bc817a73bb6d` adds `llm_provider_model` and `LlmProviderModel`: a connection's model once per connection, with four per-token `NUMERIC(24,18)` prices named as LiteLLM's route fields (`litellm/types/utils.py:3934-3939` at v1.108.6), a `price_source` of `litellm` or `manual`, and the `litellm_price_key` a `litellm` price was read under. The database refuses an input or output price of zero or less, a negative cache price, a malformed `model_id` and a model of no connection. [`llm-providers.md`](../llm-providers.md) has a Models section; `CONTEXT.md` defines LLM Provider Model.
- Changed: `database_is_clean` empties `llm_provider_model` before it resets the connections.
- Removed: `test_llm_provider_connection_migration.py`, the migration tests for slices 1 and 2.
- Release impact: the migration creates an empty table; its downgrade drops it with every model in it.
- Follow-up: PR 3 reads LiteLLM's price list.

### 2026-11-18 — AF-447 — slice 3, PR 1

- Changed: the LiteLLM chart and Compose set `LITELLM_LOCAL_MODEL_COST_MAP=true`. In v1.108.6 the image starts `litellm`, which otherwise downloads the price list from BerriAI's `main` branch at every start (`litellm/__init__.py:430-433,572`); with it, startup and scheduled or admin reloads use the list bundled in the image (`litellm_core_utils/get_model_cost_map.py:392,676`). LiteLLM chart 0.5.2.
- Changed: the LiteLLM egress NetworkPolicy was dropped from slice 3. Staging's tenant release `tenant-agent-farm-staging` installs `allow-all-egress` (`podSelector: {}`, `egress: [{}]`), and NetworkPolicies only add permissions, so a LiteLLM policy would restrict nothing. Public was not checked.
- Verification: `helm template` renders the env var on the LiteLLM container; `docker compose config` shows it on the `litellm` service.
- Follow-up: PR 2 adds the provider model schema.

### 2026-11-17 — AF-447 — slice 2, review fixes

- Fixed: a Novita key was accepted without being checked. Novita's `GET /openai/v1/models` answers `200` without authenticating, so any key passed. The checker now asks `GET https://api.novita.ai/v3/user`, which refuses a wrong key with `403` `INVALID_API_KEY`, the bad-key answer PR 2 recorded for Novita.
- Fixed: a wrong xAI key was reported as "could not be reached" (`503`) instead of "did not accept this key" (`422`). xAI's `GET /v1/models` refuses it with `400` `invalid-argument` ("Incorrect API key provided"), not the `401` in its docs, so xAI's `400` now refuses a key as Gemini's does. Nothing was stored either way.
- Changed: checked on 2026-11-17 by sending an obviously fake key to every check endpoint, never committed as a test. Novita `/v3/user` answered `403`; Anthropic, OpenAI, DeepSeek and Fireworks `401`; Gemini and xAI `400`; Novita's model list `200`. A real Novita or xAI key answering `200` is not checked yet. `test_llm_provider_key_checker.py` asks Novita at `/v3/user` and refuses xAI's `400`. [`llm-providers.md`](../llm-providers.md) says so, and that a Custom server whose `/models` does not check the key accepts any key.
- Changed: the PR 12 release-impact line said an API client calling `.../openrouter` gets `405`; it now says those routes never reached a release.

### 2026-11-17 — AF-447 — slice 2, provider list follow-up

- Changed: Platform Admin settings → LLM providers shows every connection, OpenRouter first, in one list with a card each, replacing the OpenRouter card and the **Other providers** card. "Add provider" sits above the cards, as "Add size" does in Agent sizes. An added provider, a saved key and a deleted connection are confirmed by a toast instead of a line inside a card. `provider-card.tsx` replaces `llm-provider-connection-list.tsx`, and `platform-llm-provider-settings.tsx` holds the add, key and delete dialogs. `platform-llm-providers.spec.ts` and its page object find cards in the provider list and check the toasts. [`llm-providers.md`](../llm-providers.md) describes the list.

### 2026-11-17 — AF-447 — slice 2, PR 13

- Delivered: slice 2 is complete. [`llm-providers.md`](../llm-providers.md) has a section on how each provider's key is checked, and its read-when, role and invariants cover every connection rather than OpenRouter alone.
- Changed: `docs/INDEX.md` routes `api/infrastructure/llm_provider_keys/` and key checking to the feature doc. `CONTEXT.md` is unchanged: its LLM Provider Connection definition already fits a connection to any provider.
- Follow-up: the demo of slices 1 and 2 on local k3d, then slice 3.

### 2026-11-17 — AF-447 — slice 2, PR 12

- Removed: `GET` and `PUT /api/v1/platform/settings/llm-providers/openrouter`, with `OpenRouterConnectionRead`, `OpenRouterKeyUpdate` and the service's `read_openrouter` and `replace_openrouter_key`. OpenRouter's key status is its entry in `GET /platform/settings/llm-providers`, and its key is replaced through `PUT .../openrouter/key`, which checks it with OpenRouter and writes the LiteLLM route first as before. Both old paths now answer `405`, because `DELETE .../{slug}` matches them, and reach nothing.
- Changed: `test_platform_llm_providers.py` reads OpenRouter's entry from the list and saves through `PUT .../openrouter/key`, and checks that the old paths change nothing. `test_openrouter_route_litellm_contract.py` saves through `PUT .../openrouter/key` and passes against LiteLLM. `operations-v1.json`, the RBAC brief and [`llm-providers.md`](../llm-providers.md) drop the two routes.
- Release impact: none for a released client. The two routes were added on 2026-11-16 and reached only `staging`, never `main` or a `vX.Y.Z` tag, and public deploys only from a tag. A call to them now gets `405`; the UI stopped calling them in PR 11. This holds only while this change reaches `staging` before the next release tag is cut from it.
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
