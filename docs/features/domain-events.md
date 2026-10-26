# Domain Events

## Read when

Read before adding or changing internal Domain Events, Outbox Messages, Event Deliveries, Event Handlers, event payload schemas, audit projections, or repository operations that stage events.

## Role in the system

Agent Barn uses internal Domain Events to record immutable, typed business facts at either Organization or Platform scope. A committed Domain Event is persisted as one PostgreSQL `event_outbox_message` row and one `event_delivery` row per currently registered Event Handler. PostgreSQL is the durable source for event intent and intended handler delivery state; Dramatiq/Redis is the low-latency, at-least-once transport for committed Event Deliveries.

## Invariants

- Domain Events are internal business facts, not runtime Telemetry Events, public webhooks, audit records, queue messages, or event-sourced entity history.
- Event names and schema versions are registered in code through a typed registry. Unsupported names or versions fail before persistence.
- Event envelopes include event ID, event name, schema version, occurred-at time, explicit Event Scope, optional Organization ID, typed Actor Identity, typed Subject Identity, required correlation ID, optional causation ID, and bounded Event Payload.
- Event Payloads are JSON objects validated by their event schema and by recursive safety checks. Secrets, credentials, unsupported values, oversized content, and sensitive key names are rejected.
- Organization-scoped events require exactly one Organization ID. Known actor, subject, and validated payload references that belong to a different Organization are rejected before commit.
- Platform-scoped events prohibit an Organization ID and prohibit Organization references in Actor, Subject, and payload data. User is a valid Platform event subject.
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
- Security Audit Records are idempotent projections from selected Domain Events, keyed by Event ID. They store stable actor/subject identity and display snapshots without foreign keys so deletion of product entities does not erase security evidence. Event payload safety checks remain the first redaction boundary.
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
- `platform.user_privilege.granted` — emitted atomically when Platform Privilege is granted.
- `platform.user_privilege.revoked` — emitted atomically when Platform Privilege is revoked.
- `platform.agent_size.created` / `platform.agent_size.deleted` — emitted atomically when a Platform Administrator adds a size to the Agent Size catalog or removes one, carrying the size's name as `subject_display` and all of its values (CPU and memory requests and limits, `enabled`, `is_default`). The subject is the `SYSTEM` size row.
- `platform.agent_size.changed` — emitted atomically, one event per field that moved, naming the `setting` with its `previous` and `current` value. Making a size the default records two events in one correlation: `is_default` turning false on the old default and true on the new one. Not emitted when a save leaves every value unchanged. All three go to Security Audit.
- `platform.resource_limits.changed` — emitted atomically when a Platform Administrator changes a namespace quota ceiling, one event per ceiling that moved, naming the setting (`limits_memory_bytes`, `limits_cpu_cores`, `requests_memory_bytes` or `requests_cpu_cores`) with its previous and current value. The subject is the `SYSTEM` limits row. Not emitted when a save leaves the value unchanged.
- `platform.trial_settings.changed` — emitted atomically when a Platform Administrator changes a trial setting (`self_signup_enabled`, `credit_usd`, `agent_limit` or `max_active_trials`), one event per setting that moved, with its previous and current value (booleans for signup, numbers for credit and limits, `null` for no cap). The subject is the `SYSTEM` trial settings row. Not emitted when a save leaves the value unchanged.
- `organization.trial.ended` — emitted atomically when a Platform Administrator ends a Trial Organization's trial. Not emitted when the Organization was not a trial.
- `organization.agent_sizes.changed` — emitted atomically when a Platform Administrator changes the [Agent Sizes](agent-sizes.md#organization-choice) an Organization may choose, with the set before and after as ids and names. Organization scope, like the platform-set `organization.llm_budget.changed`; the actor is the administrator's Membership when they have one there, else their user. Also emitted, once per Organization and in the switch's correlation with the administrator's user as actor, when making a size the default swaps the old default into a set that held the new one. Not emitted when the set is unchanged. Security Audit.
- `agent.agent_size.changed` — emitted atomically when an Owner or Admin chooses an Agent's size, on hire (from the default, in the `agent.created` correlation) or later, or a Platform Administrator overrides or clears it, with the size before and after (`agent_size_id` and `agent_size_name`, both null for the default). `by_platform` is true for the platform's override and its clearing (absent, so false, on records written before overrides existed); the actor is then the administrator's Membership when they have one there, else their user. Organization scope, Security Audit. Not emitted when the choice is unchanged. A dedicated event rather than an `agent.updated` field, because the size has its own route and permission and is never written by the general Agent update.

AF-381 (prepaid credit) adds, all projected by `security_audit.projection`:

- `organization.trial.ended` is also emitted when a credit purchase converts a trial (actor: the payment system, `actor_display` "Credit purchase").
- `organization.trial.expired` — emitted once when a trial runs out of credit; it then no longer counts toward the cap on active trials. Emitted by the `organization.trial_expiry.projection` Event Handler, which handles `organization.llm_budget.exhausted` (alongside the budget email and product analytics handlers).
- `organization.agent_limit.changed` — emitted atomically when a Platform Administrator sets or clears an Organization's own Agent limit, with the previous and current limit (`null` follows the default).
- `platform.billing_settings.changed` — emitted atomically when a Platform Administrator changes a billing setting (`payments_enabled`, `min_purchase_usd`, `max_purchase_usd`, `purchase_fee_percent`), one event per setting that moved, same payload shape as `platform.trial_settings.changed`.
- `platform.organization_settings.changed` — the same, for the platform's Organization settings (`default_agent_limit`).
- `platform.credit_purchase.unapplied` — emitted when a paid credit purchase arrives for an Organization that no longer runs on Credit, so nothing was granted; carries the payment reference, the credit, the amount paid and the reason (for example, the amount paid doesn't match the checkout we created), and names the Organization in `subject_display` (a Platform event carries no Organization id). Also emitted for a paid session that doesn't match a checkout we created.

AF-167 broadens Security Audit Record coverage to additional mutations:

- `agent.updated` — emitted when `update_agent` changes a tracked scalar field (name, model, approval_mode, template pin); carries a generic `field_changes` diff and is not emitted when no tracked field actually changed.
- `agent.deleted` — emitted when an Agent is soft-deleted.
- `agent.secret.added` / `agent.secret.updated` / `agent.secret.removed` — emitted on Agent Secret (credential) create/update/delete; payload is built allowlist-style from safe fields only and never includes the encrypted `content`.
- `template.created` / `template.updated` / `template.deleted` — emitted on org Template lineage create/update/delete; `template.updated`'s `field_changes` is scoped to `template_name`/`description` only, excluding the markdown prompt bodies.
- `organization.model_allowlist.changed` — emitted when an Organization's `allowed_models` list changes.
- `organization.agent_settings.changed` — emitted when an Organization's Agent Settings change, naming the setting and carrying its previous and current values plus the number of Agents that inherit it. Not emitted when a save leaves the value unchanged.
- `organization.value_settings.changed` — emitted when an Organization's value settings change: its hourly rate, or the minutes saved for an Outcome Type.
  - Carries a `field_changes` diff keyed `hourly_rate_usd` or `outcome_minutes.<OUTCOME_TYPE>`. Each entry holds `previous` and `current` as strings, where `null` means unset or the default.
  - Not emitted when a save changes nothing.
  - Emitted by `PUT /organizations/{organization_id}/value-settings` (see [`business-value.md`](business-value.md#value-settings)).
- `organization.member.added` / `organization.member.removed` — emitted on Organization membership add/remove.
- `organization.created` — emitted in the creating transaction, for self-service creation (`POST /organizations`, User Actor = creator), for Platform Administrator onboarding (`POST /platform/users`, User Actor = administrator), and for a Google self-signup's trial Organization (`GoogleSignInService._sign_up`, User Actor = the new user). Its only intended handler is `product_analytics.posthog`.
- `organization.updated` — emitted by `PATCH /organizations/{organization_id}` only when the Organization's name or description actually changes. Its actor is the acting User, not their Membership, so it is still attributable if the Organization is deleted before delivery. It carries the changed field names, never their values, and its only intended handler is `product_analytics.posthog`. An allowlist change in the same request still emits `organization.model_allowlist.changed` alongside it.
- `organization.deleted` — staged in the same transaction as the Organization's hard delete, with a User Actor (the deleting Owner). The outbox and delivery rows have no foreign key to the Organization, so they outlive it. Its only intended handler is `product_analytics.posthog`.
- `organization.ownership_transferred` — emitted when Organization ownership transfers between Memberships.

Workflow authoring adds the Platform-scoped `platform.workflow_authoring.changed`
event, carrying previous/current booleans and safe actor/subject display snapshots,
projected by `security_audit.projection`. Its atomic settings boundary and no-op
behavior are owned by [Agent workflows](agent-workflows.md#platform-authoring-setting).

Agent Memory adds the Platform-scoped `platform.memory_model.changed` event, carrying previous/current model IDs and safe actor/subject display snapshots, projected by `security_audit.projection`.

Agent Memory adds Organization-scoped events handled by `security_audit.projection`: `agent.memory.enabled`, `agent.memory.disabled`, `agent.memory_grant.created`, and `agent.memory_grant.revoked`. The Subject is the reading Agent, and payloads contain scoped IDs and display snapshots, never memory content. The state change and event commit atomically; repeating the current opt-in setting emits nothing. See [`Agent Memory`](agent-memory.md).

Playbooks add the Platform-scoped `platform.playbook_model.changed` event, carrying previous/current model IDs and display snapshots, and the Organization-scoped `playbook.extraction.requested` event, both projected by `security_audit.projection`. It commits with the queued run; its Subject is the source Agent whose transcripts the run reads, and its payload carries IDs, the target Skill name, the window length, the session bound, and display snapshots, never transcript or playbook content. See [`Playbooks`](playbooks.md).

AF-273 adds Communications operational events as Organization-scoped audit inputs:

- `communication.connection.health.changed` — emitted when a Connection's observed provider health changes.
- `communication.connection.reconnect.requested` — emitted when an authorized user requests one Connection reconnect.
- `communication.delivery.dead_lettered` — emitted when a Communication Delivery exhausts its bounded automatic attempts.
- `communication.delivery.retry.requested` — emitted when an authorized user requeues one dead-lettered outbound Delivery.
- `communication.delivery.recovered` — emitted when that retried Delivery succeeds.

These events carry scoped resource IDs, lifecycle status, attempt/error metadata, and safe actor/subject display snapshots only. The Connection health event may also carry the validated, content-free diagnostic envelope (category, operation, HTTP status, provider code, retryability, bounded retry-after value, and provider request ID); it never carries provider URLs, credentials, headers, bodies, or exception text. The separate Communications operation journal remains runtime diagnostics rather than a Domain Event stream; it records intermediate attempts and timings without payload content, credentials, or sender identity.

RBAC, Platform Privilege, and the AF-167 events above are intended for the `security_audit.projection` Event Handler, which persists deletion-independent Security Audit Records. Agent start/stop events are intended for the `agent.lifecycle_email.notification` Event Handler, which emails the Agent Creator and users with Agent Owner access, de-duplicated by email.

`agent.created`, `agent.updated`, `agent.started`, `agent.stopped`, `agent.deleted`, `organization.member.added`, `organization.member.removed`, `organization.role.changed`, `organization.ownership_transferred`, and `organization.llm_budget.exhausted` are also intended for the `product_analytics.posthog` Event Handler. That handler forwards them to PostHog when analytics is enabled. See [`product-analytics.md`](product-analytics.md).

## Delivery worker contract

Immediate enqueue is strictly post-commit. Repositories own the transaction that writes business state, the Outbox Message, and intended Event Deliveries; services perform best-effort enqueue afterward through a transport adapter. If enqueue succeeds, the delivery becomes `ENQUEUED` and records `enqueued_at`; if enqueue fails, the committed delivery remains `PENDING`, the failure is logged/metricized, and reconciliation repairs it later. Product and Ingest API health does not depend on Redis/Dramatiq availability.

Dramatiq messages contain only the Event Delivery ID and safe diagnostic metadata such as correlation ID, publish source, or publish time. Message metadata is never authoritative and must not include event payload, actor/subject data, handler routing authority, retry truth, credentials, or secrets. Workers process by reloading the Event Delivery, Outbox Message, and Domain Event envelope from PostgreSQL.

The processor must atomically claim an eligible delivery in PostgreSQL before executing a handler. Claiming transitions `ENQUEUED` or stale `PROCESSING` to `PROCESSING`, sets `claimed_at`, and increments `attempt_count`; `PENDING`, fresh `PROCESSING`, `SUCCEEDED`, and `DEAD_LETTERED` are no-ops. Missing Delivery IDs in transport messages are logged/metricized and not retried forever because PostgreSQL is authoritative.

Handlers use a formal interface. A handler has a unique stable name, declares supported event names and schema versions through a static startup registry, receives the `DomainEventEnvelope` plus a small `EventDeliveryContext`, and completes normally or raises typed retryable/terminal errors. Handler names are durable operational contracts once Event Deliveries can reference them; unknown handlers or unsupported event versions are terminal configuration errors and dead-letter their deliveries. The worker resolves the registry from one process-wide injector, so handler instances are singletons shared across worker threads: they must keep no per-delivery mutable state and must open their own database sessions per call.

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
        event_scope=EventScope.ORGANIZATION,
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

The Product API can commit Domain Events without Redis, but low-latency delivery requires Redis and the worker process. `./run.sh` starts Redis and the worker (`worker` service in `../../compose.yml`, a general-purpose background job container — not event-delivery-specific) alongside the API automatically.

Running the API outside Docker (`make dev-api`), start Redis and the worker separately:

```bash
make redis-up
make dev-worker   # uv run dramatiq api.worker_app --processes 1 --threads 4
```

Run the reconciler as a one-shot repair command; infrastructure owns the production schedule:

```bash
make reconcile    # uv run python -m api.domains.events.reconciliation
```

Both `make dev-worker` and `make reconcile` read `REDIS_URL` from the repo-root `.env` (defaults to `redis://localhost:6379/0`, matching `REDIS_PORT`).

## Platform Event Delivery Monitor

AF-247 adds the first read API and UI over this domain: a Platform Administrator–only, global Platform View surface for inspecting Event Delivery pipeline health. It is strictly read-only and monitors **Event Deliveries**, not Outbox Messages — an Outbox Message is immutable publication intent with no lifecycle status, and an event with no intended handlers has zero Event Deliveries and never appears here.

- Endpoints (Platform Administrator only, `401` unauthenticated / `403` non-admin, no Active Organization resolved or accepted):
  - `GET /api/v1/platform/event-deliveries/summary` — global counts for all five lifecycle statuses (including zero) plus, for each active state (`PENDING`, `ENQUEUED`, `PROCESSING`), oldest age, stale count, unknown-age count, and the configured stale threshold.
  - `GET /api/v1/platform/event-deliveries` — page/offset explorer, default and max page size 50/100, deterministic `(created_at, id)` ordering (newest-first default, oldest-first optional), covering both Organization- and Platform-scoped deliveries. It is filterable by status/Organization/event name/created-at range, with free-text search (exact match on Delivery ID or Event ID; case-insensitive prefix match on Organization name, event name, or handler name; `last_error` is never searched). Platform-scoped rows return `organization_id` and `organization_name` as `null`.
  - `GET /api/v1/platform/event-deliveries/event-types` — the registry catalogue as event name plus schema versions, limited to definitions with at least one intended Event Handler (a handler-less event, e.g. `agent.restore_point.created`, can never produce a delivery and is excluded).
- State age semantics reuse the domain's own clocks — `PENDING` → `created_at`, `ENQUEUED` → `enqueued_at`, `PROCESSING` → `claimed_at` — and the reconciler's configured thresholds (`EVENT_DELIVERY_RECONCILIATION_PENDING_GRACE_SECONDS`, `EVENT_DELIVERY_RECONCILIATION_ENQUEUED_STALE_SECONDS`, `EVENT_DELIVERY_PROCESSING_STALE_SECONDS`) as the single source of truth for "stale." A missing required state timestamp is surfaced as unknown age, never backfilled from `created_at`.
- The delivery response is safe operational metadata only (identity, status, timing, attempt count, dead-letter reason, bounded/redacted `last_error`, derived `status_since`) and never includes Event Payload, Actor/Subject Identity, or correlation/causation data. `last_error` is re-bounded/redacted at this read boundary as defense in depth, independent of the write-time bounding in `repository.py`.
- The UI (`../../ui/src/features/event-deliveries/`) renders this at `/dashboard/platform/event-deliveries` with URL-backed filters/sort, a manual **Refresh** action (no polling), `useInfiniteQuery` + TanStack Virtual for the explorer, and one expandable inline row at a time.

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
| Security Audit Record model and projection | `../../api/domains/events/security_audit.py` |
| Product analytics Event Handler | `../../api/domains/analytics/event_handlers.py`, [`product-analytics.md`](product-analytics.md) |
| Dramatiq transport adapter and worker actors | `../../api/domains/events/transport.py`, `../../api/domains/events/worker.py`, `../../api/worker_app.py` |
| Event Delivery reconciler | `../../api/domains/events/reconciliation.py` |
| Platform Event Delivery Monitor service and routes | `../../api/domains/events/service.py`, `../../api/domains/events/routes.py` |
| Platform Event Delivery Monitor UI | `../../ui/src/features/event-deliveries/` |
| Schema migrations | `../../api/migrations/versions/b4c7e2a19d34_add_outbox_message.py`, `../../api/migrations/versions/c9d8e7f6a5b4_add_event_delivery.py`, `../../api/migrations/versions/2a4f6c8e1b30_add_organization_creator.py`, `../../api/migrations/versions/b7f3d8e1c4a9_add_event_delivery_monitor_indexes.py` |
| Unit validation tests | `../../api/tests/unit/test_domain_events.py` |
| PostgreSQL persistence and transaction tests | `../../api/tests/integration/test_outbox_messages.py` |
| Platform Event Delivery Monitor API tests | `../../api/tests/integration/test_event_delivery_monitor.py` |
| Platform Event Delivery Monitor UI tests | `../../ui/tests/e2e/event-deliveries.spec.ts` |

## Related decisions

- [`2026-07-25-transactional-domain-event-outbox.md`](../adr/2026-07-25-transactional-domain-event-outbox.md)
- [`2026-07-26-dramatiq-event-delivery.md`](../adr/2026-07-26-dramatiq-event-delivery.md)
- [`2026-07-30-explicit-platform-and-organization-event-scopes.md`](../adr/2026-07-30-explicit-platform-and-organization-event-scopes.md)
- [`2026-07-31-retain-security-audit-records-across-product-deletion.md`](../adr/2026-07-31-retain-security-audit-records-across-product-deletion.md)

## Change impact

Adding a Domain Event requires a registered event name/version, payload schema, intended handler mapping, payload safety tests, and repository/integration coverage for any event-producing mutation. Adding an event-producing business mutation requires a domain-specific repository transaction boundary that commits business state and staged event rows together, plus service-layer post-commit enqueue if low-latency delivery is required. Adding an Event Handler requires static registry wiring, idempotency design, success/retry/terminal-failure tests, and metrics/logging coverage. Changes to event envelope fields, delivery identity, lifecycle states, dead-letter reasons, handler registry semantics, reconciliation thresholds, or privacy rules require model, migration, registry/processor tests, this document, and ADR review when the decision changes.

Changes to the Platform Event Delivery Monitor's summary/explorer response contract, stale-threshold semantics, redaction behavior, or supported filters require updating `api/domains/events/models.py` (DTOs), `repository.py` (query composition), `service.py`/`routes.py`, the matching UI schemas/hooks/components under `ui/src/features/event-deliveries/`, this document, and both test suites listed in the source map. A new index needed for a monitor query requires an Alembic migration under `api/migrations/versions/`.

## Workflow run wakeups

Workflow run transitions stage `workflow.run.changed` v1 with the run identity,
revision and state only, alongside their ledger/history transaction. The
`workflow.controller` handler advances durable intent and dispatches steps to the
owning Agent through the Kubernetes client. It tolerates duplicate events and
uses the same cluster access as the API. Services and the controller enqueue
staged delivery IDs immediately after each successful ledger commit, including
starts, cancellation, step results, failures and recovery transitions. Broker
failures leave committed deliveries pending for reconciliation. A scheduled
workflow operator pass handles missed events, expired attempts and retention. Run inputs, reasoning, files and capability credentials never enter
the event payload. These are workflow wakeup facts, not Security Audit or product
analytics projections. See the [workflow feature](agent-workflows.md#wf02-execution-and-outputs).

## Personal API Key security events

Platform-scoped `api_key.created` and `api_key.revoked` events record account credential lifecycle with a User actor and User subject. Their payloads contain only the User ID, key record ID, access mode, and safe display fields. The API Key repository commits each key mutation and outbox/delivery rows in one transaction; the Security Audit projection persists the resulting record.

## User login events

Platform-scoped `user.logged_in` records each successful login, with a User actor and User subject and the payload `user_id` and `method`. It is written through `AuthService.record_login`, which uses `OutboxMessageRepository.create` and enqueues the event. A failure to record it is logged and never fails the login. Its only intended handler is `product_analytics.posthog`. Failed logins, token refresh and API-key authentication emit nothing.

- **Password login** (`POST /auth/login`) records `method: "password"` after the credential check.
- **Google sign-in** (`GET /auth/google/callback`) records `method: "google"` after the session is issued, but only when the account already existed and was verified. That covers an account found by its Google id and an existing verified account linked to Google by its address. A first sign-in that creates the account, and an invitee enrolled through Google, are not logins. Nor is the losing side of two simultaneous first sign-ins.

Platform-scoped `user.signed_up` records an invitee's first enrollment. `PasswordResetTokenRepository.redeem` handles both invite acceptance and password reset in one transaction. It locks the token and the user, applies the password, marks the token used, and stages the event only for invite acceptance when the email was not yet verified. A reused token is rejected, and a password reset never emits it. Its payload carries `method`: `invite` for these enrollments. Google sign-in also emits it through `UserRepository.stage_user_signed_up`, in the transaction that creates or enrolls the account:

- `method: "google"` when `_sign_up` creates a self-signed-up User and trial Organization. The same transaction also stages `organization.created`.
- `method: "invite"` when `_link` enrolls a pending invitee.

Refused sign-ups and returning sign-ins emit nothing. `GoogleSignInService.complete` enqueues the deliveries after the sign-in. Its only intended handler is `product_analytics.posthog`.

`user.onboarding.completed` records the first `POST /onboarding/complete` for a user, with a User actor and User subject and the payload `user_id`. `UserRepository.complete_onboarding` sets `onboarding_completed_at` with a conditional update (only while it is null) and stages the event in the same transaction only when that update changed the row, so a repeat or a simultaneous second call emits nothing. It is scoped to the first Organization the user created (a self-signed-up user's trial), or to the platform when they created none. Its definition has no fixed scope for that reason. Its only intended handler is `product_analytics.posthog`.

`telegram.account.linked` and `telegram.account.unlinked` record Agent Barn Telegram links. They are Organization-scoped to the link's own Organization, with the link's issuing Membership as a Membership actor and the link's Agent as subject. The payload is `organization_id`, `agent_id`, `connection_id` and `link_id`, plus `reason` on an unlink. They never carry the Telegram user id or username. `AgentBarnTelegramRepository._consume` stages `linked` in the transaction that spends the token, and `unlinked` with `reason: "relinked"` for the Telegram user's previous link that it ends. That previous link can belong to another Organization, so its event uses that link's Organization and Membership. A failed attempt that is retried rolls its staged rows back with the rest of the transaction. Every other path that ends a link stages `unlinked` in the same transaction as the ending, and only when a link actually ended:
- `unlink_in_scope` (the web app's unlink) uses `reason: "user_removed"`, with the clicking user's resolved actor.
- `end_active_link` and `end_link_for_connection` (the shared bot's poller, forwarder and Bot API proxy) use `reason: "blocked_bot"` or `"access_lost"`, with the link's issuing Membership as actor.

A Membership deletion cascades its links away without an event.

`telegram.first_message.received` uses the same scope, actor, subject and payload as `linked`. `AgentBarnTelegramRepository.queue_update` stages it in the transaction that queues a linked user's new message, through a conditional update that sets `agentbarn_telegram_link.first_message_at` only while the link is active and the column is null. So it fires once per link, even for simultaneous messages. The processor asks for it only for a new `message`, never for an edit or a button press. Migration `a78bcde4b918` set `first_message_at` to `created_at` for links that already existed. It is delivered by the outbox reconciler. These writes run in the Communications process. The link-token and web-app paths enqueue after commit; the poller, forwarder and proxy paths rely on the outbox reconciler. Their only intended handler is `product_analytics.posthog`.
