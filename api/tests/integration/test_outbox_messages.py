from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from hamcrest import assert_that, equal_to, is_not, none
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import Session

from api.core.config import get_config
from api.domains.events import (
    ActorIdentity,
    ActorIdentityType,
    DomainEventDefinition,
    DomainEventRegistry,
    DomainEventValidationError,
    EventDeliveryDeadLetterReason,
    EventDeliveryStatus,
    SubjectIdentity,
    SubjectIdentityType,
)
from api.domains.events.handlers import (
    EventDeliveryContext,
    EventHandlerRegistry,
    RetryableEventHandlerError,
    SupportedEvent,
    TerminalEventHandlerError,
)
from api.domains.events.models import DomainEventEnvelope, EventDelivery, OutboxMessage
from api.domains.events.processor import EventDeliveryProcessor
from api.domains.events.repository import OutboxMessageRepository
from api.domains.organizations.models import Organization
from api.domains.rbac.catalog import OrganizationRole
from api.domains.users.models import User
from api.domains.users.organization_users.models import OrganizationUser
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import then, when


class SamplePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    organization_id: str
    detail: str = "sample"
    nested: dict[str, Any] = Field(default_factory=dict)


class RecordingEventHandler:
    name = "audit.projection"
    supported_events: Sequence[SupportedEvent] = (SupportedEvent("agent.sampled", 1),)

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[tuple[DomainEventEnvelope, EventDeliveryContext]] = []

    def handle(self, event: DomainEventEnvelope, context: EventDeliveryContext) -> None:
        self.calls.append((event, context))
        if self.error is not None:
            raise self.error


@pytest.fixture
def delegate():
    delegate = PostgresRepositoryDelegate(get_config())
    with delegate.engine.begin() as connection:
        connection.execute(text("TRUNCATE event_outbox_message CASCADE"))
        connection.execute(text('DELETE FROM "user"'))
        connection.execute(text("DELETE FROM organization"))
    try:
        yield delegate
    finally:
        with delegate.engine.begin() as connection:
            connection.execute(text("TRUNCATE event_outbox_message CASCADE"))
            connection.execute(text('DELETE FROM "user"'))
            connection.execute(text("DELETE FROM organization"))
        delegate.close()


@pytest.fixture
def organization_id(delegate: PostgresRepositoryDelegate) -> UUID:
    organization = Organization(name="Outbox Test", description=None)
    delegate.save(organization)
    return organization.id


@pytest.fixture
def registry() -> DomainEventRegistry:
    registry = DomainEventRegistry()
    registry.register(
        DomainEventDefinition(
            event_name="agent.sampled",
            schema_version=1,
            payload_model=SamplePayload,
            handler_names=("audit.projection", "activity.projection"),
        )
    )
    return registry


@pytest.fixture
def repository(delegate: PostgresRepositoryDelegate) -> OutboxMessageRepository:
    return OutboxMessageRepository(delegate=delegate)


def _organization_exists(delegate: PostgresRepositoryDelegate, organization_id: UUID) -> bool:
    return delegate.find_by_id(Organization, organization_id) is not None


def _event(registry: DomainEventRegistry, organization_id: UUID):
    return registry.build_event(
        event_name="agent.sampled",
        schema_version=1,
        occurred_at=datetime(2026, 7, 25, 12, 30, tzinfo=UTC),
        organization_id=organization_id,
        actor=ActorIdentity(
            type=ActorIdentityType.USER,
            id=uuid4(),
            organization_id=organization_id,
        ),
        subject=SubjectIdentity(
            type=SubjectIdentityType.AGENT,
            id=uuid4(),
            organization_id=organization_id,
        ),
        correlation_id=uuid4(),
        payload={"agent_id": str(uuid4()), "organization_id": str(organization_id)},
    )


def test_outbox_message_persists_validated_domain_event(
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    event = _event(registry, organization_id)

    with when("I persist it as an Outbox Message"):
        message = repository.create(event, registry)
        found = repository.get_by_event_id(event.event_id)

    with then("the durable record preserves the event envelope and payload"):
        assert_that(found, is_not(none()))
        assert found is not None
        assert_that(found.id, equal_to(message.id))
        assert_that(found.event_id, equal_to(event.event_id))
        assert_that(found.event_name, equal_to("agent.sampled"))
        assert_that(found.schema_version, equal_to(1))
        assert_that(found.organization_id, equal_to(organization_id))
        assert_that(found.occurred_at, equal_to(event.occurred_at))
        assert_that(found.created_at == event.occurred_at, equal_to(False))
        assert_that(found.actor["type"], equal_to("USER"))
        assert_that(found.subject["type"], equal_to("AGENT"))
        assert_that(found.correlation_id, equal_to(event.correlation_id))
        assert_that(found.causation_id, none())
        assert_that(found.payload, equal_to(event.payload))


def test_validation_failure_leaves_no_outbox_message(
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    with when("payload validation fails before persistence"):
        with pytest.raises(DomainEventValidationError):
            registry.build_event(
                event_name="agent.sampled",
                schema_version=1,
                occurred_at=datetime.now(UTC),
                organization_id=organization_id,
                actor=ActorIdentity(type=ActorIdentityType.USER, id=uuid4(), organization_id=organization_id),
                subject=SubjectIdentity(type=SubjectIdentityType.AGENT, id=uuid4(), organization_id=organization_id),
                correlation_id=uuid4(),
                payload={
                    "agent_id": str(uuid4()),
                    "organization_id": str(organization_id),
                    "nested": {"refresh_token": "secret"},
                },
            )

    with then("no Outbox Message is inserted"):
        assert_that(repository.count(), equal_to(0))


def test_rolled_back_outbox_message_is_not_visible(
    delegate: PostgresRepositoryDelegate,
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    event = _event(registry, organization_id)

    with when("an Outbox Message is staged and the session rolls back"):
        with Session(delegate.engine) as session:
            session.add(repository.build_message(event))
            session.rollback()

    with then("the event cannot be recovered for delivery"):
        assert_that(repository.get_by_event_id(event.event_id), none())
        assert_that(repository.count(), equal_to(0))


def test_duplicate_event_id_is_rejected_without_inserting_second_message(
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    event = _event(registry, organization_id)
    repository.create(event, registry)

    with when("the same event is inserted again"):
        with pytest.raises(IntegrityError):
            repository.create(event, registry)

    with then("only the original Outbox Message is visible"):
        assert_that(repository.count(), equal_to(1))


def test_committed_event_creates_pending_deliveries_for_registered_handlers(
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    event = _event(registry, organization_id)

    with when("I persist an event with two registered handlers"):
        message = repository.create(event, registry)
        deliveries = sorted(
            repository.list_deliveries_for_event(event.event_id), key=lambda delivery: delivery.handler_name
        )

    with then("one pending Event Delivery exists for each intended Event Handler"):
        assert_that(
            [delivery.handler_name for delivery in deliveries], equal_to(["activity.projection", "audit.projection"])
        )
        assert_that([delivery.status for delivery in deliveries], equal_to([EventDeliveryStatus.PENDING] * 2))
        assert_that([delivery.outbox_message_id for delivery in deliveries], equal_to([message.id, message.id]))
        assert_that([delivery.attempt_count for delivery in deliveries], equal_to([0, 0]))


def test_event_delivery_uniqueness_is_event_and_handler_not_retry_attempt(
    delegate: PostgresRepositoryDelegate,
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    event = _event(registry, organization_id)
    message = repository.create(event, registry)

    with when("another row is inserted for the same event and handler"):
        with pytest.raises(IntegrityError):
            with Session(delegate.engine) as session:
                session.add(
                    EventDelivery(
                        outbox_message_id=message.id,
                        event_id=event.event_id,
                        organization_id=organization_id,
                        handler_name="audit.projection",
                        attempt_count=99,
                    )
                )
                session.commit()

    with then("the original intended delivery is still the only row for that handler"):
        deliveries = repository.list_deliveries_for_event(event.event_id)
        assert_that(len(deliveries), equal_to(2))


def test_event_delivery_statuses_are_canonical():
    assert_that(
        {status.value for status in EventDeliveryStatus},
        equal_to({"PENDING", "ENQUEUED", "PROCESSING", "SUCCEEDED", "DEAD_LETTERED"}),
    )


def test_event_delivery_dead_letter_reasons_are_canonical():
    assert_that(
        {reason.value for reason in EventDeliveryDeadLetterReason},
        equal_to(
            {
                "RETRY_EXHAUSTED",
                "TERMINAL_HANDLER_ERROR",
                "UNKNOWN_HANDLER",
                "UNSUPPORTED_EVENT",
                "INVALID_DELIVERY",
            }
        ),
    )


def test_mark_delivery_enqueued_records_successful_publish(
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    event = _event(registry, organization_id)
    repository.create(event, registry)
    delivery = repository.list_deliveries_for_event(event.event_id)[0]
    enqueued_at = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)

    with when("transport publish succeeds after commit"):
        updated = repository.mark_delivery_enqueued(delivery.id, enqueued_at=enqueued_at)

    with then("the delivery is marked as known queued"):
        assert updated is not None
        assert_that(updated.status, equal_to(EventDeliveryStatus.ENQUEUED))
        assert_that(updated.enqueued_at, equal_to(enqueued_at))
        assert_that(updated.dead_letter_reason, none())


def test_claim_delivery_requires_eligible_state_and_increments_attempts(
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    event = _event(registry, organization_id)
    repository.create(event, registry)
    delivery = repository.list_deliveries_for_event(event.event_id)[0]
    repository.mark_delivery_enqueued(delivery.id, enqueued_at=datetime(2026, 7, 26, 10, 0, tzinfo=UTC))
    claimed_at = datetime(2026, 7, 26, 10, 1, tzinfo=UTC)

    with when("a worker claims an enqueued delivery"):
        claimed = repository.claim_delivery(delivery.id, claimed_at=claimed_at)
        duplicate_claim = repository.claim_delivery(delivery.id, claimed_at=claimed_at + timedelta(seconds=1))

    with then("only the first claim can execute the handler"):
        assert claimed is not None
        assert_that(claimed.status, equal_to(EventDeliveryStatus.PROCESSING))
        assert_that(claimed.claimed_at, equal_to(claimed_at))
        assert_that(claimed.attempt_count, equal_to(1))
        assert_that(duplicate_claim, none())


def test_claim_delivery_can_reclaim_stale_processing(
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    event = _event(registry, organization_id)
    repository.create(event, registry)
    delivery = repository.list_deliveries_for_event(event.event_id)[0]
    first_claimed_at = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
    repository.mark_delivery_enqueued(delivery.id, enqueued_at=first_claimed_at)
    repository.claim_delivery(delivery.id, claimed_at=first_claimed_at)

    with when("the processing claim is stale"):
        reclaimed = repository.claim_delivery(
            delivery.id,
            claimed_at=first_claimed_at + timedelta(minutes=20),
            processing_stale_before=first_claimed_at + timedelta(minutes=15),
        )

    with then("another worker can claim a new attempt"):
        assert reclaimed is not None
        assert_that(reclaimed.status, equal_to(EventDeliveryStatus.PROCESSING))
        assert_that(reclaimed.attempt_count, equal_to(2))


def test_retryable_failure_is_bounded_and_success_clears_current_error(
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    event = _event(registry, organization_id)
    repository.create(event, registry)
    delivery = repository.list_deliveries_for_event(event.event_id)[0]
    repository.mark_delivery_enqueued(delivery.id)
    repository.claim_delivery(delivery.id)

    with when("a retryable failure contains sensitive details before a later success"):
        failed = repository.mark_delivery_retryable_failure(delivery.id, "api_token=super-secret")
        succeeded = repository.mark_delivery_succeeded(
            delivery.id, completed_at=datetime(2026, 7, 26, 10, 30, tzinfo=UTC)
        )

    with then("the unresolved error is redacted and then cleared without clearing attempts"):
        assert failed is not None
        assert_that(failed.status, equal_to(EventDeliveryStatus.PROCESSING))
        assert_that(failed.last_error, equal_to("Event delivery error contained sensitive details and was redacted"))
        assert succeeded is not None
        assert_that(succeeded.status, equal_to(EventDeliveryStatus.SUCCEEDED))
        assert_that(succeeded.last_error, none())
        assert_that(succeeded.attempt_count, equal_to(1))


def test_dead_lettered_delivery_requires_reason_and_preserves_error(
    delegate: PostgresRepositoryDelegate,
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    event = _event(registry, organization_id)
    repository.create(event, registry)
    delivery = repository.list_deliveries_for_event(event.event_id)[0]

    with when("a delivery reaches terminal failure"):
        dead_lettered = repository.mark_delivery_dead_lettered(
            delivery.id,
            reason=EventDeliveryDeadLetterReason.TERMINAL_HANDLER_ERROR,
            error="handler rejected event",
            completed_at=datetime(2026, 7, 26, 10, 45, tzinfo=UTC),
        )

    with then("the state and reason are both durable"):
        assert dead_lettered is not None
        assert_that(dead_lettered.status, equal_to(EventDeliveryStatus.DEAD_LETTERED))
        assert_that(dead_lettered.dead_letter_reason, equal_to(EventDeliveryDeadLetterReason.TERMINAL_HANDLER_ERROR))
        assert_that(dead_lettered.last_error, equal_to("handler rejected event"))
        assert_that(dead_lettered.completed_at, equal_to(datetime(2026, 7, 26, 10, 45, tzinfo=UTC)))

    with then("the database rejects dead-lettered rows without a reason"):
        with pytest.raises(IntegrityError):
            with Session(delegate.engine) as session:
                persisted = session.get(EventDelivery, delivery.id)
                assert persisted is not None
                persisted.dead_letter_reason = None
                session.add(persisted)
                session.commit()


def test_reconciliation_candidates_are_delivery_state_and_timestamp_specific(
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    event = _event(registry, organization_id)
    repository.create(event, registry)
    pending, enqueued = repository.list_deliveries_for_event(event.event_id)
    now = datetime.now(UTC)
    old = now - timedelta(minutes=20)
    repository.mark_delivery_enqueued(enqueued.id, enqueued_at=old)

    processing_event = _event(registry, organization_id)
    repository.create(processing_event, registry)
    processing, succeeded = repository.list_deliveries_for_event(processing_event.event_id)
    repository.mark_delivery_enqueued(processing.id, enqueued_at=old)
    repository.claim_delivery(processing.id, claimed_at=old)
    repository.mark_delivery_enqueued(succeeded.id, enqueued_at=old)
    repository.claim_delivery(succeeded.id, claimed_at=old)
    repository.mark_delivery_succeeded(succeeded.id)

    with when("reconciliation scans stale non-terminal deliveries"):
        candidates = repository.claim_reconciliation_candidates(
            pending_created_before=now + timedelta(seconds=1),
            enqueued_before=now - timedelta(minutes=5),
            processing_claimed_before=now - timedelta(minutes=15),
            limit=10,
            skip_locked=False,
        )

    with then("pending, stale enqueued, and stale processing deliveries are selected"):
        assert_that({candidate.id for candidate in candidates}, equal_to({pending.id, enqueued.id, processing.id}))


def test_delivery_processor_executes_supported_handler_and_marks_succeeded(
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    event = _event(registry, organization_id)
    repository.create(event, registry)
    delivery = next(
        delivery
        for delivery in repository.list_deliveries_for_event(event.event_id)
        if delivery.handler_name == "audit.projection"
    )
    repository.mark_delivery_enqueued(delivery.id)
    handler = RecordingEventHandler()
    processor = EventDeliveryProcessor(repository=repository, handlers=EventHandlerRegistry([handler]))

    with when("the generic processor handles an enqueued delivery"):
        processed = processor.process(delivery.id)

    with then("the handler receives event and delivery context before success is persisted"):
        assert_that(processed, equal_to(True))
        persisted = repository.get_delivery(delivery.id)
        assert persisted is not None
        assert_that(persisted.status, equal_to(EventDeliveryStatus.SUCCEEDED))
        assert_that(persisted.last_error, none())
        assert_that(len(handler.calls), equal_to(1))
        handled_event, context = handler.calls[0]
        assert_that(handled_event.event_id, equal_to(event.event_id))
        assert_that(context.delivery_id, equal_to(delivery.id))
        assert_that(context.handler_name, equal_to("audit.projection"))
        assert_that(context.attempt_count, equal_to(1))
        assert_that(context.correlation_id, equal_to(event.correlation_id))


def test_delivery_processor_noops_missing_and_terminal_deliveries(
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    event = _event(registry, organization_id)
    repository.create(event, registry)
    delivery = repository.list_deliveries_for_event(event.event_id)[0]
    repository.mark_delivery_succeeded(delivery.id)
    handler = RecordingEventHandler()
    processor = EventDeliveryProcessor(repository=repository, handlers=EventHandlerRegistry([handler]))

    with when("the processor receives a terminal or missing delivery"):
        terminal_processed = processor.process(delivery.id)
        missing_processed = processor.process(uuid4())

    with then("it exits without invoking handlers"):
        assert_that(terminal_processed, equal_to(False))
        assert_that(missing_processed, equal_to(False))
        assert_that(handler.calls, equal_to([]))


def test_delivery_processor_dead_letters_unknown_handler(
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    event = _event(registry, organization_id)
    repository.create(event, registry)
    delivery = next(
        delivery
        for delivery in repository.list_deliveries_for_event(event.event_id)
        if delivery.handler_name == "activity.projection"
    )
    repository.mark_delivery_enqueued(delivery.id)
    processor = EventDeliveryProcessor(repository=repository, handlers=EventHandlerRegistry([RecordingEventHandler()]))

    with when("no registered handler has the delivery's stable name"):
        processed = processor.process(delivery.id)

    with then("the delivery is dead-lettered as a terminal configuration error"):
        assert_that(processed, equal_to(False))
        persisted = repository.get_delivery(delivery.id)
        assert persisted is not None
        assert_that(persisted.status, equal_to(EventDeliveryStatus.DEAD_LETTERED))
        assert_that(persisted.dead_letter_reason, equal_to(EventDeliveryDeadLetterReason.UNKNOWN_HANDLER))


def test_delivery_processor_dead_letters_unsupported_event_version(
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    event = _event(registry, organization_id)
    repository.create(event, registry)
    delivery = next(
        delivery
        for delivery in repository.list_deliveries_for_event(event.event_id)
        if delivery.handler_name == "audit.projection"
    )
    repository.mark_delivery_enqueued(delivery.id)

    class WrongVersionHandler(RecordingEventHandler):
        supported_events: Sequence[SupportedEvent] = (SupportedEvent("agent.sampled", 2),)

    processor = EventDeliveryProcessor(repository=repository, handlers=EventHandlerRegistry([WrongVersionHandler()]))

    with when("the handler name exists but does not support the event version"):
        processed = processor.process(delivery.id)

    with then("the delivery is dead-lettered without retry"):
        assert_that(processed, equal_to(False))
        persisted = repository.get_delivery(delivery.id)
        assert persisted is not None
        assert_that(persisted.status, equal_to(EventDeliveryStatus.DEAD_LETTERED))
        assert_that(persisted.dead_letter_reason, equal_to(EventDeliveryDeadLetterReason.UNSUPPORTED_EVENT))


def test_delivery_processor_classifies_retryable_and_terminal_handler_errors(
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    retry_event = _event(registry, organization_id)
    repository.create(retry_event, registry)
    retry_delivery = next(
        delivery
        for delivery in repository.list_deliveries_for_event(retry_event.event_id)
        if delivery.handler_name == "audit.projection"
    )
    repository.mark_delivery_enqueued(retry_delivery.id)
    retry_processor = EventDeliveryProcessor(
        repository=repository,
        handlers=EventHandlerRegistry([RecordingEventHandler(error=RetryableEventHandlerError("temporary"))]),
    )

    terminal_event = _event(registry, organization_id)
    repository.create(terminal_event, registry)
    terminal_delivery = next(
        delivery
        for delivery in repository.list_deliveries_for_event(terminal_event.event_id)
        if delivery.handler_name == "audit.projection"
    )
    repository.mark_delivery_enqueued(terminal_delivery.id)
    terminal_processor = EventDeliveryProcessor(
        repository=repository,
        handlers=EventHandlerRegistry([RecordingEventHandler(error=TerminalEventHandlerError("terminal"))]),
    )

    with when("handlers raise typed errors"):
        with pytest.raises(RetryableEventHandlerError):
            retry_processor.process(retry_delivery.id)
        terminal_processed = terminal_processor.process(terminal_delivery.id)

    with then("retryable errors stay processing and terminal errors dead-letter"):
        retry_persisted = repository.get_delivery(retry_delivery.id)
        terminal_persisted = repository.get_delivery(terminal_delivery.id)
        assert retry_persisted is not None
        assert terminal_persisted is not None
        assert_that(retry_persisted.status, equal_to(EventDeliveryStatus.PROCESSING))
        assert_that(retry_persisted.last_error, equal_to("temporary"))
        assert_that(terminal_processed, equal_to(False))
        assert_that(terminal_persisted.status, equal_to(EventDeliveryStatus.DEAD_LETTERED))
        assert_that(
            terminal_persisted.dead_letter_reason, equal_to(EventDeliveryDeadLetterReason.TERMINAL_HANDLER_ERROR)
        )


def test_session_aware_stage_commits_business_state_message_and_deliveries_atomically(
    delegate: PostgresRepositoryDelegate,
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
):
    organization = Organization(name="Atomic Commit", description=None)
    organization_id = organization.id
    event = _event(registry, organization_id)

    with when("a domain-specific operation writes business state and stages an event in one session"):
        with Session(delegate.engine) as session:
            session.add(organization)
            session.flush()
            repository.stage(session=session, event=event, registry=registry)
            session.commit()

    with then("business state, Outbox Message, and Event Deliveries commit together"):
        assert_that(_organization_exists(delegate, organization_id), equal_to(True))
        assert_that(repository.get_by_event_id(event.event_id), is_not(none()))
        deliveries = repository.list_deliveries_for_event(event.event_id)
        assert_that(len(deliveries), equal_to(2))


def test_event_validation_failure_rolls_back_business_mutation(
    delegate: PostgresRepositoryDelegate,
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
):
    organization = Organization(name="Validation Rollback", description=None)
    organization_id = organization.id

    with when("a domain-specific operation mutates state before event validation fails"):
        with Session(delegate.engine) as session:
            session.add(organization)
            with pytest.raises(DomainEventValidationError):
                registry.build_event(
                    event_name="agent.sampled",
                    schema_version=1,
                    occurred_at=datetime.now(UTC),
                    organization_id=organization_id,
                    actor=ActorIdentity(type=ActorIdentityType.USER, id=uuid4(), organization_id=organization_id),
                    subject=SubjectIdentity(
                        type=SubjectIdentityType.AGENT,
                        id=uuid4(),
                        organization_id=organization_id,
                    ),
                    correlation_id=uuid4(),
                    payload={"agent_id": str(uuid4()), "organization_id": str(uuid4())},
                )
            session.rollback()

    with then("the business mutation and event state are both absent"):
        assert_that(_organization_exists(delegate, organization_id), equal_to(False))
        assert_that(repository.count(), equal_to(0))
        assert_that(repository.delivery_count(), equal_to(0))


def test_outbox_insert_failure_rolls_back_business_mutation(
    delegate: PostgresRepositoryDelegate,
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    event = _event(registry, organization_id)
    repository.create(event, registry)
    business_mutation = Organization(name="Outbox Insert Rollback", description=None)
    business_mutation_id = business_mutation.id

    with when("a duplicate event_id fails while business state is pending"):
        with pytest.raises(IntegrityError):
            with Session(delegate.engine) as session:
                session.add(business_mutation)
                repository.stage(session=session, event=event, registry=registry)
                session.commit()

    with then("the pending business mutation rolls back with the failed event insert"):
        assert_that(_organization_exists(delegate, business_mutation_id), equal_to(False))
        assert_that(repository.count(), equal_to(1))


def test_duplicate_delivery_constraint_rolls_back_business_mutation(
    delegate: PostgresRepositoryDelegate,
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    event = _event(registry, organization_id)
    message = repository.create(event, registry)
    business_mutation = Organization(name="Delivery Rollback", description=None)
    business_mutation_id = business_mutation.id

    with when("a duplicate Event Delivery fails while business state is pending"):
        with pytest.raises(IntegrityError):
            with Session(delegate.engine) as session:
                session.add(business_mutation)
                session.add(
                    EventDelivery(
                        outbox_message_id=message.id,
                        event_id=event.event_id,
                        organization_id=organization_id,
                        handler_name="audit.projection",
                    )
                )
                session.commit()

    with then("the pending business mutation rolls back with the failed delivery insert"):
        assert_that(_organization_exists(delegate, business_mutation_id), equal_to(False))
        assert_that(len(repository.list_deliveries_for_event(event.event_id)), equal_to(2))


def test_role_change_repository_operation_emits_audit_domain_event(
    delegate: PostgresRepositoryDelegate,
    repository: OutboxMessageRepository,
    organization_id: UUID,
):
    user = User(email="role-change@example.com", hashed_password="hash")
    delegate.save(user)
    membership = OrganizationUser(user_id=user.id, organization_id=organization_id, role=OrganizationRole.MEMBER)
    delegate.save(membership)
    org_user_repository = OrganizationUserRepository(delegate=delegate, outbox_repository=repository)

    with when("a role change is committed through the domain-specific repository operation"):
        changed = org_user_repository.change_role_with_event(
            organization_id=organization_id,
            user_id=user.id,
            new_role=OrganizationRole.ADMIN,
            actor=ActorIdentity(type=ActorIdentityType.USER, id=user.id, organization_id=organization_id),
        )

    with then("the role mutation and audit Domain Event rows commit together"):
        assert changed is not None
        assert_that(changed.membership.role, equal_to(OrganizationRole.ADMIN))
        assert_that(repository.count(), equal_to(1))
        messages = delegate.find_all(OutboxMessage)
        assert_that(messages[0].event_name, equal_to("organization.role.changed"))
        assert_that(messages[0].payload["previous_role"], equal_to("MEMBER"))
        assert_that(messages[0].payload["new_role"], equal_to("ADMIN"))
        deliveries = repository.list_deliveries_for_event(messages[0].event_id)
        assert_that([delivery.handler_name for delivery in deliveries], equal_to(["security_audit.projection"]))
        assert_that(changed.delivery_ids, equal_to([deliveries[0].id]))


def test_outbox_message_rows_are_immutable(
    delegate: PostgresRepositoryDelegate,
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    event = _event(registry, organization_id)
    message = repository.create(event, registry)

    with when("a persisted Outbox Message is updated"):
        with pytest.raises(SQLAlchemyError):
            with delegate.engine.begin() as connection:
                connection.execute(
                    text("UPDATE event_outbox_message SET event_name = 'agent.changed' WHERE id = :id"),
                    {"id": message.id},
                )

    with then("the original event fact remains unchanged"):
        found = repository.get_by_event_id(event.event_id)
        assert found is not None
        assert_that(found.event_name, equal_to("agent.sampled"))
