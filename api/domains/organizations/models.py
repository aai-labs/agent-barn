import calendar
import enum
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict
from pydantic import Field as PydanticField
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import CheckConstraint, Field
from sqlmodel import Field as SqlField

from api.core.config import get_config
from api.infrastructure.postgres.models import BaseModel

# The windows LiteLLM snaps to calendar boundaries (next midnight, next Monday, the
# 1st of the month). An Organization's team and every Agent key share one of these,
# so they all renew at the same moment; any other "Nd" renews N days from whenever
# it was set and would drift apart.
LlmBudgetWindow = Literal["1d", "7d", "30d"]
DEFAULT_LLM_BUDGET_WINDOW: LlmBudgetWindow = "30d"


def budget_window_start(renews_at: datetime, window: str) -> datetime:
    """When the budget window that renews at `renews_at` began.

    LiteLLM snaps a 30d window to the 1st of the month, so it spans a calendar
    month rather than 30 days: stepping back a month keeps memory spend aligned
    with the window the team's own spend accrues in. A day that does not exist in
    the earlier month (31 March back to February) clamps to its last day.
    """
    if window == "30d":
        year, month = (renews_at.year, renews_at.month - 1) if renews_at.month > 1 else (renews_at.year - 1, 12)
        last_day = calendar.monthrange(year, month)[1]
        return renews_at.replace(year=year, month=month, day=min(renews_at.day, last_day))
    return renews_at - timedelta(days=int(window.removesuffix("d")))


def _default_llm_ceiling() -> float:
    """Every new Organization starts capped, whichever path creates it."""
    return get_config().organization_default_llm_budget_usd


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

    # Platform-administered LLM spend ceiling. Always set: a new Organization starts at
    # the deployment default, and 0 is a real zero allowance. A float is enough here
    # where cost_record needs NUMERIC: this is a configured ceiling, never a summed
    # figure.
    llm_budget_usd: float = Field(default_factory=_default_llm_ceiling, nullable=False)
    # LiteLLM budget window, shared by the team and every Agent key.
    llm_budget_duration: str = Field(default=DEFAULT_LLM_BUDGET_WINDOW, nullable=False, max_length=32)
    # The Organization's own limit, set by its Owners and Admins. NULL follows the
    # ceiling; never above it (lowering the ceiling pulls this down with it). The
    # proxy enforces `llm_own_budget_usd ?? llm_budget_usd` on the team.
    llm_own_budget_usd: float | None = Field(default=None, nullable=True)

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

    # Memory spend this window, measured by the enforcement pass. Memory runs on
    # Honcho's own LiteLLM key, which is in no team, so the team's spend never
    # includes it; the pass apportions Honcho's total to the Organization's pools.
    # NULL means "not yet measured", never zero.
    llm_memory_spend_usd: float | None = Field(default=None, nullable=True)
    llm_memory_spend_observed_at: datetime | None = SqlField(
        default=None,
        sa_type=sa.DateTime(timezone=True),  # type: ignore
        nullable=True,
    )
    # Set to `llm_budget_window_key` when agents and memory together reached the
    # limit. The Organization's memory stays off while it matches, so a memory
    # figure that dips (apportionment shifts as other pools grow) cannot flap it
    # back on; a renewal or a new limit changes the key and lifts it.
    llm_memory_suspended_key: str | None = Field(default=None, nullable=True, max_length=128)

    __table_args__ = (
        sa.Index("ix_organization_name", "name"),
        CheckConstraint("length(name) >= 3", name="check_name_length_min"),
        CheckConstraint("length(name) <= 255", name="check_name_length_max"),
        CheckConstraint("llm_budget_usd IS NULL OR llm_budget_usd >= 0", name="check_llm_budget_non_negative"),
        CheckConstraint(
            "llm_own_budget_usd IS NULL OR (llm_own_budget_usd >= 0 AND llm_own_budget_usd <= llm_budget_usd)",
            name="check_llm_own_budget_within_ceiling",
        ),
    )

    @property
    def effective_llm_budget_usd(self) -> float:
        """The Organization's limit: its own where it set one, else the ceiling."""
        return self.llm_own_budget_usd if self.llm_own_budget_usd is not None else self.llm_budget_usd

    @property
    def memory_spend_this_window_usd(self) -> float:
        """Memory spend measured in the current window, else 0.

        A figure measured before the window renewed belongs to the last window; it
        must not hold the new one down until the next pass replaces it.
        """
        if self.llm_memory_spend_usd is None or self.llm_memory_spend_observed_at is None:
            return 0.0
        if self.llm_budget_renews_at is None:
            return 0.0
        if self.llm_memory_spend_observed_at < budget_window_start(self.llm_budget_renews_at, self.llm_budget_duration):
            return 0.0
        return self.llm_memory_spend_usd

    @property
    def enforced_llm_budget_usd(self) -> float:
        """The limit the proxy enforces on the Organization's team.

        The team only sees agent spend, so the memory already spent comes off the
        limit instead: the proxy then refuses agents once agents + memory reach it.
        Never shown to anyone — surfaces show the real limit and combined spend.

        Rounded to a millionth of a dollar: the subtraction leaves float noise
        (0.45997120708399997) that never equals what LiteLLM stores and reads back
        (0.459971207084), so an unchanged ceiling would be rewritten on every pass
        and fail the client's verification each time.
        """
        return round(max(0.0, self.effective_llm_budget_usd - self.memory_spend_this_window_usd), 6)

    @property
    def llm_budget_window_key(self) -> str:
        """Identifies the current window and limit, like `llm_alert_key`."""
        renews_at = self.llm_budget_renews_at.isoformat() if self.llm_budget_renews_at else ""
        return f"{renews_at}|{self.effective_llm_budget_usd}"

    @property
    def llm_memory_suspended(self) -> bool:
        return self.llm_memory_suspended_key is not None and self.llm_memory_suspended_key == self.llm_budget_window_key


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
    # The Organization's own limit beneath the ceiling; None when it follows it.
    llm_own_budget_usd: float | None = None


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
    # The limit in force: the Organization's own when it set one, else the ceiling.
    limit_usd: float
    # What the platform allows; the Organization's own limit can only go below it.
    ceiling_usd: float
    # The Organization's own limit, or None when it follows the ceiling.
    own_limit_usd: float | None = None
    window: str
    # Agents and memory together this window — what the limit is measured against.
    spend_usd: float | None = None
    # The memory share of `spend_usd`. Memory runs on its own credential, so the
    # proxy's team figure never includes it; it is added here.
    memory_spend_usd: float | None = None
    renews_at: datetime | None = None
    # Whether the caller may change the Organization's own limit, so the UI shows a
    # control only to the people the API would accept it from.
    can_manage: bool = False


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
    """Platform-administered spend ceiling. Always an amount: an Organization can no
    longer be uncapped, and an administrator who means "unlimited" sets a large one."""

    model_config = ConfigDict(extra="forbid")

    budget_usd: float = PydanticField(ge=0, allow_inf_nan=False)
    # Omitted keeps the current window, so changing only the amount never reschedules
    # the Organization's renewal date.
    budget_duration: LlmBudgetWindow | None = None


class OrganizationOwnLlmBudgetUpdate(PydanticBaseModel):
    """An Organization's own limit. Null follows the platform ceiling."""

    model_config = ConfigDict(extra="forbid")

    budget_usd: float | None = PydanticField(ge=0, allow_inf_nan=False)


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
