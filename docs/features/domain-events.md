# Domain Events

## Read when

Read before adding or changing internal Domain Events, Outbox Messages, Event Deliveries, Event Handlers, event payload schemas, audit projections, or repository operations that stage events.

## Role in the system

Agent Farm uses internal Domain Events to record immutable, typed business facts that occurred inside one Organization. A committed Domain Event is persisted as one PostgreSQL `event_outbox_message` row and one `event_delivery` row per currently registered Event Handler. PostgreSQL is the durable source for event intent and intended handler delivery state; worker transport is intentionally outside this foundation.

## Invariants

- Domain Events are internal business facts, not runtime Telemetry Events, public webhooks, audit records, queue messages, or event-sourced entity history.
- Event names and schema versions are registered in code through a typed registry. Unsupported names or versions fail before persistence.
- Event envelopes include event ID, event name, schema version, occurred-at time, Organization ID, typed Actor Identity, typed Subject Identity, required correlation ID, optional causation ID, and bounded Event Payload.
- Event Payloads are JSON objects validated by their event schema and by recursive safety checks. Secrets, credentials, unsupported values, oversized content, and sensitive key names are rejected.
- Organization ID is authoritative. Known actor, subject, and validated payload references that belong to a different Organization are rejected before commit.
- A domain-specific repository operation that produces an event owns the transaction boundary. It writes business state, the Outbox Message, and intended Event Deliveries with one SQLModel session and one commit.
- The session-aware outbox staging interface stages rows in an existing repository-owned session. It does not commit, open another session, or belong in routes.
- `PostgresRepositoryDelegate` remains the default session-per-operation helper for ordinary persistence and does not accept optional event parameters.
- `event_outbox_message` rows are immutable after insert. They store transport-neutral event envelope data and do not contain Dramatiq, Redis, Kafka, RabbitMQ, webhook, or worker-specific fields.
- Event Delivery identity is `(event_id, handler_name)`. Retry attempts do not create additional intended deliveries.
- Event Deliveries are mutable operational state with lifecycle values `PENDING`, `IN_PROGRESS`, `SUCCEEDED`, `FAILED`, and `DEAD_LETTER`. AF-219 creates `PENDING` rows; later worker slices claim, retry, complete, and dead-letter them.
- The persistence foundation supports at-least-once delivery to each intended Event Handler. Exactly-once execution and strict global ordering are not promised.
- Security Audit Records are projections from selected Domain Events. Audit retention and redaction rules do not redefine the internal Domain Event contract.
- Runtime Ingest remains separate: Telemetry Events from Hermes/OpenClaw become Conversation Messages or Tool Calls and are not automatically written to the Domain Event outbox.

## Data flow

```text
Domain-specific repository operation
   ├── validate business mutation
   ├── build typed Domain Event through registry
   └── one SQLModel session / one commit
       ├── business state rows
       ├── event_outbox_message row
       └── event_delivery rows, one per registered Event Handler

Later worker slices
   └── read committed Event Deliveries from PostgreSQL → transport/handler execution
```

## Boundaries

The event domain owns envelope types, payload validation, event registry, outbox persistence, and delivery persistence. Business domains decide when their own mutations produce Domain Events and should expose domain-specific repository operations for those all-or-nothing writes. Routes must not manage sessions or stage events directly. Services may orchestrate business behavior, but SQL and transaction mechanics stay in repositories.

This foundation deliberately excludes event sourcing, public webhooks, replay administration, strict global ordering, broker-specific domain types, Dramatiq/Redis workers, retry execution, reconciliation jobs, and broad migration of existing workflows.

## Source map

| Concern | Authoritative source |
| --- | --- |
| Domain Event envelope, identities, Outbox Message, Event Delivery models | `../../api/domains/events/models.py` |
| Event registry and payload validation | `../../api/domains/events/registry.py` |
| Session-aware outbox staging and persistence reads | `../../api/domains/events/repository.py` |
| Schema migrations | `../../api/migrations/versions/b4c7e2a19d34_add_outbox_message.py`, `../../api/migrations/versions/c9d8e7f6a5b4_add_event_delivery.py` |
| Unit validation tests | `../../api/tests/unit/test_domain_events.py` |
| PostgreSQL persistence and transaction tests | `../../api/tests/integration/test_outbox_messages.py` |

## Related decisions

- [`2026-07-25-transactional-domain-event-outbox.md`](../adr/2026-07-25-transactional-domain-event-outbox.md)

## Change impact

Adding a Domain Event requires a registered event name/version, payload schema, intended handler mapping, payload safety tests, and repository/integration coverage for any event-producing mutation. Adding an event-producing business mutation requires a domain-specific repository transaction boundary that commits business state and staged event rows together. Changes to event envelope fields, delivery identity, lifecycle states, or privacy rules require model, migration, registry, tests, this document, and ADR review when the decision changes.
