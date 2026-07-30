# Deliver Domain Events through Dramatiq delivery workers

Status: Accepted
Date: 2026-07-26
Origin: AF-220, maintainer grilling session

Agent Farm will deliver committed Event Deliveries through Dramatiq messages backed by company Redis, while PostgreSQL remains authoritative for Outbox Messages and Event Delivery state. Dramatiq messages carry only the Event Delivery ID plus diagnostic metadata; workers reload state from PostgreSQL, claim deliveries atomically, execute statically registered handlers, and persist success or dead-letter state. This keeps domain event persistence transport-neutral and durable while using Dramatiq only for queue transport, concurrency, bounded exponential retry, and retry-exhaustion callbacks.

## Considered alternatives

- Put event payloads or handler routing data in queue messages. This would reduce PostgreSQL reads but make Redis/Dramatiq authoritative for business data and increase secret/tenant leakage risk.
- Let PostgreSQL schedule retries independently. This would centralize retry state but duplicate Dramatiq's retry scheduler and violate the AF-220 requirement to avoid a competing retry system.
- Treat retryable failures as a durable `FAILED` lifecycle state. This made operational language ambiguous, so terminal failures use `DEAD_LETTERED` and transient failures remain `PROCESSING` with bounded error metadata.
- Run reconciliation inside the Product or Ingest API. This would couple API health and latency to queue repair, so reconciliation is worker-owned and scheduled by infrastructure.

## Consequences

- Event Delivery lifecycle is `PENDING`, `ENQUEUED`, `PROCESSING`, `SUCCEEDED`, or `DEAD_LETTERED`; dead-letter reason is separate from lifecycle state.
- Immediate enqueue is post-commit best effort. Redis/Dramatiq failure leaves committed deliveries `PENDING` and visible for reconciliation rather than failing the originating business operation.
- Delivery is at-least-once. Handlers must be idempotent because a worker can crash after handler side effects commit and before the delivery is marked `SUCCEEDED`.
- Handler names are stable operational contracts once Event Deliveries can reference them; removing or renaming a handler requires compatibility or migration.
- Reconciliation republishes eligible Event Deliveries, not whole Outbox Messages, and never automatically republishes `SUCCEEDED` or `DEAD_LETTERED` deliveries.
