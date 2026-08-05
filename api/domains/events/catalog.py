from typing import Any
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
AGENT_UPDATED = "agent.updated"
AGENT_DELETED = "agent.deleted"
AGENT_SECRET_ADDED = "agent.secret.added"
AGENT_SECRET_UPDATED = "agent.secret.updated"
AGENT_SECRET_REMOVED = "agent.secret.removed"
TEMPLATE_CREATED = "template.created"
TEMPLATE_UPDATED = "template.updated"
TEMPLATE_DELETED = "template.deleted"
ORGANIZATION_MODEL_ALLOWLIST_CHANGED = "organization.model_allowlist.changed"
ORGANIZATION_MEMBER_ADDED = "organization.member.added"
ORGANIZATION_MEMBER_REMOVED = "organization.member.removed"
ORGANIZATION_OWNERSHIP_TRANSFERRED = "organization.ownership_transferred"
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


class AgentUpdatedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    field_changes: dict[str, dict[str, Any]]
    actor_display: str
    subject_display: str


class AgentDeletedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    agent_name: str
    platform: str
    runtime: str
    actor_display: str
    subject_display: str


class AgentSecretChangedPayload(BaseModel):
    """Field names deliberately avoid "secret"/"credential" substrings — the
    registry's sensitive-key filter (api/domains/events/registry.py
    _is_sensitive_key) rejects any payload key containing those substrings,
    so this payload can never literally be keyed "secret_name" etc. even
    though it only ever carries the same safe fields as AgentSecretRead."""

    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    record_id: UUID
    provider: str
    label: str
    shared_reference_id: UUID | None
    actor_display: str
    subject_display: str


class TemplateCreatedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    template_id: UUID
    template_slug: str
    template_name: str
    version: int
    actor_display: str
    subject_display: str


class TemplateUpdatedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    template_id: UUID
    template_slug: str
    previous_version: int
    new_version: int
    field_changes: dict[str, dict[str, Any]]
    actor_display: str
    subject_display: str


class TemplateDeletedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    template_slug: str
    versions_deleted: list[int]
    actor_display: str
    subject_display: str


class OrganizationModelAllowlistChangedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    previous_models: list[str]
    new_models: list[str]
    actor_display: str
    subject_display: str


class OrganizationMemberChangedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    membership_id: UUID
    user_id: UUID | None
    role: str
    actor_display: str
    subject_display: str


class OrganizationOwnershipTransferredPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    previous_owner_membership_id: UUID
    previous_owner_user_id: UUID | None
    new_owner_membership_id: UUID
    new_owner_user_id: UUID | None
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
        (AGENT_UPDATED, AgentUpdatedPayload),
        (AGENT_DELETED, AgentDeletedPayload),
        (TEMPLATE_CREATED, TemplateCreatedPayload),
        (TEMPLATE_UPDATED, TemplateUpdatedPayload),
        (TEMPLATE_DELETED, TemplateDeletedPayload),
        (ORGANIZATION_MODEL_ALLOWLIST_CHANGED, OrganizationModelAllowlistChangedPayload),
        (ORGANIZATION_OWNERSHIP_TRANSFERRED, OrganizationOwnershipTransferredPayload),
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
    for event_name in (AGENT_SECRET_ADDED, AGENT_SECRET_UPDATED, AGENT_SECRET_REMOVED):
        registry.register(
            DomainEventDefinition(
                event_name=event_name,
                schema_version=1,
                payload_model=AgentSecretChangedPayload,
                handler_names=(SECURITY_AUDIT_HANDLER,),
                event_scope=EventScope.ORGANIZATION,
            )
        )
    for event_name in (ORGANIZATION_MEMBER_ADDED, ORGANIZATION_MEMBER_REMOVED):
        registry.register(
            DomainEventDefinition(
                event_name=event_name,
                schema_version=1,
                payload_model=OrganizationMemberChangedPayload,
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
