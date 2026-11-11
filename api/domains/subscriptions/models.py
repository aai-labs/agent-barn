"""Subscriptions: what keeps an Organization on a paid Tier, month by month.

A subscription is provider-neutral. Its provider takes the payment: today only the mock
provider, which deployments turn on for demonstrations; a payment provider plugs in
behind the same seam (`provider.py`) and drives the same activation, renewal and ending.
See `docs/features/tiers.md#subscriptions`.
"""

import enum
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.domains.usage.models import OrganizationTierRead
from api.infrastructure.postgres.models import BaseModel

# One subscription period. A payment provider reports its own periods; the mock uses this.
MOCK_PERIOD_DAYS = 30


class SubscriptionPortal(PydanticBaseModel):
    """Where the Owner manages the card, billing details and invoices."""

    url: str


@dataclass(frozen=True)
class ProviderStart:
    # The provider took the payment: activate now, under this reference.
    activate_now: bool
    provider_subscription_id: str | None = None
    # Otherwise, where the buyer pays.
    redirect_url: str | None = None


@dataclass(frozen=True)
class Buyer:
    organization_id: UUID
    organization_name: str
    email: str
    # Where the provider's own pages send the buyer back: Billing, or onboarding.
    return_url: str


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    # A renewal payment failed; the Tier is kept through the payment grace period.
    PAST_DUE = "past_due"
    CANCELED = "canceled"


class SubscriptionProviderKey(str, enum.Enum):
    # A pretend payment, for demonstrations. Renews itself at each period's end.
    MOCK = "mock"
    STRIPE = "stripe"


class OrganizationSubscription(BaseModel, table=True):
    """One subscription. An Organization has at most one that isn't cancelled."""

    __tablename__: str = "organization_subscription"
    __table_args__ = (
        sa.Index(
            "uq_organization_subscription_live",
            "organization_id",
            unique=True,
            postgresql_where=sa.text("status <> 'canceled'"),
        ),
        sa.UniqueConstraint(
            "provider", "provider_subscription_id", name="uq_organization_subscription_provider_reference"
        ),
        sa.CheckConstraint("status IN ('active', 'past_due', 'canceled')", name="ck_organization_subscription_status"),
        sa.CheckConstraint("current_period_end > current_period_start", name="ck_organization_subscription_period"),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", ondelete="CASCADE", index=True)
    tier_id: UUID = SqlField(foreign_key="tier.id", ondelete="RESTRICT")
    provider: str = SqlField(max_length=16)
    # The provider's own id for it, unique per provider.
    provider_subscription_id: str | None = SqlField(default=None, max_length=255)
    status: str = SqlField(default=SubscriptionStatus.ACTIVE.value, max_length=16)
    current_period_start: datetime = SqlField(sa_type=sa.DateTime(timezone=True))  # type: ignore
    current_period_end: datetime = SqlField(sa_type=sa.DateTime(timezone=True))  # type: ignore
    # Ends when the period does, rather than renewing.
    cancel_at_period_end: bool = SqlField(default=False)
    # A smaller Tier chosen to take over when the period ends; a bigger one applies at once.
    scheduled_tier_id: UUID | None = SqlField(default=None, foreign_key="tier.id", ondelete="RESTRICT")
    # The provider's own record of that scheduled change, to take it back.
    provider_schedule_id: str | None = SqlField(default=None, max_length=255)
    past_due_since: datetime | None = SqlField(default=None, sa_type=sa.DateTime(timezone=True))  # type: ignore
    canceled_at: datetime | None = SqlField(default=None, sa_type=sa.DateTime(timezone=True))  # type: ignore
    # When activation finished: the Tier, the one-time credit, the first allowance and the
    # holds. Until then each provider event and the sweep take it up where it stopped.
    activated_at: datetime | None = SqlField(default=None, sa_type=sa.DateTime(timezone=True))  # type: ignore
    # The allowance granted for this period, and the Organization's spend when it began, so
    # what is left of the allowance can expire when it ends.
    period_allowance_usd: Decimal = SqlField(
        default=Decimal(0), sa_column=Column(sa.Numeric(10, 2), nullable=False, server_default="0")
    )
    period_spend_start_usd: Decimal = SqlField(
        default=Decimal(0), sa_column=Column(sa.Numeric(14, 6), nullable=False, server_default="0")
    )


class SubscriptionRead(PydanticBaseModel):
    id: UUID
    tier: OrganizationTierRead
    status: SubscriptionStatus
    provider: SubscriptionProviderKey
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool
    # The smaller Tier it moves to when this period ends, if one was chosen.
    scheduled_tier: OrganizationTierRead | None = None
    # When a renewal payment failed, and when the Tier is lost unless it is paid by then.
    past_due_since: datetime | None = None
    grace_ends_at: datetime | None = None
    # Whether the provider has a page for the card, billing details and invoices.
    manageable: bool = False
    # This period's allowance, and what is left of it as of the last spend snapshot.
    allowance_usd: float
    allowance_remaining_usd: float


class SubscriptionStart(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    tier_key: str = Field(min_length=1, max_length=32)
    # Where a payment provider's page sends the Owner back.
    return_to: Literal["billing", "onboarding"] = "billing"


class SubscriptionStartRead(PydanticBaseModel):
    """`active`: the subscription is in place now. `redirect`: the payment provider's page
    takes the payment, and the subscription starts when it reports the payment."""

    outcome: str
    redirect_url: str | None = None
    subscription: SubscriptionRead | None = None
