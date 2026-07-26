# Domain Events

## Read when

Read before adding or changing internal Domain Events, Outbox Messages, Event Deliveries, Event Handlers, event payload schemas, audit projections, or repository operations that stage events.

## Role in the system

Agent Farm uses internal Domain Events to record immutable, typed business facts that occurred inside one Organization. A committed Domain Event is persisted as one PostgreSQL `event_outbox_message` row and one `event_delivery` row per currently registered Event Handler. PostgreSQL is the durable source for event intent and intended handler delivery state; Dramatiq/Redis is the low-latency, at-least-once transport for committed Event Deliveries.

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
- Event Deliveries are mutable operational state with lifecycle values `PENDING`, `ENQUEUED`, `PROCESSING`, `SUCCEEDED`, and `DEAD_LETTERED`.
  - `PENDING`: delivery exists in PostgreSQL and is not known to be queued.
  - `ENQUEUED`: a Dramatiq message was published or republished for the delivery.
  - `PROCESSING`: a worker has atomically claimed the delivery in PostgreSQL before handler execution.
  - `SUCCEEDED`: the handler completed; duplicate messages no-op.
  - `DEAD_LETTERED`: terminal delivery failure with no automatic retry remaining.
- `DEAD_LETTERED` is the only automatic terminal failure state. Its reason is stored separately from lifecycle state, and the reason is required whenever the status is `DEAD_LETTERED`.
- PostgreSQL `attempt_count` records observed handler execution attempts and remains historical metadata after success. `last_error` stores only the current unresolved bounded/redacted error and is cleared when a retry later succeeds.
- The delivery framework supports at-least-once delivery to each intended Event Handler. Exactly-once handler side effects, strict global ordering, and distributed transactions with handler side effects are not promised.
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

Post-commit delivery
   ├── service-layer best-effort enqueue of committed Event Delivery IDs
   ├── Dramatiq message carries Delivery ID plus diagnostic-only metadata
   └── workers reload Event Delivery and Domain Event from PostgreSQL → handler execution
```

## Initial event catalogue

AF-219 ships the first concrete events as RBAC audit inputs and usage examples:

- `organization.role.changed` — emitted when a Membership's Organization Role changes.
- `agent.access.granted` — emitted when explicit Agent Access is granted to a Membership.
- `agent.access.revoked` — emitted when explicit Agent Access is removed from a Membership.
- `agent.general_access.changed` — emitted when an Agent's General Access role changes.
- `agent.created` — emitted after an Agent is successfully created.
- `agent.started` — emitted after an Agent transitions to `RUNNING`.
- `agent.stopped` — emitted after an Agent transitions to `STOPPED`.

RBAC events are intended for the `security_audit.projection` Event Handler. Agent start/stop events are intended for the `agent.lifecycle_email.notification` Event Handler, which emails the Agent Creator and users with Agent Owner access, de-duplicated by email. The Security Audit Record projection is implemented by a later slice; the events themselves are persisted by the business mutation transaction.

## Delivery worker contract

Immediate enqueue is strictly post-commit. Repositories own the transaction that writes business state, the Outbox Message, and intended Event Deliveries; services perform best-effort enqueue afterward through a transport adapter. If enqueue succeeds, the delivery becomes `ENQUEUED` and records `enqueued_at`; if enqueue fails, the committed delivery remains `PENDING`, the failure is logged/metricized, and reconciliation repairs it later. Product and Ingest API health does not depend on Redis/Dramatiq availability.

Dramatiq messages contain only the Event Delivery ID and safe diagnostic metadata such as correlation ID, publish source, or publish time. Message metadata is never authoritative and must not include event payload, actor/subject data, handler routing authority, retry truth, credentials, or secrets. Workers process by reloading the Event Delivery, Outbox Message, and Domain Event envelope from PostgreSQL.

The processor must atomically claim an eligible delivery in PostgreSQL before executing a handler. Claiming transitions `ENQUEUED` or stale `PROCESSING` to `PROCESSING`, sets `claimed_at`, and increments `attempt_count`; `PENDING`, fresh `PROCESSING`, `SUCCEEDED`, and `DEAD_LETTERED` are no-ops. Missing Delivery IDs in transport messages are logged/metricized and not retried forever because PostgreSQL is authoritative.

Handlers use a formal interface. A handler has a unique stable name, declares supported event names and schema versions through a static startup registry, receives the `DomainEventEnvelope` plus a small `EventDeliveryContext`, and completes normally or raises typed retryable/terminal errors. Handler names are durable operational contracts once Event Deliveries can reference them; unknown handlers or unsupported event versions are terminal configuration errors and dead-letter their deliveries.

Handler side effects are at-least-once. The delivery framework prevents execution after terminal states, but a worker can crash after a handler commits side effects and before marking the delivery `SUCCEEDED`; each handler must prove its own idempotency using an appropriate key such as `event_id` or `(event_id, handler_name)`. Handlers may own their own database transactions, but they must not mutate Event Delivery lifecycle state directly.

Retryable handler failures leave the delivery `PROCESSING`, persist bounded/redacted `last_error`, and re-raise to Dramatiq. Dramatiq owns bounded exponential retry scheduling and retry-exhaustion callbacks; PostgreSQL does not run a competing retry scheduler. Exhaustion or terminal handler errors mark the delivery `DEAD_LETTERED`, set `completed_at`, persist bounded/redacted `last_error`, and set a required dead-letter reason such as retry exhaustion, terminal handler error, unknown handler, unsupported event, or invalid delivery.

Reconciliation is a worker-owned, one-shot, bounded command scheduled by infrastructure. It scans Event Deliveries, not Outbox Messages, using row locking/`SKIP LOCKED`, a bounded batch size, max runtime, and low publish concurrency. It republishes `PENDING` deliveries after a short grace period, stale `ENQUEUED` deliveries by `enqueued_at`, and stale `PROCESSING` deliveries by `claimed_at`; `SUCCEEDED` and `DEAD_LETTERED` are never automatically republished. Each successful publish is individually marked `ENQUEUED`; individual publish failures are logged/metricized and left eligible.

Delivery timing and retry values are code constants to keep the operational surface small: pending grace 60 seconds, enqueued stale 300 seconds, processing stale 900 seconds, retry attempts 20, and retry backoff 15 to 900 seconds. The Redis URL and reconciler schedule remain externally configurable.

## Usage examples

### Add a Domain Event type

Define the event name and payload schema in `../../api/domains/events/catalog.py`, then register the schema version and intended handler names in `build_default_event_registry()`:

```python
AGENT_RENAMED = "agent.renamed"

class AgentRenamedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    previous_name: str
    new_name: str

registry.register(
    DomainEventDefinition(
        event_name=AGENT_RENAMED,
        schema_version=1,
        payload_model=AgentRenamedPayload,
        handler_names=(SECURITY_AUDIT_HANDLER,),
    )
)
```

Rules for event schemas:

- Use canonical domain names from `../../CONTEXT.md`.
- Include `organization_id` and any tenant-owned IDs the registry should validate.
- Keep payloads bounded, secret-safe JSON objects; never include credentials, tokens, raw provider payloads, or unbounded text.
- Add a new schema version instead of mutating a persisted event contract incompatibly.

### Produce an event with a business mutation

A repository method that emits a Domain Event owns one explicit transaction. It mutates business state, builds the typed event, stages the Outbox Message and Event Deliveries, captures the committed delivery IDs, and commits once:

```python
with Session(self.delegate.engine, expire_on_commit=False) as session:
    agent = session.get(Agent, agent_id)
    previous_name = agent.name
    agent.name = new_name
    session.add(agent)
    session.flush()

    event = EVENT_REGISTRY.build_event(
        event_name=AGENT_RENAMED,
        schema_version=1,
        occurred_at=datetime.now(UTC),
        organization_id=agent.organization_id,
        actor=actor,
        subject=SubjectIdentity(
            type=SubjectIdentityType.AGENT,
            id=agent.id,
            organization_id=agent.organization_id,
        ),
        correlation_id=correlation_id,
        payload={
            "organization_id": agent.organization_id,
            "agent_id": agent.id,
            "previous_name": previous_name,
            "new_name": new_name,
        },
    )
    self.outbox_repository.stage(session=session, event=event, registry=EVENT_REGISTRY)
    delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
    session.commit()
```

Do not build or stage events in routes. Do not let the outbox open a second transaction for a business mutation that must be atomic with the event.

### Enqueue committed deliveries from the service layer

After the repository commit succeeds, the service performs best-effort immediate enqueue through `EventDeliveryTransport`. Publish failure is logged and swallowed so the committed business operation remains successful and reconciliation can repair the `PENDING` delivery:

```python
for delivery_id in result.delivery_ids:
    try:
        self.event_delivery_transport.enqueue(delivery_id, metadata={"source": "immediate"})
        self.outbox_repository.mark_delivery_enqueued(delivery_id)
    except Exception as exc:
        logger.warning("Immediate Event Delivery enqueue failed for %s: %s", delivery_id, bound_delivery_error(exc))
```

Only mark a delivery `ENQUEUED` after transport publish returns successfully.

### Add an Event Handler

Handlers are statically registered startup dependencies. For example, `agent.lifecycle_email.notification` handles `agent.started` and `agent.stopped` by sending lifecycle email notifications to the Agent Creator and Agent Owners. A handler declares a stable name, supported event versions, and receives both the business event and delivery context:

```python
class SecurityAuditProjection:
    name = SECURITY_AUDIT_HANDLER
    supported_events = (SupportedEvent(AGENT_RENAMED, 1),)

    def handle(self, event: DomainEventEnvelope, context: EventDeliveryContext) -> None:
        # Use event.event_id or (event.event_id, context.handler_name) as an idempotency key.
        # Commit handler-owned side effects in the handler's own transaction.
        ...
```

Wire handlers in the `EventHandlerRegistry` provider, not dynamically at runtime:

```python
@provider
@singleton
def provide_event_handler_registry(self, audit_projection: SecurityAuditProjection) -> EventHandlerRegistry:
    return EventHandlerRegistry([audit_projection])
```

Handler rules:

- Handler names are durable contracts. Do not rename or remove one while incomplete Event Deliveries can reference it.
- Handlers must be idempotent; at-least-once delivery can call them again after a crash.
- Return normally for success.
- Raise `RetryableEventHandlerError` for transient failures that Dramatiq should retry.
- Raise `TerminalEventHandlerError` for non-retryable handler failures that should dead-letter immediately.
- Do not mutate Event Delivery state directly; the processor owns lifecycle transitions.

### Test the event slice

A new event-producing mutation should cover:

- payload validation and secret rejection in `../../api/tests/unit/test_domain_events.py` or neighboring unit tests;
- one-transaction persistence of business state, Outbox Message, and Event Deliveries in integration tests;
- post-commit enqueue success and enqueue failure leaving committed deliveries recoverable;
- handler success, retryable error, terminal error, duplicate/no-op behavior, and handler idempotency.

Use `../../api/tests/integration/test_outbox_messages.py`, `../../api/tests/unit/test_event_handlers.py`, and `../../api/tests/unit/test_event_delivery_*` as examples.

### Run delivery workers locally

The Product API can commit Domain Events without Redis, but low-latency delivery requires Redis and the worker process. Set `EVENT_DELIVERY_REDIS_URL` when Redis is not at the local default:

```bash
EVENT_DELIVERY_REDIS_URL=redis://localhost:6379/0 \
  uv run dramatiq api.domains.events.worker --processes 1 --threads 4 --queues event-deliveries
```

Run the reconciler as a one-shot repair command; infrastructure owns the production schedule:

```bash
EVENT_DELIVERY_REDIS_URL=redis://localhost:6379/0 \
  uv run python -m api.domains.events.reconciliation
```

## Boundaries

The event domain owns envelope types, payload validation, event registry, handler registry contract, outbox persistence, delivery persistence, and delivery processing state machine. Business domains decide when their own mutations produce Domain Events and should expose domain-specific repository operations for those all-or-nothing writes. Routes must not manage sessions, stage events, or publish deliveries directly. Services may orchestrate post-commit enqueue, but SQL and transaction mechanics stay in repositories and Dramatiq remains hidden behind the transport adapter.

This foundation deliberately excludes event sourcing, public webhooks, replay administration, strict global ordering, broker-specific domain types in domain models, manual dead-letter replay/remap tooling, and broad migration of existing workflows.

## Source map

| Concern | Authoritative source |
| --- | --- |
| Domain Event envelope, identities, Outbox Message, Event Delivery models | `../../api/domains/events/models.py` |
| Event catalogue | `../../api/domains/events/catalog.py` |
| Event registry and payload validation | `../../api/domains/events/registry.py` |
| Session-aware outbox staging and persistence reads | `../../api/domains/events/repository.py` |
| Event Handler registry and delivery processor | `../../api/domains/events/handlers.py`, `../../api/domains/events/processor.py` |
| Dramatiq transport adapter and worker actors | `../../api/domains/events/transport.py`, `../../api/domains/events/worker.py` |
| Event Delivery reconciler | `../../api/domains/events/reconciliation.py` |
| Schema migrations | `../../api/migrations/versions/b4c7e2a19d34_add_outbox_message.py`, `../../api/migrations/versions/c9d8e7f6a5b4_add_event_delivery.py` |
| Unit validation tests | `../../api/tests/unit/test_domain_events.py` |
| PostgreSQL persistence and transaction tests | `../../api/tests/integration/test_outbox_messages.py` |

## Related decisions

- [`2026-07-25-transactional-domain-event-outbox.md`](../adr/2026-07-25-transactional-domain-event-outbox.md)
- [`2026-07-26-dramatiq-event-delivery.md`](../adr/2026-07-26-dramatiq-event-delivery.md)

## Change impact

Adding a Domain Event requires a registered event name/version, payload schema, intended handler mapping, payload safety tests, and repository/integration coverage for any event-producing mutation. Adding an event-producing business mutation requires a domain-specific repository transaction boundary that commits business state and staged event rows together, plus service-layer post-commit enqueue if low-latency delivery is required. Adding an Event Handler requires static registry wiring, idempotency design, success/retry/terminal-failure tests, and metrics/logging coverage. Changes to event envelope fields, delivery identity, lifecycle states, dead-letter reasons, handler registry semantics, reconciliation thresholds, or privacy rules require model, migration, registry/processor tests, this document, and ADR review when the decision changes.
