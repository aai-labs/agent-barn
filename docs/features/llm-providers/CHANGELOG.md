# LLM providers in Platform Admin settings — change log

Status: Active
Epic: AF-447
Related context: [`../costs.md`](../costs.md), [`../agent-settings.md`](../agent-settings.md), [`../../guidelines/operations.md`](../../guidelines/operations.md)

## Current state

- Delivered: the API can add, update and delete LiteLLM model routes by a fixed route id. LiteLLM persists database routes with their provider keys encrypted under `LITELLM_SALT_KEY`; its config-file OpenRouter route is at `order: 2`, so a healthy route with a lower order is used instead.
- In transition: the OpenRouter key still comes only from `OPENROUTER_API_KEY`; nothing registers a database route yet.
- Next: slice 1, PR 3 — the OpenRouter client takes the key per call.
- Blockers: `LITELLM_SALT_KEY`, `STAGING_LITELLM_SALT_KEY` and `PUBLIC_LITELLM_SALT_KEY` GitHub secrets must exist before the next deploy.

## Changes

### 2026-11-16 — AF-447 — slice 1, PR 2

- Delivered: LiteLLM's model store is on (`store_model_in_db: true`). The config-file `openrouter/*` route is at `order: 2` and is rendered only while `OPENROUTER_API_KEY` is set.
- Changed: new required `LITELLM_SALT_KEY`, kept in its own `litellm-salt` Secret that the API does not read; wired through Helmfile, both deploy workflows, Compose, `run.sh` and `k3d-up.sh`. LiteLLM chart 0.5.0.
- Follow-up: PR 3 passes the OpenRouter key to the client per call.

### 2026-11-16 — AF-447 — slice 1, PR 1

- Delivered: `LiteLLMClient.upsert_model_deployment` creates a route LiteLLM does not have (`/model/new`) and updates one it has (`/model/update`), looked up by `model_info.id`; `delete_model_deployment` removes a route and reports one that is already gone.
- Changed: failures raise `LiteLLMError` with a fixed message and no exception chain, so the provider key in the request body never reaches a log or traceback.
- Follow-up: PR 2 turns on LiteLLM's model store so these routes persist.
