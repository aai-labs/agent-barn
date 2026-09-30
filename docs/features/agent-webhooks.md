# Agent Webhooks

## Read when

Read before changing Agent Webhook configuration, signed machine ingress, Webhook Invocation persistence, native trigger submission, or webhook UI.

## Role in the system

An Agent Webhook lets an external system trigger one Agent over authenticated HTTP. Agent Barn owns admission, idempotency, and submission history; Hermes or OpenClaw owns the resulting one-shot Agent Trigger Job, execution history, and delivery through the selected runtime-owned Communication Connection.

## Invariants

- Every Agent Webhook belongs to one Agent and carries the same Organization identity.
- Reads require Agent visibility. Editing, enabling, disabling, and retrying require Agent update; creating, rotating the secret, and retiring also require secret-management authority because they issue or destroy a signing secret. Invocation content requires activity-read authority.
- The signing secret is encrypted at rest and returned only when created or rotated.
- Public ingress verifies HMAC-SHA256 over `{X-AgentBarn-Timestamp}.{raw request body}` (Unix seconds, then a dot, then the exact bytes) before validating the versioned payload, and rejects a timestamp more than 300 seconds from the server clock. The window bounds replay of a captured request; `event_id` is still the way to make intentional caller retries safe.
- The payload requires only `prompt`, capped at 5,000 characters at ingress to match the Hermes job prompt limit; longer prompts are rejected with 400 before an invocation is stored. When the caller supplies the optional `event_id`, `(webhook_id, external_event_id)` identifies one Webhook Invocation and caller retries return it without resubmitting. Without `event_id`, every accepted request creates a new invocation.
- An Agent Webhook selects one enabled runtime-owned Slack, Discord, Telegram, or Teams Connection that has a default channel (Slack `default_delivery_target`; otherwise `home_channel_id`). Eligibility is checked when listing platforms, on create and update, and again before each dispatch; an invocation whose Connection lost its default channel fails with `DELIVERY_CHANNEL_UNAVAILABLE`. The runtime delivers to that default channel; selecting an individual channel is deferred.
- A Webhook Invocation records only trigger submission: `RECEIVED`, `SUBMITTED`, or `DISPATCH_FAILED`. It stores no Agent output and receives no execution callback.
- The product API makes at most three bounded transport attempts per dispatch generation. Every attempt uses the same idempotency key.
- A UI retry is allowed from `DISPATCH_FAILED`, or from `RECEIVED` once it has not changed for two minutes (longer than a whole dispatch, so the API process that owned it is gone). The webhook must be enabled. A retry increments the dispatch generation and resubmits the same invocation; a result from a superseded generation is discarded.
- `202 Accepted` from the private Agent listener means the native scheduler durably accepted the one-shot job. It does not mean execution or provider delivery succeeded.
- Retiring a webhook closes public ingress and destroys its signing secret. It does not cancel Agent Trigger Jobs already accepted by a runtime.
- Webhook triggers never create Communication Deliveries and never pass through the Communications Gateway or Platform Plugin registry.

## State model

```text
RECEIVED ── native scheduler accepts ──> SUBMITTED
    │
    ├── submission cannot be accepted ─> DISPATCH_FAILED
    │                                      │
    │                                      └── explicit retry ─> RECEIVED
    │
    └── stalled for two minutes (API process died mid-dispatch) ── explicit retry ─> RECEIVED
```

`SUBMITTED` is terminal in Agent Barn. Hermes/OpenClaw runtime history is authoritative after that boundary.

## Primary flow

1. An authorized user creates an Agent Webhook, selects an eligible native platform, and copies the one-time signing secret.
2. An external system posts a versioned JSON body to the public URL with the current Unix time in `X-AgentBarn-Timestamp`, and signs the timestamp and raw bytes.
3. Agent Barn authenticates the request and atomically creates the invocation, or finds the existing one when the caller supplied a repeated `event_id`.
4. For a new invocation, Agent Barn immediately calls the Agent's authenticated private trigger listener, retrying transient submission failures at most three times.
5. The listener deduplicates by `invocation_id:dispatch_generation` and creates, or finds, a deterministically named native one-shot job scheduled a few seconds ahead. The native scheduler fires it; the listener never force-runs a job, so a found job is never triggered twice. Submission is at most once: a pending receipt is committed before the create call, and a retry that finds it pending with no job by that name returns a non-retryable `409` ("outcome unknown") rather than recreating a job that may already have run and deleted itself. When the failure proves nothing was created (the runtime refused the connection, the OpenClaw CLI is missing, or the runtime returned 4xx), the listener drops the pending receipt so the same key can submit again. Runtime 4xx rejections are returned as non-retryable, and the listener's reason is recorded as the invocation error.
6. Agent Barn records `SUBMITTED` plus the native job identifier, or `DISPATCH_FAILED` plus a safe submission error. It does not poll or receive a completion callback.
7. Hermes/OpenClaw executes the job in an isolated session and natively posts the final result to the selected platform's configured default channel.

## Source map

| Concern | Authoritative source |
|---|---|
| Persistence and DTOs | `../../api/domains/agent_webhooks/models.py` |
| Tenant-aware persistence and idempotency | `../../api/domains/agent_webhooks/repository.py` |
| Authorization, signing, and orchestration | `../../api/domains/agent_webhooks/service.py` |
| Bounded product-to-Agent dispatch | `../../api/domains/agent_webhooks/dispatch.py` |
| Product and public HTTP contracts | `../../api/domains/agent_webhooks/routes.py` |
| Native Hermes/OpenClaw job admission | `../../api/domains/agents/scripts/agent-trigger-server.py` |
| Runtime packaging and private Service (local: `make forward-triggers AGENT=<id>`) | `../../api/domains/agents/builders/`, `../../api/domains/agents/scripts/hermes/start.sh`, `../../api/domains/agents/scripts/openclaw/start.sh` |
| UI schemas, hooks, and components | `../../ui/src/features/agent-webhooks/` |
| Schema migration | `../../api/migrations/versions/7a9c2e4f6b81_add_agent_webhooks_and_invocations.py` |
| Backend coverage | `../../api/tests/integration/test_agent_webhooks.py`, `../../api/tests/unit/test_agent_trigger_server.py` |
| UI coverage | `../../ui/tests/e2e/agent-webhooks.spec.ts`, `../../ui/tests/pages/agent-webhooks-page.po.ts`, `../../ui/tests/pages/data-support/agent-webhook-data-support.po.ts` |

## Change impact

Changing admission, invocation identity, status, or retry behavior requires API contract and migrated-PostgreSQL coverage. Changing native job submission affects the private listener, both runtime builders and startup scripts, the Agent Service port, and runtime contract tests. Changing eligible delivery platforms affects Connection validation and the webhook-specific UI selector, but must not introduce a Communication Delivery or provider sender into this flow.
