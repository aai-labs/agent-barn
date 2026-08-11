from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api.domains.events.models import EventScope
from api.domains.events.registry import DomainEventDefinition, DomainEventRegistry

ORGANIZATION_ROLE_CHANGED = "organization.role.changed"
AGENT_ACCESS_GRANTED = "agent.access.granted"
AGENT_ACCESS_REVOKED = "agent.access.revoked"
AGENT_GENERAL_ACCESS_CHANGED = "agent.general_access.changed"
AGENT_CREATED = "agent.created"
AGENT_STARTED = "agent.started"
AGENT_STOPPED = "agent.stopped"
AGENT_TEMPLATE_OVERRIDE_DRAFT_SAVED = "agent.template_override.draft_saved"
AGENT_TEMPLATE_OVERRIDE_PUBLISHED = "agent.template_override.published"
AGENT_TEMPLATE_OVERRIDE_SELECTED = "agent.template_override.selected"
PLATFORM_USER_PRIVILEGE_GRANTED = "platform.user_privilege.granted"
PLATFORM_USER_PRIVILEGE_REVOKED = "platform.user_privilege.revoked"

SECURITY_AUDIT_HANDLER = "security_audit.projection"
AGENT_LIFECYCLE_EMAIL_HANDLER = "agent.lifecycle_email.notification"


class OrganizationRoleChangedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    membership_id: UUID
    user_id: UUID | None
    previous_role: str
    new_role: str
    actor_display: str
    subject_display: str


class AgentAccessGrantedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    membership_id: UUID
    access_role_id: UUID
    actor_display: str
    subject_display: str


class AgentAccessRevokedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    membership_id: UUID
    previous_access_role_id: UUID
    actor_display: str
    subject_display: str


class AgentGeneralAccessChangedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    previous_access_role_id: UUID | None
    new_access_role_id: UUID | None
    actor_display: str
    subject_display: str


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


class AgentTemplateOverrideDraftSavedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    draft_id: UUID
    template_name: str
    created: bool
    actor_display: str
    subject_display: str


class AgentTemplateOverridePublishedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    override_version_id: UUID
    version: int
    template_name: str
    actor_display: str
    subject_display: str


class AgentTemplateOverrideSelectedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    selection_type: str
    selected_id: UUID
    selected_version: int | None
    template_key: str | None
    actor_display: str
    subject_display: str


class PlatformUserPrivilegeChangedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_user_id: UUID
    actor_display: str
    subject_user_id: UUID
    subject_display: str
    reason: str


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
                event_scope=EventScope.ORGANIZATION,
            )
        )
    registry.register(
        DomainEventDefinition(
            event_name=AGENT_CREATED,
            schema_version=1,
            payload_model=AgentCreatedPayload,
            event_scope=EventScope.ORGANIZATION,
        )
    )
    for event_name in (AGENT_STARTED, AGENT_STOPPED):
        registry.register(
            DomainEventDefinition(
                event_name=event_name,
                schema_version=1,
                payload_model=AgentLifecyclePayload,
                handler_names=(AGENT_LIFECYCLE_EMAIL_HANDLER,),
                event_scope=EventScope.ORGANIZATION,
            )
        )
    for event_name, payload_model in (
        (AGENT_TEMPLATE_OVERRIDE_DRAFT_SAVED, AgentTemplateOverrideDraftSavedPayload),
        (AGENT_TEMPLATE_OVERRIDE_PUBLISHED, AgentTemplateOverridePublishedPayload),
        (AGENT_TEMPLATE_OVERRIDE_SELECTED, AgentTemplateOverrideSelectedPayload),
    ):
        registry.register(
            DomainEventDefinition(
                event_name=event_name,
                schema_version=1,
                payload_model=payload_model,
                handler_names=(SECURITY_AUDIT_HANDLER,),
                event_scope=EventScope.ORGANIZATION,
            )
        )
    for event_name in (
        PLATFORM_USER_PRIVILEGE_GRANTED,
        PLATFORM_USER_PRIVILEGE_REVOKED,
    ):
        registry.register(
            DomainEventDefinition(
                event_name=event_name,
                schema_version=1,
                payload_model=PlatformUserPrivilegeChangedPayload,
                handler_names=(SECURITY_AUDIT_HANDLER,),
                event_scope=EventScope.PLATFORM,
            )
        )
    return registry


EVENT_REGISTRY = build_default_event_registry()
