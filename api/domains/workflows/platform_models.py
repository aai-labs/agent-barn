"""Installation-wide authoring policy, independent of Organization membership."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlmodel import Field, SQLModel


class PlatformWorkflowSettings(SQLModel, table=True):
    __tablename__: str = "platform_workflow_settings"
    __table_args__ = (sa.CheckConstraint("id = 1", name="ck_platform_workflow_settings_singleton"),)
    id: int = Field(default=1, primary_key=True)
    authoring_enabled: bool
    updated_at: datetime = Field(sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False))
    updated_by: UUID | None = Field(default=None, foreign_key="user.id", ondelete="SET NULL")


class PlatformWorkflowSettingsRead(BaseModel):
    authoring_enabled: bool
    updated_at: datetime | None = None


class PlatformWorkflowSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authoring_enabled: StrictBool
