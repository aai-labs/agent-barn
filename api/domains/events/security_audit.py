from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, Session, select

from api.domains.events.catalog import (
    AGENT_ACCESS_GRANTED,
    AGENT_ACCESS_REVOKED,
    AGENT_DELETED,
    AGENT_GENERAL_ACCESS_CHANGED,
    AGENT_SECRET_ADDED,
    AGENT_SECRET_REMOVED,
    AGENT_SECRET_UPDATED,
    AGENT_TEMPLATE_OVERRIDE_DRAFT_SAVED,
    AGENT_TEMPLATE_OVERRIDE_PUBLISHED,
    AGENT_TEMPLATE_OVERRIDE_SELECTED,
    AGENT_UPDATED,
    ORGANIZATION_MEMBER_ADDED,
    ORGANIZATION_MEMBER_REMOVED,
    ORGANIZATION_MODEL_ALLOWLIST_CHANGED,
    ORGANIZATION_OWNERSHIP_TRANSFERRED,
    ORGANIZATION_ROLE_CHANGED,
    PLATFORM_USER_PRIVILEGE_GRANTED,
    PLATFORM_USER_PRIVILEGE_REVOKED,
    SECURITY_AUDIT_HANDLER,
    TEMPLATE_CREATED,
    TEMPLATE_DELETED,
    TEMPLATE_UPDATED,
)
from api.domains.events.handlers import EventDeliveryContext, SupportedEvent
from api.domains.events.models import DomainEventEnvelope, EventScope
from api.infrastructure.postgres.models import BaseModel
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


class SecurityAuditRecord(BaseModel, table=True):
    __tablename__: str = "security_audit_record"
    __table_args__ = (
        sa.UniqueConstraint("event_id", name="uq_security_audit_record_event_id"),
        sa.Index("ix_security_audit_record_scope_occurred", "event_scope", "occurred_at"),
        sa.Index("ix_security_audit_record_organization_occurred", "organization_id", "occurred_at"),
        sa.Index("ix_security_audit_record_subject", "subject_type", "subject_id"),
    )

    # Identity references intentionally have no foreign keys. Audit evidence and
    # display snapshots must survive later deletion of product entities.
    event_id: UUID = Field(nullable=False)
    event_scope: EventScope = Field(sa_column=Column(sa.String(32), nullable=False))
    organization_id: UUID | None = Field(default=None, nullable=True)
    action: str = Field(nullable=False, max_length=255)
    occurred_at: datetime = Field(sa_type=sa.DateTime(timezone=True), nullable=False)  # type: ignore
    actor_type: str = Field(nullable=False, max_length=32)
    actor_id: str = Field(nullable=False, max_length=255)
    actor_display: str | None = Field(default=None, nullable=True, max_length=320)
    subject_type: str = Field(nullable=False, max_length=32)
    subject_id: str = Field(nullable=False, max_length=255)
    subject_display: str | None = Field(default=None, nullable=True, max_length=320)
    reason: str | None = Field(default=None, nullable=True, max_length=1000)
    details: dict = Field(sa_column=Column(JSONB, nullable=False))


@inject
@singleton
@dataclass
class SecurityAuditRepository:
    delegate: PostgresRepositoryDelegate

    def get_by_event_id(self, event_id: UUID) -> SecurityAuditRecord | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(SecurityAuditRecord).where(SecurityAuditRecord.event_id == event_id)
            ).one_or_none()

    def save_if_absent(self, record: SecurityAuditRecord) -> SecurityAuditRecord:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            existing = session.exec(
                select(SecurityAuditRecord).where(SecurityAuditRecord.event_id == record.event_id)
            ).one_or_none()
            if existing is not None:
                return existing
            session.add(record)
            session.commit()
            return record


@inject
@dataclass
class SecurityAuditProjection:
    repository: SecurityAuditRepository

    name: ClassVar[str] = SECURITY_AUDIT_HANDLER
    supported_events: ClassVar[Sequence[SupportedEvent]] = (
        SupportedEvent(ORGANIZATION_ROLE_CHANGED, 1),
        SupportedEvent(AGENT_ACCESS_GRANTED, 1),
        SupportedEvent(AGENT_ACCESS_REVOKED, 1),
        SupportedEvent(AGENT_GENERAL_ACCESS_CHANGED, 1),
        SupportedEvent(AGENT_TEMPLATE_OVERRIDE_DRAFT_SAVED, 1),
        SupportedEvent(AGENT_TEMPLATE_OVERRIDE_PUBLISHED, 1),
        SupportedEvent(AGENT_TEMPLATE_OVERRIDE_SELECTED, 1),
        SupportedEvent(PLATFORM_USER_PRIVILEGE_GRANTED, 1),
        SupportedEvent(PLATFORM_USER_PRIVILEGE_REVOKED, 1),
        SupportedEvent(AGENT_UPDATED, 1),
        SupportedEvent(AGENT_DELETED, 1),
        SupportedEvent(AGENT_SECRET_ADDED, 1),
        SupportedEvent(AGENT_SECRET_UPDATED, 1),
        SupportedEvent(AGENT_SECRET_REMOVED, 1),
        SupportedEvent(TEMPLATE_CREATED, 1),
        SupportedEvent(TEMPLATE_UPDATED, 1),
        SupportedEvent(TEMPLATE_DELETED, 1),
        SupportedEvent(ORGANIZATION_MODEL_ALLOWLIST_CHANGED, 1),
        SupportedEvent(ORGANIZATION_MEMBER_ADDED, 1),
        SupportedEvent(ORGANIZATION_MEMBER_REMOVED, 1),
        SupportedEvent(ORGANIZATION_OWNERSHIP_TRANSFERRED, 1),
    )

    def handle(self, event: DomainEventEnvelope, context: EventDeliveryContext) -> None:
        del context
        self.repository.save_if_absent(
            SecurityAuditRecord(
                event_id=event.event_id,
                event_scope=event.event_scope,
                organization_id=event.organization_id,
                action=event.event_name,
                occurred_at=event.occurred_at,
                actor_type=event.actor.type.value,
                actor_id=str(event.actor.id),
                actor_display=event.payload.get("actor_display"),
                subject_type=event.subject.type.value,
                subject_id=str(event.subject.id),
                subject_display=event.payload.get("subject_display"),
                reason=event.payload.get("reason"),
                details=event.payload,
            )
        )
