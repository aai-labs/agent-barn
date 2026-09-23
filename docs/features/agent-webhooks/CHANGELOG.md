# Agent Webhooks decoupling delivery state

Related context: [`../agent-webhooks.md`](../agent-webhooks.md), [`../../architecture/runtime-and-deployment.md`](../../architecture/runtime-and-deployment.md), [`../../guidelines/epics.md`](../../guidelines/epics.md)

## Current state

- Delivered: independent Agent Webhook configuration and signed ingress, idempotent Webhook Invocations, direct native Agent Trigger Job submission for Hermes/OpenClaw, bounded submission retries, explicit failed-submission retry, and the webhook-specific UI.
- Removed: the unreleased Communications-backed webhook Platform, event-specific Communication Delivery behavior, and their tests and UI filtering. See the [Communications change log](../communications/CHANGELOG.md).
- Preserved: released Communications behavior is unchanged, and the runtime protocol is back to its released version 2 while still accepting the staging-only version 3.
- Next: nothing outstanding; per-webhook channel selection stays deferred.
- Blockers: none.

## Slice history

### 2026-09-22 — Independent Agent Webhooks foundation

- Delivered Agent Webhook CRUD, one-time secret reveal and rotation, signed `/agent-hooks/v1/{webhook_id}` ingress, caller idempotency, invocation history, tenant constraints, and focused integration coverage.
- Added migration `7a9c2e4f6b81`.

### 2026-09-22 — Native trigger submission and UI cutover

- Replaced the rejected claim/lease/polling design with immediate product-to-Agent dispatch.
- Added the `RECEIVED`, `SUBMITTED`, and `DISPATCH_FAILED` submission model. Agent Barn stores neither Agent output nor native execution/delivery state.
- Added an authenticated private listener to both runtime images. It deduplicates each dispatch generation, creates a native one-shot Hermes/OpenClaw job, and acknowledges only after scheduler acceptance.
- Added selection of an enabled native Slack, Discord, Telegram, or Teams Connection. Final output goes through that runtime's configured default channel; per-webhook channel selection remains deferred.
- Added webhook-specific UI schemas, hooks, CRUD, one-time secret reveal, invocation history, and retry for `DISPATCH_FAILED` only. The UI no longer imports Communication Connection webhook/call contracts.
- Collapsed the unreleased webhook migrations into `7a9c2e4f6b81`; no released migration was rewritten.
- Made `event_id` optional: only `prompt` is required, and caller idempotency applies only when `event_id` is supplied.
- The listener now schedules the native one-shot a few seconds ahead instead of creating it a year out and force-running it. A forced OpenClaw run keeps the future schedule, which would have fired the job again later. Runtime 4xx rejections no longer consume transport retries.
- Added Playwright coverage for the one-time secret reveal, prompt-only example, and failed-submission retry; associated the reveal and detail labels with their inputs.
- Added `make forward-triggers` and local `AGENT_TRIGGER_URL` overrides so host and Compose APIs reach the k3d Agent listener on port 8082.
- Capped `prompt` at 5,000 characters at ingress (the Hermes job prompt limit) and stated the cap in the UI payload hint.
- Delivery platforms now require a default channel (Slack `default_delivery_target`, otherwise `home_channel_id`). This is checked when listing platforms, on create and update, and before each dispatch (`DELIVERY_CHANNEL_UNAVAILABLE`).
- Made listener submission at-most-once. A pending receipt is committed before the create call. On a retry where no job by that name exists, the listener returns `409` instead of recreating a job that may already have run. The listener's rejection reason is recorded on the invocation.
- Retired the webhook Communication Platform in migration `b6d4f0a91c37`, deleting its Connections and their deliveries, journal entries, and transcript rows.

### 2026-09-22 — Review hardening

- Ingress now runs dispatch in the threadpool instead of blocking the API event loop for up to the full dispatch retry budget.
- The signature now covers `X-AgentBarn-Timestamp`, and requests outside a 300-second window are rejected to bound replay. Contract version stays `1` because it has not been released.
- `RECEIVED` invocations that have not changed for two minutes can be retried, so an API crash mid-dispatch no longer strands them. Retry requires the webhook to be enabled.
- The listener drops its pending receipt when a create provably made no job, so the API's in-dispatch retries can succeed instead of ending in "outcome unknown".
- The UI gates create, rotate, and remove on `agent.secret.manage`, and reports mutation failures instead of leaving unhandled rejections.
