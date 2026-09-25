from datetime import datetime
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel


class OrganizationAgentSettings(BaseModel, table=True):
    """Organization-scoped defaults applied to the Agents in that Organization.

    One row per Organization, created lazily on first write. Every setting column is
    nullable and NULL means "follow the platform value", so an Organization that has
    never opened Agent Settings needs no row at all. Further settings (default
    approval mode, runtime, platform, tool policy, budgets) are added here as more
    typed nullable columns rather than as a JSON blob, so each keeps its own
    validation and its own change Event.
    """

    __tablename__: str = "organization_agent_settings"

    __table_args__ = (
        sa.UniqueConstraint("organization_id", name="uq_organization_agent_settings_organization_id"),
        sa.CheckConstraint(
            "default_agent_llm_budget_usd IS NULL OR default_agent_llm_budget_usd >= 0",
            name="check_default_agent_llm_budget_non_negative",
        ),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    # Tracks Config.agent_default_model while NULL rather than snapshotting it, so an
    # Organization that never picks a default follows platform model upgrades.
    default_model: str | None = SqlField(default=None, nullable=True)
    # Spend limit (USD) for Agents that set none of their own. NULL follows
    # AGENT_DEFAULT_LLM_BUDGET_USD. Tracked live, not snapshotted: changing it moves
    # every inheriting Agent's limit.
    default_agent_llm_budget_usd: float | None = SqlField(default=None, nullable=True)


DefaultModelSource = Literal["organization", "platform"]

DEFAULT_MODEL_SETTING = "default_model"
DEFAULT_AGENT_LLM_BUDGET_SETTING = "default_agent_llm_budget_usd"


class AgentSettingsRead(PydanticBaseModel):
    # The Organization's own choice; None means it follows the platform default.
    default_model: str | None
    # What the default resolves to right now.
    effective_default_model: str
    default_model_source: DefaultModelSource
    # Agents following the default, and Agents pinning their own model. Counted
    # across the whole Organization: these numbers describe the blast radius of a
    # policy change rather than a list the caller may read.
    inheriting_agent_count: int
    override_agent_count: int
    # The Organization's own default Agent spend limit; None follows the platform's.
    default_agent_llm_budget_usd: float | None = None
    # What an Agent without a limit of its own is held to right now.
    effective_default_agent_llm_budget_usd: float
    # Agents following the default limit, and Agents with a limit of their own.
    budget_inheriting_agent_count: int
    budget_override_agent_count: int
    # Whether the caller may change the default Agent spend limit.
    can_manage_llm_budget: bool = False
    updated_at: datetime | None


class AgentSettingsUpdate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    # An explicit null reverts to following the platform default. Omitting the field
    # leaves the stored value untouched, which is what keeps this DTO usable once
    # further settings are added alongside it.
    default_model: str | None = None
    # Same semantics: an explicit null follows the platform default, omitted leaves it.
    default_agent_llm_budget_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
