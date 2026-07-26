from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api.domains.events.registry import DomainEventDefinition, DomainEventRegistry

ORGANIZATION_ROLE_CHANGED = "organization.role.changed"
AGENT_ACCESS_GRANTED = "agent.access.granted"
AGENT_ACCESS_REVOKED = "agent.access.revoked"
AGENT_GENERAL_ACCESS_CHANGED = "agent.general_access.changed"
AGENT_CREATED = "agent.created"
AGENT_STARTED = "agent.started"
AGENT_STOPPED = "agent.stopped"

SECURITY_AUDIT_HANDLER = "security_audit.projection"
AGENT_LIFECYCLE_EMAIL_HANDLER = "agent.lifecycle_email.notification"


class OrganizationRoleChangedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    membership_id: UUID
    user_id: UUID | None
    previous_role: str
    new_role: str


class AgentAccessGrantedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    membership_id: UUID
    access_role_id: UUID


class AgentAccessRevokedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    membership_id: UUID
    previous_access_role_id: UUID


class AgentGeneralAccessChangedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    previous_access_role_id: UUID | None
    new_access_role_id: UUID | None


class AgentCreatedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    agent_name: str
    created_by_user_id: UUID | None
    platform: str
    runtime: str


class AgentLifecyclePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    agent_name: str
    previous_status: str
    new_status: str
    platform: str
    runtime: str


def build_default_event_registry() -> DomainEventRegistry:
    registry = DomainEventRegistry()
    for event_name, payload_model in (
        (ORGANIZATION_ROLE_CHANGED, OrganizationRoleChangedPayload),
        (AGENT_ACCESS_GRANTED, AgentAccessGrantedPayload),
        (AGENT_ACCESS_REVOKED, AgentAccessRevokedPayload),
        (AGENT_GENERAL_ACCESS_CHANGED, AgentGeneralAccessChangedPayload),
    ):
        registry.register(
            DomainEventDefinition(
                event_name=event_name,
                schema_version=1,
                payload_model=payload_model,
                handler_names=(SECURITY_AUDIT_HANDLER,),
            )
        )
    registry.register(
        DomainEventDefinition(
            event_name=AGENT_CREATED,
            schema_version=1,
            payload_model=AgentCreatedPayload,
        )
    )
    for event_name in (AGENT_STARTED, AGENT_STOPPED):
        registry.register(
            DomainEventDefinition(
                event_name=event_name,
                schema_version=1,
                payload_model=AgentLifecyclePayload,
                handler_names=(AGENT_LIFECYCLE_EMAIL_HANDLER,),
            )
        )
    return registry


EVENT_REGISTRY = build_default_event_registry()
