# LLM providers in Platform Admin settings — change log

Status: Active
Epic: AF-447
Related context: [`../costs.md`](../costs.md), [`../agent-settings.md`](../agent-settings.md), [`../../guidelines/operations.md`](../../guidelines/operations.md)

## Current state

- Delivered: the API can add, update and delete LiteLLM model routes by a fixed route id. LiteLLM persists database routes with their provider keys encrypted under `LITELLM_SALT_KEY`; its config-file OpenRouter route is at `order: 2`, so a healthy route with a lower order is used instead.
- In transition: the OpenRouter key still comes only from `OPENROUTER_API_KEY`; nothing registers a database route yet.
- Next: slice 1, PR 5 — the OpenRouter key status for Platform Administrators.
- Blockers: `LITELLM_SALT_KEY`, `STAGING_LITELLM_SALT_KEY` and `PUBLIC_LITELLM_SALT_KEY` GitHub secrets must exist before the next deploy.

## Changes

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
