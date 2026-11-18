"""The Platform-wide decision model, chosen by Platform Administrators."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Field as SqlField
from sqlmodel import SQLModel


class PlatformDecisionSettings(SQLModel, table=True):
    __tablename__: str = "platform_decision_settings"
    __table_args__ = (sa.CheckConstraint("id = 1", name="ck_platform_decision_settings_singleton"),)
    id: int = SqlField(default=1, primary_key=True)
    # A name from DECISION_MODELS, not a slug: a version bump then needs no data change.
    model: str
    updated_at: datetime = SqlField(sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False))
    updated_by: UUID | None = SqlField(default=None, foreign_key="user.id", ondelete="SET NULL")


class PlatformDecisionSettingsRead(BaseModel):
    model: str
    updated_at: datetime | None = None


class PlatformDecisionSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(max_length=100)
