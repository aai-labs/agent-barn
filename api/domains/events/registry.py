import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError

from api.domains.events.constants import SENSITIVE_TOKEN_PARTS
from api.domains.events.models import (
    ActorIdentity,
    ActorIdentityType,
    DomainEventEnvelope,
    EventPayload,
    EventScope,
    SubjectIdentity,
    SubjectIdentityType,
)

MAX_PAYLOAD_BYTES = 16 * 1024


class DomainEventValidationError(ValueError):
    pass


class UnsupportedDomainEventError(DomainEventValidationError):
    pass


@dataclass(frozen=True)
class DomainEventDefinition:
    event_name: str
    schema_version: int
    payload_model: type[BaseModel]
    handler_names: tuple[str, ...] = ()
    event_scope: EventScope | None = None

    def __post_init__(self) -> None:
        if not self.event_name:
            raise DomainEventValidationError("event_name is required")
        if self.schema_version < 1:
            raise DomainEventValidationError("schema_version must be at least 1")
        if len(set(self.handler_names)) != len(self.handler_names):
            raise DomainEventValidationError("handler_names must be unique")
        for handler_name in self.handler_names:
            if not handler_name:
                raise DomainEventValidationError("handler_names cannot contain empty values")


class DomainEventRegistry:
    def __init__(self, max_payload_bytes: int = MAX_PAYLOAD_BYTES):
        self._definitions: dict[tuple[str, int], DomainEventDefinition] = {}
        self._max_payload_bytes = max_payload_bytes

    def register(self, definition: DomainEventDefinition) -> None:
        key = (definition.event_name, definition.schema_version)
        if key in self._definitions:
            raise DomainEventValidationError(
                f"Domain Event {definition.event_name} v{definition.schema_version} is already registered"
            )
        self._definitions[key] = definition

    def get(self, event_name: str, schema_version: int) -> DomainEventDefinition:
        definition = self._definitions.get((event_name, schema_version))
        if definition is None:
            raise UnsupportedDomainEventError(f"Unsupported Domain Event {event_name} v{schema_version}")
        return definition

    def handler_names_for(self, event_name: str, schema_version: int) -> tuple[str, ...]:
        return self.get(event_name, schema_version).handler_names

    def list_definitions(self) -> tuple[DomainEventDefinition, ...]:
        return tuple(self._definitions.values())

    def build_event(
        self,
        *,
        event_name: str,
        schema_version: int,
        occurred_at: datetime,
        organization_id: UUID | None,
        actor: ActorIdentity,
        subject: SubjectIdentity,
        correlation_id: UUID,
        payload: EventPayload,
        causation_id: UUID | None = None,
        event_scope: EventScope | None = None,
    ) -> DomainEventEnvelope:
        definition = self.get(event_name, schema_version)
        resolved_scope = definition.event_scope or event_scope or EventScope.ORGANIZATION
        if definition.event_scope is not None and event_scope is not None and event_scope != definition.event_scope:
            raise DomainEventValidationError(f"Domain Event {event_name} is {definition.event_scope.value}-scoped")
        self._validate_scope(resolved_scope, organization_id)
        self._validate_identity_organization("actor", actor, organization_id, resolved_scope)
        self._validate_identity_organization("subject", subject, organization_id, resolved_scope)
        safe_payload = self._validate_payload(definition, payload, resolved_scope, organization_id)
        return DomainEventEnvelope(
            event_name=event_name,
            schema_version=schema_version,
            occurred_at=occurred_at,
            event_scope=resolved_scope,
            organization_id=organization_id,
            actor=actor,
            subject=subject,
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload=safe_payload,
        )

    def _validate_payload(
        self,
        definition: DomainEventDefinition,
        payload: EventPayload,
        event_scope: EventScope,
        organization_id: UUID | None,
    ) -> EventPayload:
        if not isinstance(payload, dict):
            raise DomainEventValidationError("Event Payload must be a JSON object")
        try:
            parsed_payload = definition.payload_model.model_validate(payload)
        except ValidationError as exc:
            raise DomainEventValidationError(str(exc)) from exc

        try:
            payload_data = parsed_payload.model_dump(mode="json")
        except (PydanticSerializationError, ValueError) as exc:
            raise DomainEventValidationError("Unsupported payload value") from exc
        if not isinstance(payload_data, dict):
            raise DomainEventValidationError("Event Payload schema must serialize to a JSON object")

        self._validate_json_value(payload_data, path="payload")
        self._validate_payload_organization(payload_data, event_scope, organization_id)
        encoded = json.dumps(payload_data, separators=(",", ":"), sort_keys=True)
        if len(encoded.encode("utf-8")) > self._max_payload_bytes:
            raise DomainEventValidationError("Event Payload exceeds maximum size")
        return payload_data

    def _validate_json_value(self, value: Any, *, path: str) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if not isinstance(key, str):
                    raise DomainEventValidationError(f"Unsupported non-string payload key at {path}")
                if _is_sensitive_key(key):
                    raise DomainEventValidationError(f"Event Payload contains sensitive key at {path}.{key}")
                self._validate_json_value(nested, path=f"{path}.{key}")
            return
        if isinstance(value, list):
            for index, nested in enumerate(value):
                self._validate_json_value(nested, path=f"{path}[{index}]")
            return
        if isinstance(value, str | bool) or value is None:
            return
        if isinstance(value, int):
            return
        if isinstance(value, float):
            if math.isfinite(value):
                return
            raise DomainEventValidationError(f"Unsupported non-finite payload number at {path}")
        raise DomainEventValidationError(f"Unsupported payload value at {path}")

    @staticmethod
    def _validate_identity_organization(
        identity_name: str,
        identity: ActorIdentity | SubjectIdentity,
        organization_id: UUID | None,
        event_scope: EventScope,
    ) -> None:
        if event_scope == EventScope.PLATFORM:
            if identity.organization_id is not None:
                raise DomainEventValidationError(f"Platform Event {identity_name} cannot reference an Organization")
            if identity_name == "actor" and identity.type == ActorIdentityType.MEMBERSHIP:
                raise DomainEventValidationError("Platform Event actor cannot be an Organization Membership")
            if identity_name == "subject" and identity.type not in {
                SubjectIdentityType.USER,
                SubjectIdentityType.SYSTEM,
            }:
                raise DomainEventValidationError("Platform Event subject cannot reference an Organization resource")
            return
        if identity.organization_id is not None and identity.organization_id != organization_id:
            raise DomainEventValidationError(f"{identity_name} belongs to a different Organization")

    @staticmethod
    def _validate_scope(event_scope: EventScope, organization_id: UUID | None) -> None:
        if event_scope == EventScope.ORGANIZATION and organization_id is None:
            raise DomainEventValidationError("Organization-scoped events require an Organization")
        if event_scope == EventScope.PLATFORM and organization_id is not None:
            raise DomainEventValidationError("Platform-scoped events cannot reference an Organization")

    @staticmethod
    def _validate_payload_organization(
        payload: EventPayload,
        event_scope: EventScope,
        organization_id: UUID | None,
    ) -> None:
        for path, value in _walk_dicts(payload):
            ref_org = value.get("organization_id")
            if ref_org is not None and event_scope == EventScope.PLATFORM:
                raise DomainEventValidationError(
                    f"Platform Event Payload reference at {path} cannot contain an Organization"
                )
            if ref_org is not None and str(ref_org) != str(organization_id):
                raise DomainEventValidationError(f"Payload reference at {path} belongs to a different Organization")


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_TOKEN_PARTS)


def _walk_dicts(value: Any, *, path: str = "payload"):
    if isinstance(value, dict):
        yield path, value
        for key, nested in value.items():
            yield from _walk_dicts(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _walk_dicts(nested, path=f"{path}[{index}]")
