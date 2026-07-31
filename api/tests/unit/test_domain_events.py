from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict, Field

from api.domains.events import (
    ActorIdentity,
    ActorIdentityType,
    DomainEventDefinition,
    DomainEventRegistry,
    DomainEventValidationError,
    EventScope,
    SubjectIdentity,
    SubjectIdentityType,
    UnsupportedDomainEventError,
)


class SamplePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    organization_id: str
    nested: dict[str, Any] = Field(default_factory=dict)


class AnyPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    value: Any


def _registry(max_payload_bytes: int = 16 * 1024) -> DomainEventRegistry:
    registry = DomainEventRegistry(max_payload_bytes=max_payload_bytes)
    registry.register(
        DomainEventDefinition(
            event_name="agent.sampled",
            schema_version=1,
            payload_model=SamplePayload,
            handler_names=("audit.projection", "activity.projection"),
        )
    )
    registry.register(
        DomainEventDefinition(
            event_name="agent.anything_sampled",
            schema_version=1,
            payload_model=AnyPayload,
        )
    )
    return registry


def _actor(organization_id):
    return ActorIdentity(
        type=ActorIdentityType.USER,
        id=uuid4(),
        organization_id=organization_id,
    )


def _subject(organization_id):
    return SubjectIdentity(
        type=SubjectIdentityType.AGENT,
        id=uuid4(),
        organization_id=organization_id,
    )


def test_build_event_accepts_registered_schema_version_and_returns_envelope():
    organization_id = uuid4()
    event = _registry().build_event(
        event_name="agent.sampled",
        schema_version=1,
        occurred_at=datetime(2026, 7, 25, tzinfo=UTC),
        organization_id=organization_id,
        actor=_actor(organization_id),
        subject=_subject(organization_id),
        correlation_id=uuid4(),
        payload={"agent_id": str(uuid4()), "organization_id": str(organization_id)},
    )

    assert event.event_name == "agent.sampled"
    assert event.schema_version == 1
    assert event.organization_id == organization_id
    assert event.causation_id is None
    assert event.payload["organization_id"] == str(organization_id)


def test_build_platform_event_requires_no_organization_reference():
    event = _registry().build_event(
        event_name="agent.anything_sampled",
        schema_version=1,
        occurred_at=datetime(2026, 7, 31, tzinfo=UTC),
        event_scope=EventScope.PLATFORM,
        organization_id=None,
        actor=ActorIdentity(type=ActorIdentityType.USER, id=uuid4()),
        subject=SubjectIdentity(type=SubjectIdentityType.USER, id=uuid4()),
        correlation_id=uuid4(),
        payload={"value": "platform change"},
    )

    assert event.event_scope == EventScope.PLATFORM
    assert event.organization_id is None


def test_build_platform_event_rejects_organization_identity():
    organization_id = uuid4()

    with pytest.raises(DomainEventValidationError, match="cannot reference"):
        _registry().build_event(
            event_name="agent.anything_sampled",
            schema_version=1,
            occurred_at=datetime(2026, 7, 31, tzinfo=UTC),
            event_scope=EventScope.PLATFORM,
            organization_id=organization_id,
            actor=ActorIdentity(type=ActorIdentityType.USER, id=uuid4()),
            subject=SubjectIdentity(type=SubjectIdentityType.USER, id=uuid4()),
            correlation_id=uuid4(),
            payload={"value": "platform change"},
        )


def test_build_organization_event_rejects_missing_organization():
    with pytest.raises(DomainEventValidationError, match="require an Organization"):
        _registry().build_event(
            event_name="agent.anything_sampled",
            schema_version=1,
            occurred_at=datetime(2026, 7, 31, tzinfo=UTC),
            event_scope=EventScope.ORGANIZATION,
            organization_id=None,
            actor=ActorIdentity(type=ActorIdentityType.USER, id=uuid4()),
            subject=SubjectIdentity(type=SubjectIdentityType.USER, id=uuid4()),
            correlation_id=uuid4(),
            payload={"value": "organization change"},
        )


def test_registry_returns_handler_names_for_registered_event():
    assert _registry().handler_names_for("agent.sampled", 1) == ("audit.projection", "activity.projection")


def test_build_event_rejects_unsupported_schema_version():
    organization_id = uuid4()

    with pytest.raises(UnsupportedDomainEventError):
        _registry().build_event(
            event_name="agent.sampled",
            schema_version=2,
            occurred_at=datetime.now(UTC),
            organization_id=organization_id,
            actor=_actor(organization_id),
            subject=_subject(organization_id),
            correlation_id=uuid4(),
            payload={"agent_id": str(uuid4()), "organization_id": str(organization_id)},
        )


def test_build_event_rejects_non_object_top_level_payload():
    organization_id = uuid4()

    non_object_payload = cast(dict[str, Any], [])

    with pytest.raises(DomainEventValidationError, match="JSON object"):
        _registry().build_event(
            event_name="agent.sampled",
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=organization_id,
            actor=_actor(organization_id),
            subject=_subject(organization_id),
            correlation_id=uuid4(),
            payload=non_object_payload,
        )


def test_build_event_rejects_secret_like_payload_keys():
    organization_id = uuid4()

    with pytest.raises(DomainEventValidationError, match="sensitive key"):
        _registry().build_event(
            event_name="agent.sampled",
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=organization_id,
            actor=_actor(organization_id),
            subject=_subject(organization_id),
            correlation_id=uuid4(),
            payload={
                "agent_id": str(uuid4()),
                "organization_id": str(organization_id),
                "nested": {"api_token": "should-not-persist"},
            },
        )


def test_build_event_rejects_unsupported_payload_values():
    organization_id = uuid4()

    with pytest.raises(DomainEventValidationError, match="Unsupported payload value"):
        _registry().build_event(
            event_name="agent.anything_sampled",
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=organization_id,
            actor=_actor(organization_id),
            subject=_subject(organization_id),
            correlation_id=uuid4(),
            payload={"value": object()},
        )


def test_build_event_rejects_oversized_payload():
    organization_id = uuid4()

    with pytest.raises(DomainEventValidationError, match="maximum size"):
        _registry(max_payload_bytes=80).build_event(
            event_name="agent.sampled",
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=organization_id,
            actor=_actor(organization_id),
            subject=_subject(organization_id),
            correlation_id=uuid4(),
            payload={"agent_id": str(uuid4()), "organization_id": str(organization_id)},
        )


def test_build_event_rejects_actor_from_different_organization():
    organization_id = uuid4()

    with pytest.raises(DomainEventValidationError, match="actor belongs"):
        _registry().build_event(
            event_name="agent.sampled",
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=organization_id,
            actor=_actor(uuid4()),
            subject=_subject(organization_id),
            correlation_id=uuid4(),
            payload={"agent_id": str(uuid4()), "organization_id": str(organization_id)},
        )


def test_build_event_rejects_subject_from_different_organization():
    organization_id = uuid4()

    with pytest.raises(DomainEventValidationError, match="subject belongs"):
        _registry().build_event(
            event_name="agent.sampled",
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=organization_id,
            actor=_actor(organization_id),
            subject=_subject(uuid4()),
            correlation_id=uuid4(),
            payload={"agent_id": str(uuid4()), "organization_id": str(organization_id)},
        )


def test_build_event_rejects_payload_reference_from_different_organization():
    organization_id = uuid4()

    with pytest.raises(DomainEventValidationError, match="different Organization"):
        _registry().build_event(
            event_name="agent.sampled",
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=organization_id,
            actor=_actor(organization_id),
            subject=_subject(organization_id),
            correlation_id=uuid4(),
            payload={"agent_id": str(uuid4()), "organization_id": str(uuid4())},
        )


def test_build_event_rejects_payload_missing_tenant_metadata():
    organization_id = uuid4()

    with pytest.raises(DomainEventValidationError):
        _registry().build_event(
            event_name="agent.sampled",
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=organization_id,
            actor=_actor(organization_id),
            subject=_subject(organization_id),
            correlation_id=uuid4(),
            payload={"agent_id": str(uuid4())},
        )


def test_build_event_requires_schema_fields():
    organization_id = uuid4()

    with pytest.raises(DomainEventValidationError):
        _registry().build_event(
            event_name="agent.sampled",
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=organization_id,
            actor=_actor(organization_id),
            subject=_subject(organization_id),
            correlation_id=uuid4(),
            payload={"organization_id": str(organization_id)},
        )


def test_register_rejects_duplicate_event_definition():
    registry = _registry()

    with pytest.raises(DomainEventValidationError, match="already registered"):
        registry.register(
            DomainEventDefinition(
                event_name="agent.sampled",
                schema_version=1,
                payload_model=SamplePayload,
            )
        )
