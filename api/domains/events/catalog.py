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
AGENT_TEMPLATE_OVERRIDE_DRAFT_SAVED = "agent.template_override.draft_saved"
AGENT_TEMPLATE_OVERRIDE_PUBLISHED = "agent.template_override.published"
AGENT_TEMPLATE_OVERRIDE_SELECTED = "agent.template_override.selected"
AGENT_UPDATED = "agent.updated"
AGENT_DELETED = "agent.deleted"
AGENT_SECRET_ADDED = "agent.secret.added"
AGENT_SECRET_UPDATED = "agent.secret.updated"
AGENT_SECRET_REMOVED = "agent.secret.removed"
TEMPLATE_CREATED = "template.created"
TEMPLATE_UPDATED = "template.updated"
TEMPLATE_DELETED = "template.deleted"
ORGANIZATION_MODEL_ALLOWLIST_CHANGED = "organization.model_allowlist.changed"
ORGANIZATION_AGENT_SETTINGS_CHANGED = "organization.agent_settings.changed"
ORGANIZATION_MEMBER_ADDED = "organization.member.added"
ORGANIZATION_MEMBER_REMOVED = "organization.member.removed"
ORGANIZATION_OWNERSHIP_TRANSFERRED = "organization.ownership_transferred"
PLATFORM_USER_PRIVILEGE_GRANTED = "platform.user_privilege.granted"
PLATFORM_USER_PRIVILEGE_REVOKED = "platform.user_privilege.revoked"
COMMUNICATION_CONNECTION_HEALTH_CHANGED = "communication.connection.health.changed"
COMMUNICATION_CONNECTION_RECONNECT_REQUESTED = "communication.connection.reconnect.requested"
COMMUNICATION_DELIVERY_DEAD_LETTERED = "communication.delivery.dead_lettered"
COMMUNICATION_DELIVERY_RETRY_REQUESTED = "communication.delivery.retry.requested"
COMMUNICATION_DELIVERY_RECOVERED = "communication.delivery.recovered"

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
    """subject_display names the Agent (the event's Subject); member_display is a
    write-time snapshot of the target member's name/email, since membership_id alone
    can't be resolved to a human-readable identity once the membership or user is
    later deleted (records must survive that per the retention ADR).

    previous_access_role_id is set when this event represents a role change for a
    member who already had direct access (None means a brand-new grant) — reusing
    "granted" rather than adding a third event type, since both cases converge on
    the same "member has this access role now" fact."""

    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    membership_id: UUID
    access_role_id: UUID
    previous_access_role_id: UUID | None = None
    actor_display: str
    subject_display: str
    member_display: str


class AgentAccessRevokedPayload(BaseModel):
    """See AgentAccessGrantedPayload — same subject_display/member_display split."""

    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    membership_id: UUID
    previous_access_role_id: UUID
    actor_display: str
    subject_display: str
    member_display: str


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
    runtime: str


class AgentLifecyclePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    agent_name: str
    previous_status: str
    new_status: str
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


class AgentUpdatedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    field_changes: dict[str, dict[str, Any]]
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


class AgentDeletedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    agent_name: str
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
    template_key: str
    template_name: str
    version: int
    actor_display: str
    subject_display: str


class TemplateUpdatedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    template_id: UUID
    template_key: str
    previous_version: int
    new_version: int
    field_changes: dict[str, dict[str, Any]]
    actor_display: str
    subject_display: str


class TemplateDeletedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    template_key: str
    versions_deleted: list[int]
    actor_display: str
    subject_display: str


class OrganizationModelAllowlistChangedPayload(BaseModel):
    """Carries the diff (added/removed), not the full before/after lists — the
    allowlist is validated against the OpenRouter catalog (400+ models) with no
    length bound, so two full lists can exceed MAX_PAYLOAD_BYTES and make the
    allowlist permanently uneditable once it's grown large enough."""

    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    added: list[str]
    removed: list[str]
    actor_display: str
    subject_display: str


class OrganizationAgentSettingsChangedPayload(BaseModel):
    """One changed Agent Setting, named by `setting`, with its before/after values.

    Unlike the allowlist event this can safely carry both values: a setting holds a
    single bounded scalar (a model slug), not an unbounded list, so the payload
    cannot grow into MAX_PAYLOAD_BYTES. `previous`/`current` are None when the
    Organization was, or becomes, one that follows the platform default.
    """

    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    setting: str
    previous: str | None
    current: str | None
    inheriting_agent_count: int
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


class CommunicationConnectionHealthChangedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    connection_id: UUID
    previous_status: str | None
    new_status: str
    error_code: str | None
    error_summary: str | None
    actor_display: str
    subject_display: str


class CommunicationConnectionReconnectRequestedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    connection_id: UUID
    actor_display: str
    subject_display: str


class CommunicationDeliveryDeadLetteredPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    connection_id: UUID
    delivery_id: UUID
    direction: str
    attempt_number: int
    error_code: str | None
    error_summary: str | None
    actor_display: str
    subject_display: str


class CommunicationDeliveryRetryRequestedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    connection_id: UUID
    delivery_id: UUID
    direction: str
    attempt_number: int
    actor_display: str
    subject_display: str


class CommunicationDeliveryRecoveredPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    agent_id: UUID
    connection_id: UUID
    delivery_id: UUID
    direction: str
    attempt_number: int
    actor_display: str
    subject_display: str


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
        (ORGANIZATION_AGENT_SETTINGS_CHANGED, OrganizationAgentSettingsChangedPayload),
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
    for event_name, payload_model in (
        (COMMUNICATION_CONNECTION_HEALTH_CHANGED, CommunicationConnectionHealthChangedPayload),
        (COMMUNICATION_CONNECTION_RECONNECT_REQUESTED, CommunicationConnectionReconnectRequestedPayload),
        (COMMUNICATION_DELIVERY_DEAD_LETTERED, CommunicationDeliveryDeadLetteredPayload),
        (COMMUNICATION_DELIVERY_RETRY_REQUESTED, CommunicationDeliveryRetryRequestedPayload),
        (COMMUNICATION_DELIVERY_RECOVERED, CommunicationDeliveryRecoveredPayload),
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
    return registry


EVENT_REGISTRY = build_default_event_registry()
