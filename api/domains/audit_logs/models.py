from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, Index

from api.infrastructure.postgres.models import BaseModel


class TargetType(StrEnum):
    """The kind of entity an audited action acted on. Stored as a plain string in
    ``target_type``; kept as an enum only for consistent authoring at call sites."""

    AGENT = "agent"
    ORGANIZATION = "organization"
    MEMBER = "member"
    USER = "user"
    TEMPLATE = "template"
    SKILL = "skill"
    INTEGRATION = "integration"
    AUDIT_LOG = "audit_log"


class AuditAction(StrEnum):
    """The catalog of known user actions. This is the single source of truth for the
    action set — the DB column is a plain varchar (no PG enum) so adding a member here
    never requires a migration, honoring the ticket's "the action set can grow" goal.
    ``AuditLogService.record`` also accepts a raw ``str`` so a one-off action is never
    blocked, but prefer adding a member here."""

    # Agents
    AGENT_CREATE = "agent.create"
    AGENT_UPDATE = "agent.update"
    AGENT_START = "agent.start"
    AGENT_STOP = "agent.stop"
    AGENT_DELETE = "agent.delete"
    # Agent reads
    AGENT_VIEW = "agent.view"
    AGENT_LOGS_VIEW = "agent.logs_view"
    AGENT_CONVERSATIONS_VIEW = "agent.conversations_view"
    AGENT_TOOL_CALLS_VIEW = "agent.tool_calls_view"

    # Organizations
    ORG_CREATE = "org.create"
    ORG_UPDATE = "org.update"
    ORG_DELETE = "org.delete"

    # Members
    MEMBER_ADD = "member.add"
    MEMBER_ROLE_CHANGE = "member.role_change"
    MEMBER_REMOVE = "member.remove"
    MEMBER_OWNERSHIP_TRANSFER = "member.ownership_transfer"
    MEMBER_INVITE_RESEND = "member.invite_resend"

    # Templates
    TEMPLATE_CREATE = "template.create"
    TEMPLATE_UPDATE = "template.update"

    # Skills
    SKILL_CREATE = "skill.create"
    SKILL_UPDATE = "skill.update"
    SKILL_DELETE = "skill.delete"

    # Users (superuser admin; global — NULL org)
    USER_CREATE = "user.create"
    USER_PASSWORD_RESET = "user.password_reset"
    USER_DELETE = "user.delete"

    # Auth (global — NULL org)
    AUTH_LOGIN = "auth.login"
    AUTH_LOGIN_FAILED = "auth.login_failed"
    AUTH_LOGOUT = "auth.logout"
    AUTH_PASSWORD_CHANGE = "auth.password_change"
    AUTH_PASSWORD_RESET_REQUEST = "auth.password_reset_request"
    AUTH_PASSWORD_RESET = "auth.password_reset"
    AUTH_SET_PASSWORD = "auth.set_password"
    AUTH_SLACK_CONFIG_TOKEN_SAVE = "auth.slack_config_token_save"
    AUTH_SLACK_CONFIG_TOKEN_DELETE = "auth.slack_config_token_delete"

    # Integrations
    INTEGRATION_SLACK_APP_CREATE = "integration.slack_app_create"

    # Cost
    COST_VIEW = "cost.view"

    # Audit log itself
    AUDIT_LOG_VIEW = "audit_log.view"
    AUDIT_LOG_EXPORT = "audit_log.export"


# Actions that are "significant reads" — subject to in-memory dedup suppression in the
# service so React Query refetches don't flood the log. Everything else is a mutation and
# is always written.
READ_ACTIONS: frozenset[AuditAction] = frozenset(
    {
        AuditAction.AGENT_VIEW,
        AuditAction.AGENT_LOGS_VIEW,
        AuditAction.AGENT_CONVERSATIONS_VIEW,
        AuditAction.AGENT_TOOL_CALLS_VIEW,
        AuditAction.COST_VIEW,
        AuditAction.AUDIT_LOG_VIEW,
    }
)


class AuditLog(BaseModel, table=True):
    """An append-only record of a single user action.

    Deliberately carries no foreign keys: the log is a historical record that must
    outlive the user or org it references. ``actor_email``/``actor_name`` are snapshots so
    a row stays readable after the actor is deleted. ``organization_id`` is nullable —
    NULL denotes a global action (auth flows, superuser user-admin) that belongs to no
    single org and is visible only in the superuser view.
    """

    __tablename__: str = "audit_log"

    organization_id: UUID | None = Field(default=None, nullable=True)
    actor_user_id: UUID | None = Field(default=None, nullable=True)
    actor_email: str | None = Field(default=None, nullable=True)
    actor_name: str | None = Field(default=None, nullable=True)
    is_superuser_actor: bool = Field(default=False, nullable=False)
    action: str = Field(nullable=False, max_length=100)
    target_type: str | None = Field(default=None, nullable=True, max_length=50)
    target_id: UUID | None = Field(default=None, nullable=True)
    target_label: str | None = Field(default=None, nullable=True)
    changed_fields: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )

    __table_args__ = (
        Index("ix_audit_log_org_created", "organization_id", "created_at"),
        Index("ix_audit_log_created", "created_at"),
        Index("ix_audit_log_actor", "actor_user_id"),
        Index("ix_audit_log_action", "action"),
        Index("ix_audit_log_target", "target_type", "target_id"),
    )


class AuditLogRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    organization_id: UUID | None = None
    organization_name: str | None = None
    actor_user_id: UUID | None = None
    actor_email: str | None = None
    actor_name: str | None = None
    is_superuser_actor: bool = False
    action: str
    target_type: str | None = None
    target_id: UUID | None = None
    target_label: str | None = None
    changed_fields: dict[str, Any] | None = None


class AuditLogFilter(PydanticBaseModel):
    actor_user_id: UUID | None = None
    search: str | None = None
    action: str | None = None
    target_type: str | None = None
    target_id: UUID | None = None
    start_date: str | None = None
    end_date: str | None = None
    # Superuser-only. Ignored (overridden to the caller's own org) for non-superusers.
    organization_id: UUID | None = None
    scope: Literal["org", "all"] = "org"


def get_audit_log_filter(
    actor_user_id: UUID | None = Query(default=None),
    search: str | None = Query(default=None),
    action: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    target_id: UUID | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    organization_id: UUID | None = Query(default=None),
    scope: Literal["org", "all"] = Query(default="org"),
) -> AuditLogFilter:
    return AuditLogFilter(
        actor_user_id=actor_user_id,
        search=search,
        action=action,
        target_type=target_type,
        target_id=target_id,
        start_date=start_date,
        end_date=end_date,
        organization_id=organization_id,
        scope=scope,
    )
