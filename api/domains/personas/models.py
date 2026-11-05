from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel

PERSONA_KEY_MAX_LENGTH = 40
PERSONA_EMOJI_MAX_LENGTH = 16


class AgentPersona(BaseModel, table=True):
    __tablename__: str = "agent_persona"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_persona_agent_organization",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("agent_id", "key", name="uq_agent_persona_agent_key"),
        sa.UniqueConstraint("id", "organization_id", name="uq_agent_persona_id_organization"),
        sa.UniqueConstraint("id", "agent_id", name="uq_agent_persona_id_agent"),
        sa.Index("ix_agent_persona_organization", "organization_id"),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    agent_id: UUID = SqlField(nullable=False)
    key: str = SqlField(nullable=False, max_length=PERSONA_KEY_MAX_LENGTH)
    display_name: str = SqlField(nullable=False, max_length=255)
    emoji: str | None = SqlField(default=None, nullable=True, max_length=PERSONA_EMOJI_MAX_LENGTH)
    current_version: int = SqlField(nullable=False)
    deleted_at: datetime | None = SqlField(
        default=None,
        sa_column=Column(sa.DateTime(timezone=True), nullable=True),
    )


class AgentPersonaVersion(BaseModel, table=True):
    __tablename__: str = "agent_persona_version"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["persona_id", "organization_id"],
            ["agent_persona.id", "agent_persona.organization_id"],
            name="fk_agent_persona_version_persona_organization",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("persona_id", "version", name="uq_agent_persona_version_persona_version"),
        sa.Index("ix_agent_persona_version_organization", "organization_id"),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    persona_id: UUID = SqlField(nullable=False)
    version: int = SqlField(nullable=False)
    soul_md: str = SqlField(nullable=False, sa_type=sa.Text)
    identity_md: str = SqlField(nullable=False, sa_type=sa.Text)
    author_user_id: UUID | None = SqlField(
        default=None,
        foreign_key="user.id",
        nullable=True,
        ondelete="SET NULL",
    )
