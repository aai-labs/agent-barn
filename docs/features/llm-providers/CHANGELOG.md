# LLM providers in Platform Admin settings — change log

Status: Active
Epic: AF-447
Related context: [`../costs.md`](../costs.md), [`../agent-settings.md`](../agent-settings.md), [`../../guidelines/operations.md`](../../guidelines/operations.md)

## Current state

- Delivered: the API can add, update and delete LiteLLM model routes by a fixed route id.
- In transition: the OpenRouter key still comes only from `OPENROUTER_API_KEY`; nothing registers a database route yet.
- Next: slice 1, PR 2 — LiteLLM's model store and `LITELLM_SALT_KEY`.
- Blockers: none.

## Changes

### 2026-11-16 — AF-447 — slice 1, PR 1

- Delivered: `LiteLLMClient.upsert_model_deployment` creates a route LiteLLM does not have (`/model/new`) and updates one it has (`/model/update`), looked up by `model_info.id`; `delete_model_deployment` removes a route and reports one that is already gone.
- Changed: failures raise `LiteLLMError` with a fixed message and no exception chain, so the provider key in the request body never reaches a log or traceback.
- Follow-up: PR 2 turns on LiteLLM's model store so these routes persist.
