from datetime import UTC, datetime
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
    EventDeliveryStatus,
    SubjectIdentity,
    SubjectIdentityType,
)
from api.domains.events.models import EventDelivery
from api.domains.events.repository import OutboxMessageRepository
from api.domains.organizations.models import Organization
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import then, when


class SamplePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    organization_id: str
    detail: str = "sample"
    nested: dict[str, Any] = Field(default_factory=dict)


@pytest.fixture
def delegate():
    delegate = PostgresRepositoryDelegate(get_config())
    with delegate.engine.begin() as connection:
        connection.execute(text("TRUNCATE event_outbox_message CASCADE"))
        connection.execute(text("DELETE FROM organization"))
    try:
        yield delegate
    finally:
        with delegate.engine.begin() as connection:
            connection.execute(text("TRUNCATE event_outbox_message CASCADE"))
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
        equal_to({"PENDING", "IN_PROGRESS", "SUCCEEDED", "FAILED", "DEAD_LETTER"}),
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
