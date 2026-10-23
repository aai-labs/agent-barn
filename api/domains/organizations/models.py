import enum
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, model_validator
from pydantic import Field as PydanticField
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import CheckConstraint, Field, SQLModel
from sqlmodel import Field as SqlField

from api.core.config import get_config
from api.infrastructure.litellm.client import ONE_OFF_BUDGET_WINDOW
from api.infrastructure.postgres.models import BaseModel

# The windows LiteLLM snaps to calendar boundaries (next midnight, next Monday, the
# 1st of the month). An Organization's team and every Agent key share one of these,
# so they all renew at the same moment; any other "Nd" renews N days from whenever
# it was set and would drift apart.
LlmBudgetWindow = Literal["1d", "7d", "30d"]
DEFAULT_LLM_BUDGET_WINDOW: LlmBudgetWindow = "30d"


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
    # Created by self-signup. A trial runs one Agent on a one-off spend limit until a
    # Platform Administrator ends the trial.
    is_trial: bool = Field(default=False, nullable=False, sa_column_kwargs={"server_default": "false"})
    # When a trial ran out of credit. An expired trial is still a trial — it keeps its
    # Agents and can still buy credit — but no longer counts toward the cap on active
    # trials.
    trial_expired_at: datetime | None = SqlField(
        default=None,
        sa_type=sa.DateTime(timezone=True),  # type: ignore
        nullable=True,
    )
    # How many Agents it may run, set by a Platform Administrator. NULL follows the
    # default: the trial setting for a trial, the deployment's for any other.
    agent_limit: int | None = Field(default=None, nullable=True)

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

    __table_args__ = (
        sa.Index("ix_organization_name", "name"),
        CheckConstraint("length(name) >= 3", name="check_name_length_min"),
        CheckConstraint("length(name) <= 255", name="check_name_length_max"),
        CheckConstraint("llm_budget_usd IS NULL OR llm_budget_usd >= 0", name="check_llm_budget_non_negative"),
        CheckConstraint("agent_limit IS NULL OR agent_limit >= 0", name="check_agent_limit_non_negative"),
        CheckConstraint(
            "llm_own_budget_usd IS NULL OR (llm_own_budget_usd >= 0 AND llm_own_budget_usd <= llm_budget_usd)",
            name="check_llm_own_budget_within_ceiling",
        ),
    )

    @property
    def runs_on_credit(self) -> bool:
        """A one-off limit is credit: everything granted, spent down and never renewed."""
        return self.llm_budget_duration == ONE_OFF_BUDGET_WINDOW

    @property
    def own_llm_budget_in_force_usd(self) -> float | None:
        """The Organization's own limit, unless it runs on credit. There it would be a
        lifetime cap that no top-up could lift, so the balance is the only limit; a
        value left from before is kept but not applied."""
        return None if self.runs_on_credit else self.llm_own_budget_usd

    @property
    def effective_llm_budget_usd(self) -> float:
        """The limit the proxy enforces on the Organization's team."""
        own = self.own_llm_budget_in_force_usd
        return own if own is not None else self.llm_budget_usd


class CreditGrantKind(str, enum.Enum):
    TRIAL = "trial"
    PURCHASE = "purchase"
    REFUND = "refund"
    CHARGEBACK = "chargeback"
    # A platform administrator setting the ceiling of an Organization on credit; also
    # the opening balance of one that was on credit before the ledger existed.
    ADJUSTMENT = "adjustment"


# A purchase can only add credit, a refund or chargeback only take it back off. Trial
# credit may be zero, as the platform's trial setting allows.
_DEBITING_KINDS = frozenset({CreditGrantKind.REFUND, CreditGrantKind.CHARGEBACK})


class OrganizationCreditGrant(BaseModel, table=True):
    """One change to an Organization's credit. The ledger is append-only: an Organization
    on credit has a ceiling equal to the sum of its grants, written in the same
    transaction as each new grant."""

    __tablename__: str = "organization_credit_grant"

    organization_id: UUID = Field(foreign_key="organization.id", nullable=False, ondelete="CASCADE", index=True)
    kind: CreditGrantKind = Field(
        sa_column=sa.Column(sa.Enum(CreditGrantKind, name="credit_grant_kind"), nullable=False)
    )
    # Signed: refunds and chargebacks are negative. NUMERIC, not float: the ceiling is
    # their sum, so it must add up exactly.
    credit_usd: Decimal = SqlField(sa_column=sa.Column(sa.Numeric(14, 6), nullable=False))
    # What was charged for it, when anything was. Kept apart from `credit_usd` so a
    # purchase fee or margin changes one without the other.
    amount_paid_usd: Decimal | None = SqlField(default=None, sa_column=sa.Column(sa.Numeric(14, 2), nullable=True))
    # The payment provider's reference, unique so a payment reported twice is granted once.
    external_ref: str | None = Field(default=None, nullable=True, max_length=255, unique=True)
    actor_display: str = Field(nullable=False, max_length=255)
    note: str | None = Field(default=None, nullable=True, max_length=500)


class CreditGrantRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: UUID
    kind: CreditGrantKind
    credit_usd: Decimal
    amount_paid_usd: Decimal | None = None
    external_ref: str | None = None
    actor_display: str
    created_at: datetime


class PlatformCreditGrantRead(CreditGrantRead):
    """A Credit Grant with the Organization it belongs to, for the platform's view."""

    organization_name: str


class CreditGrantCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: CreditGrantKind
    credit_usd: Decimal = PydanticField(allow_inf_nan=False, max_digits=14, decimal_places=6)
    amount_paid_usd: Decimal | None = PydanticField(default=None, ge=0, allow_inf_nan=False, decimal_places=2)
    external_ref: str | None = PydanticField(default=None, max_length=255)
    note: str | None = PydanticField(default=None, max_length=500)

    @model_validator(mode="after")
    def _sign_matches_kind(self) -> CreditGrantCreate:
        if self.kind is CreditGrantKind.PURCHASE and self.credit_usd <= 0:
            raise ValueError("A purchase must add credit")
        if self.kind is CreditGrantKind.TRIAL and self.credit_usd < 0:
            raise ValueError("Trial credit cannot be negative")
        if self.kind in _DEBITING_KINDS and self.credit_usd >= 0:
            raise ValueError(f"A {self.kind.value} grant must take credit off")
        return self


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
    is_trial: bool = False
    trial_expired_at: datetime | None = None
    # How many Agents the Organization may run; None when there is no limit.
    agent_limit: int | None = None
    # Whether it already runs that many, counting Agents this member can't read.
    agent_limit_reached: bool = False
    # How many Agents the trial may run; None for an Organization that is not a trial.
    trial_agent_limit: int | None = None
    # Creation capacity, independent of which Agents this member may read.
    trial_agent_limit_reached: bool = False


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
    is_trial: bool = False
    trial_expired_at: datetime | None = None
    # Its own Agent limit; None when it follows the default.
    agent_limit: int | None = None
    # The Agent limit in force, own or default; None means no limit. Only the single
    # Organization read fills it in.
    agent_limit_in_force: int | None = None


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
    spend_usd: float | None = None
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


class OrganizationAgentLimitUpdate(PydanticBaseModel):
    """An Organization's own Agent limit; null returns it to the default."""

    model_config = ConfigDict(extra="forbid")

    agent_limit: int | None = PydanticField(ge=0, strict=True)


class OrganizationTrialEnd(PydanticBaseModel):
    """The spend limit an Organization goes on to when its trial ends."""

    model_config = ConfigDict(extra="forbid")

    budget_usd: float = PydanticField(ge=0, allow_inf_nan=False)
    budget_duration: LlmBudgetWindow


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


ORGANIZATION_SETTINGS_SUBJECT_DISPLAY = "Organization settings"
# A bound no real Organization reaches; it only stops a typo.
MAX_DEFAULT_AGENT_LIMIT = 1000


class PlatformOrganizationSettings(SQLModel, table=True):
    """The one row of platform-wide Organization settings, created on first save. Without
    a row, the deployment's defaults apply."""

    __tablename__: str = "platform_organization_settings"
    __table_args__ = (
        sa.CheckConstraint("id = 1", name="ck_platform_organization_settings_singleton"),
        sa.CheckConstraint(
            "default_agent_limit >= 1", name="ck_platform_organization_settings_default_agent_limit_positive"
        ),
    )
    id: int = SqlField(default=1, primary_key=True)
    # How many Agents an Organization that is not a trial may run, unless it has its own.
    default_agent_limit: int
    updated_at: datetime = SqlField(sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False))
    updated_by: UUID | None = SqlField(default=None, foreign_key="user.id", ondelete="SET NULL")


class OrganizationSettingsRead(PydanticBaseModel):
    default_agent_limit: int
    # None until the first save.
    updated_at: datetime | None = None


class OrganizationSettingsUpdate(PydanticBaseModel):
    """Omitting a setting leaves it as it is; none can be removed."""

    model_config = ConfigDict(extra="forbid")
    default_agent_limit: int = PydanticField(ge=1, le=MAX_DEFAULT_AGENT_LIMIT, strict=True)
