import enum
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict
from pydantic import Field as PydanticField
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import CheckConstraint, Field
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel


class Organization(BaseModel, table=True):
    __tablename__: str = "organization"

    name: str = Field(nullable=False, min_length=3, max_length=255)
    description: str | None = Field(default=None, nullable=True)
    created_by_user_id: UUID | None = Field(
        default=None,
        foreign_key="user.id",
        nullable=True,
        ondelete="RESTRICT",
        index=True,
    )
    allowed_models: list[str] = Field(default_factory=list, sa_column=sa.Column(JSONB, server_default="[]"))

    # Platform-administered LLM spend ceiling, mirrored onto the Organization's LiteLLM
    # team. NULL means no cap; 0 is a real zero allowance. A float is enough here where
    # cost_record needs NUMERIC: this is a configured ceiling, never a summed figure.
    llm_budget_usd: float | None = Field(default=None, nullable=True)
    # LiteLLM budget window (e.g. "30d"). Only meaningful while a budget is set.
    llm_budget_duration: str | None = Field(default=None, nullable=True, max_length=32)

    # Spend snapshot, refreshed on a schedule. Organization-facing surfaces read this
    # rather than the proxy: a banner on every page load must not put an external
    # service in the critical path. NULL spend means "not yet observed" — never zero.
    llm_spend_usd: float | None = Field(default=None, nullable=True)
    llm_spend_observed_at: datetime | None = SqlField(
        default=None,
        sa_type=sa.DateTime(timezone=True),  # type: ignore
        nullable=True,
    )
    llm_budget_renews_at: datetime | None = SqlField(
        default=None,
        sa_type=sa.DateTime(timezone=True),  # type: ignore
        nullable=True,
    )
    # Highest threshold already alerted for `llm_alert_key`. The key identifies the
    # window *and* the limit, so raising a limit re-arms the thresholds instead of
    # silencing the Organization for the rest of the period.
    llm_alerted_threshold: int | None = Field(default=None, nullable=True)
    llm_alert_key: str | None = Field(default=None, nullable=True, max_length=128)

    __table_args__ = (
        sa.Index("ix_organization_name", "name"),
        CheckConstraint("length(name) >= 3", name="check_name_length_min"),
        CheckConstraint("length(name) <= 255", name="check_name_length_max"),
        CheckConstraint("llm_budget_usd IS NULL OR llm_budget_usd >= 0", name="check_llm_budget_non_negative"),
    )


class OrganizationRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
    name: str
    description: str | None = None
    owner_email: str | None = None
    owner_name: str | None = None
    allowed_models: list[str] = Field(default_factory=list)


class PlatformOrganizationRead(PydanticBaseModel):
    """Dedicated read model for Platform View: adds immutable Creator identity on top
    of what OrganizationRead exposes to Organization members, per the Platform
    Oversight ADR (no reuse of Organization-scoped DTOs)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
    name: str
    description: str | None = None
    owner_user_id: UUID | None = None
    owner_email: str | None = None
    owner_name: str | None = None
    creator_user_id: UUID | None = None
    creator_email: str | None = None
    creator_name: str | None = None
    llm_budget_usd: float | None = None
    llm_budget_duration: str | None = None


class OrganizationBudgetEmailReceipt(BaseModel, table=True):
    """Idempotency record: a recipient has already been emailed for an Event Delivery.

    Same shape and reasoning as the Agent lifecycle receipt — a delivery fans out to
    several recipients, and a retry must only re-notify the ones that failed.
    """

    __tablename__: str = "organization_budget_email_receipt"

    __table_args__ = (
        sa.UniqueConstraint("delivery_id", "recipient_email", name="uq_org_budget_email_receipt_delivery_recipient"),
    )

    delivery_id: UUID = Field(nullable=False, index=True)
    recipient_email: str = Field(nullable=False, max_length=320)


class OrganizationLlmBudgetState(str, enum.Enum):
    NONE = "none"
    OK = "ok"
    WARNING = "warning"
    EXHAUSTED = "exhausted"
    # A limit is set but spend has never been observed. Distinct from OK: we do not
    # know it is fine, we only know we have not looked yet.
    UNKNOWN = "unknown"


class OrganizationLlmBudgetRead(PydanticBaseModel):
    """What an Organization is allowed to know about its own spend limit.

    Requires `cost.read`, so Owners and Admins only — the same audience as the rest
    of the Organization's spend figures.
    """

    state: OrganizationLlmBudgetState
    limit_usd: float | None = None
    spend_usd: float | None = None
    renews_at: datetime | None = None


class AgentLlmEnrollment(str, enum.Enum):
    """Why an Agent is or is not covered by its Organization's team budget."""

    ENROLLED = "enrolled"
    UNENROLLED = "unenrolled"
    # Refused rather than moved — someone may have arranged this deliberately.
    OTHER_TEAM = "other_team"
    # LiteLLM has no record of the key, e.g. it was removed there by hand.
    UNKNOWN_KEY = "unknown_key"
    # The proxy could not be read, or the stored key could not be decrypted.
    UNREADABLE = "unreadable"


class AgentLlmCoverageRead(PydanticBaseModel):
    agent_id: UUID
    agent_name: str
    status: AgentLlmEnrollment


class OrganizationLlmCoverageRead(PydanticBaseModel):
    """Whether this Organization's Agents are actually subject to its team budget.

    Read live from the proxy rather than cached: a key detached by hand would make a
    stored answer claim coverage the Organization does not have.
    """

    total_agents: int
    enrolled_agents: int
    # Only the Agents that are not enrolled — an administrator needs to know which
    # ones a limit would fail to cover, by name.
    uncovered: list[AgentLlmCoverageRead] = PydanticField(default_factory=list)
    newly_enrolled: int = 0
    # Spend LiteLLM has accrued against the limit, and when that window renews.
    # None means the proxy could not be read — never render it as zero spent.
    spend_usd: float | None = None
    renews_at: str | None = None


class OrganizationLlmBudgetUpdate(PydanticBaseModel):
    """Platform-administered spend ceiling. Absent amount means no cap at all."""

    model_config = ConfigDict(extra="forbid")

    budget_usd: float | None = PydanticField(default=None, ge=0, allow_inf_nan=False)
    # LiteLLM duration: a positive integer followed by s/m/h/d. "30d" is a 30-day
    # interval, not a calendar month.
    budget_duration: str | None = PydanticField(default=None, pattern=r"^[1-9][0-9]*[smhd]$")


class OrganizationUpdate(PydanticBaseModel):
    name: str | None = Field(min_length=3, max_length=255, default=None)
    description: str | None = None
    allowed_models: list[str] | None = None


class OrganizationCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=3, max_length=255)
    description: str | None = Field(default=None, nullable=True)


class OrganizationFilter(PydanticBaseModel):
    search: str | None = Field(default=None)


def get_organization_filter(
    search: str | None = Query(default=None),
) -> OrganizationFilter:
    return OrganizationFilter(search=search)
