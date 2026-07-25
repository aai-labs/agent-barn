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
    SubjectIdentity,
    SubjectIdentityType,
)
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
        )
    )
    return registry


@pytest.fixture
def repository(delegate: PostgresRepositoryDelegate) -> OutboxMessageRepository:
    return OutboxMessageRepository(delegate=delegate)


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
        message = repository.create(event)
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
    repository.create(event)

    with when("the same event is inserted again"):
        with pytest.raises(IntegrityError):
            repository.create(event)

    with then("only the original Outbox Message is visible"):
        assert_that(repository.count(), equal_to(1))


def test_outbox_message_rows_are_immutable(
    delegate: PostgresRepositoryDelegate,
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id: UUID,
):
    event = _event(registry, organization_id)
    message = repository.create(event)

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
