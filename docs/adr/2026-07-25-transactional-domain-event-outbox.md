# Use a transactional Domain Event outbox

Status: Accepted
Date: 2026-07-25
Origin: AF-218, AF-219

Agent Farm will persist internal Domain Events through a PostgreSQL transactional outbox: a domain-specific repository operation that produces an event writes the business state, one Outbox Message, and one Event Delivery per currently registered Event Handler using one SQLModel session and one commit. This keeps business mutations and event intent atomic, leaves PostgreSQL as the durable source of publication and handler-delivery state, and keeps domain code transport-neutral before Dramatiq/Redis delivery is introduced.

## Considered alternatives

- Treat the Outbox Message as the Domain Event itself. This simplified persistence terminology but collapsed the domain contract into a storage concern.
- Let the outbox open or commit its own session. This made event staging easy to call but allowed events to commit independently from the business mutation that produced them.
- Create Event Delivery rows later in a worker. This reduced synchronous write work but made intended handler delivery state non-atomic with the event-producing mutation.

## Consequences

- A Domain Event is the immutable typed business fact; an Outbox Message is its immutable durable PostgreSQL publication-intent record; an Event Delivery is durable mutable delivery state for one event and one named Event Handler, not a retry-attempt log.
- Event names and schema versions are owned by a typed registry that validates bounded, secret-safe JSON payloads and resolves intended handlers; payload validation combines per-event schemas with recursive sensitive-key and unsupported-value rejection.
- AF-219 defines the persistence foundation for at-least-once delivery to each intended Event Handler; Event Deliveries have an explicit durable lifecycle from creation (`PENDING`, `IN_PROGRESS`, `SUCCEEDED`, `FAILED`, `DEAD_LETTER`), while later worker slices provide actual Dramatiq execution, retries, and exhausted-delivery handling.
- Event envelopes carry event ID, event name, schema version, occurred-at time, Organization ID, typed Actor Identity, typed Subject Identity, required correlation ID, and optional causation ID.
- Organization ID is authoritative. Known actor, subject, and validated payload references that belong to a different Organization must be rejected, rolling back the associated business mutation.
- Security Audit Records are projections from selected Domain Events, not the Domain Events themselves.
- This decision does not introduce event sourcing, public webhooks, broker-specific domain types, replay administration, or strict global ordering.
