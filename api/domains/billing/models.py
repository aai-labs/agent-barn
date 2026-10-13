"""Buying credit: the platform's billing settings, each Organization's Stripe Customer, and
what the Billing page reads."""

from datetime import datetime
from decimal import Decimal
from typing import Self
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlmodel import Field as SqlField
from sqlmodel import SQLModel

BILLING_SETTINGS_SUBJECT_DISPLAY = "Billing settings"
DEFAULT_MIN_PURCHASE_USD = 5.0
DEFAULT_MAX_PURCHASE_USD = 500.0
DEFAULT_CREDIT_RATE = 1.0
DEFAULT_PURCHASE_FEE_PERCENT = 0.0
# Bounds no real setting reaches; they only stop a typo.
MAX_PURCHASE_CAP_USD = 100_000.0
MAX_PURCHASE_FEE_PERCENT = 100.0


class PlatformBillingSettings(SQLModel, table=True):
    """The one row of billing settings, created on first save. Without a row, the
    defaults apply."""

    __tablename__: str = "platform_billing_settings"
    __table_args__ = (
        sa.CheckConstraint("id = 1", name="ck_platform_billing_settings_singleton"),
        sa.CheckConstraint("min_purchase_usd > 0", name="ck_platform_billing_settings_min_positive"),
        sa.CheckConstraint("max_purchase_usd >= min_purchase_usd", name="ck_platform_billing_settings_max_above_min"),
        sa.CheckConstraint("credit_rate > 0", name="ck_platform_billing_settings_rate_positive"),
        sa.CheckConstraint("purchase_fee_percent >= 0", name="ck_platform_billing_settings_fee_non_negative"),
    )
    id: int = SqlField(default=1, primary_key=True)
    min_purchase_usd: float
    max_purchase_usd: float
    # Credit granted per dollar charged, before the purchase fee. 1.0 passes model spend
    # through at cost; below 1.0 is a margin.
    credit_rate: float
    # Added on top of every purchase, e.g. to cover the payment provider's fee.
    purchase_fee_percent: float
    updated_at: datetime = SqlField(sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False))
    updated_by: UUID | None = SqlField(default=None, foreign_key="user.id", ondelete="SET NULL")


class OrganizationBillingCustomer(SQLModel, table=True):
    """The Stripe Customer an Organization pays as, created on its first purchase so its
    receipts and payments stay together."""

    __tablename__: str = "organization_billing_customer"
    organization_id: UUID = SqlField(primary_key=True, foreign_key="organization.id", ondelete="CASCADE")
    stripe_customer_id: str = SqlField(unique=True, max_length=255)
    created_at: datetime = SqlField(sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False))


class BillingSettingsRead(BaseModel):
    # Whether this deployment takes payments at all (PAYMENTS_ENABLED).
    payments_enabled: bool = False
    min_purchase_usd: float = DEFAULT_MIN_PURCHASE_USD
    max_purchase_usd: float = DEFAULT_MAX_PURCHASE_USD
    credit_rate: float = DEFAULT_CREDIT_RATE
    purchase_fee_percent: float = DEFAULT_PURCHASE_FEE_PERCENT
    # None until the first save.
    updated_at: datetime | None = None


class BillingSettingsUpdate(BaseModel):
    """Omitting a setting leaves it as it is; none can be removed."""

    model_config = ConfigDict(extra="forbid")
    min_purchase_usd: float | None = Field(default=None, gt=0, le=MAX_PURCHASE_CAP_USD, allow_inf_nan=False)
    max_purchase_usd: float | None = Field(default=None, gt=0, le=MAX_PURCHASE_CAP_USD, allow_inf_nan=False)
    credit_rate: float | None = Field(default=None, gt=0, le=100, allow_inf_nan=False)
    purchase_fee_percent: float | None = Field(default=None, ge=0, le=MAX_PURCHASE_FEE_PERCENT, allow_inf_nan=False)

    @model_validator(mode="after")
    def _settings_keep_a_value(self) -> Self:
        for setting in self.model_fields_set:
            if getattr(self, setting) is None:
                raise ValueError(f"{setting} can't be removed")
        return self

    def changes(self) -> dict[str, float]:
        return self.model_dump(include=self.model_fields_set)


class CreditHistoryItem(BaseModel):
    kind: str
    credit_usd: float
    # What was charged for it, and who bought it, for a purchase.
    amount_paid_usd: float | None = None
    purchased_by: str | None = None
    created_at: datetime


class OrganizationBillingRead(BaseModel):
    # Whether this Organization can buy credit: payments are on and it runs on credit.
    available: bool
    credit_usd: float
    # None until spend has been observed.
    spend_usd: float | None = None
    balance_usd: float | None = None
    min_purchase_usd: float
    max_purchase_usd: float
    credit_rate: float
    purchase_fee_percent: float
    # Newest first.
    history: list[CreditHistoryItem] = Field(default_factory=list)


class CheckoutCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credit_usd: Decimal = Field(gt=0, max_digits=10, decimal_places=2, allow_inf_nan=False)


class CheckoutRead(BaseModel):
    # Stripe's page, where the payment is made.
    url: str
