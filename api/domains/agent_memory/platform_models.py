"""Platform-owned memory processing configuration, independent of Organizations."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Field as SqlField
from sqlmodel import SQLModel


class PlatformMemorySettings(SQLModel, table=True):
    __tablename__: str = "platform_memory_settings"
    __table_args__ = (sa.CheckConstraint("id = 1", name="ck_platform_memory_settings_singleton"),)
    id: int = SqlField(default=1, primary_key=True)
    model: str
    updated_at: datetime = SqlField(sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False))
    updated_by: UUID | None = SqlField(default=None, foreign_key="user.id", ondelete="SET NULL")


class PlatformMemorySettingsRead(BaseModel):
    model: str
    updated_at: datetime | None = None


class PlatformMemorySettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=200, pattern=r"^openrouter/[A-Za-z0-9._:/-]+$")
