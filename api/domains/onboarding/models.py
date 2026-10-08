"""Trial onboarding: the platform's trial settings and what the onboarding flow reads."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Field as SqlField
from sqlmodel import SQLModel

TRIAL_SETTINGS_SUBJECT_DISPLAY = "Trial settings"
# Bounds no real trial reaches; they only stop a typo from granting a fortune.
MAX_TRIAL_CREDIT_USD = 10_000.0
MAX_TRIAL_AGENT_LIMIT = 50
DEFAULT_TRIAL_AGENT_LIMIT = 1


class PlatformTrialSettings(SQLModel, table=True):
    """The one row of trial settings, created on first save. Without a row, the
    deployment default applies."""

    __tablename__: str = "platform_trial_settings"
    __table_args__ = (
        sa.CheckConstraint("id = 1", name="ck_platform_trial_settings_singleton"),
        sa.CheckConstraint("credit_usd >= 0", name="ck_platform_trial_settings_credit_non_negative"),
        sa.CheckConstraint("agent_limit >= 1", name="ck_platform_trial_settings_agent_limit_positive"),
    )
    id: int = SqlField(default=1, primary_key=True)
    credit_usd: float
    # How many Agents a Trial Organization may run, checked whenever one is hired.
    agent_limit: int = SqlField(default=DEFAULT_TRIAL_AGENT_LIMIT, sa_column_kwargs={"server_default": "1"})
    updated_at: datetime = SqlField(sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False))
    updated_by: UUID | None = SqlField(default=None, foreign_key="user.id", ondelete="SET NULL")


class TrialGrant(SQLModel, table=True):
    """An email address that has had a trial. Kept as a hash, and kept when the account
    is deleted, so signing up again with the same address grants no second trial."""

    __tablename__: str = "trial_grant"
    # SHA-256 hex of the address, lowercased.
    email_hash: str = SqlField(primary_key=True, max_length=64)
    created_at: datetime = SqlField(sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False))


class TrialSettingsRead(BaseModel):
    credit_usd: float
    agent_limit: int = DEFAULT_TRIAL_AGENT_LIMIT
    # None until the first save.
    updated_at: datetime | None = None


class TrialSettingsUpdate(BaseModel):
    """Omitting a setting leaves it as it is."""

    model_config = ConfigDict(extra="forbid")
    credit_usd: float | None = Field(default=None, ge=0, le=MAX_TRIAL_CREDIT_USD, allow_inf_nan=False)
    agent_limit: int | None = Field(default=None, ge=1, le=MAX_TRIAL_AGENT_LIMIT)


class OnboardingRead(BaseModel):
    """Where the signed-in user stands in trial onboarding.

    `required` is false for anyone without a trial Organization of their own, and for
    everyone who already finished; the UI sends them straight to the dashboard.
    """

    required: bool
    completed_at: datetime | None = None
    organization_id: UUID | None = None
    credit_usd: float | None = None
    agent_id: UUID | None = None
    agent_name: str | None = None
    # The Agent's lifecycle status, as the Agents API reports it.
    agent_status: str | None = None
    connection_id: UUID | None = None
    # The shared bot the user chats with their Agent through.
    telegram_bot_username: str | None = None
