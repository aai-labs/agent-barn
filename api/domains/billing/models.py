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
DEFAULT_PURCHASE_FEE_PERCENT = 0.0
# Bounds no real setting reaches; they only stop a typo.
MAX_PURCHASE_CAP_USD = 100_000.0
# The smallest card payment Stripe takes in US dollars.
MIN_PURCHASE_FLOOR_USD = 0.5
MAX_PURCHASE_FEE_PERCENT = 100.0


class PlatformBillingSettings(SQLModel, table=True):
    """The one row of billing settings, created on first save. Without a row, the
    defaults apply."""

    __tablename__: str = "platform_billing_settings"
    __table_args__ = (
        sa.CheckConstraint("id = 1", name="ck_platform_billing_settings_singleton"),
        sa.CheckConstraint("min_purchase_usd > 0", name="ck_platform_billing_settings_min_positive"),
        sa.CheckConstraint("max_purchase_usd >= min_purchase_usd", name="ck_platform_billing_settings_max_above_min"),
        sa.CheckConstraint("purchase_fee_percent >= 0", name="ck_platform_billing_settings_fee_non_negative"),
    )
    id: int = SqlField(default=1, primary_key=True)
    # Whether Organizations on credit can buy more. Off until a Platform Administrator
    # turns it on, which needs the deployment's Stripe keys.
    payments_enabled: bool = SqlField(default=False, sa_column_kwargs={"server_default": "false"})
    min_purchase_usd: float
    max_purchase_usd: float
    # Added on top of every purchase, to cover the payment provider's fee or keep a margin.
    # $1 of credit is always $1 of model spend; this is the only markup.
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


class BillingCheckout(SQLModel, table=True):
    """A Checkout Session we created, and what it was for. The webhook grants what this
    says, and only when Stripe's session matches it: the session's own metadata could
    have been written by anyone with access to the Stripe account."""

    __tablename__: str = "billing_checkout"
    __table_args__ = (sa.CheckConstraint("amount_cents > 0", name="ck_billing_checkout_amount_positive"),)
    stripe_session_id: str = SqlField(primary_key=True, max_length=255)
    organization_id: UUID = SqlField(foreign_key="organization.id", ondelete="CASCADE", index=True)
    credit_usd: Decimal = SqlField(sa_column=sa.Column(sa.Numeric(14, 6), nullable=False))
    amount_cents: int
    purchased_by_user_id: UUID | None = SqlField(default=None, foreign_key="user.id", ondelete="SET NULL")
    created_at: datetime = SqlField(sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False))


class BillingUnappliedPayment(SQLModel, table=True):
    """A payment that granted no credit, put on the platform audit log to be refunded.
    Its refund or dispute then has nothing to take back, rather than waiting for a
    purchase that will never be recorded."""

    __tablename__: str = "billing_unapplied_payment"
    payment_reference: str = SqlField(primary_key=True, max_length=255)
    created_at: datetime = SqlField(sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False))


class BillingSettingsRead(BaseModel):
    # Whether a Platform Administrator has turned payments on.
    payments_enabled: bool = False
    # Whether this deployment has the Stripe keys payments need. Payments are taken only
    # with both: turned on, and this.
    payments_configured: bool = False
    min_purchase_usd: float = DEFAULT_MIN_PURCHASE_USD
    max_purchase_usd: float = DEFAULT_MAX_PURCHASE_USD
    purchase_fee_percent: float = DEFAULT_PURCHASE_FEE_PERCENT
    # None until the first save.
    updated_at: datetime | None = None


class BillingSettingsUpdate(BaseModel):
    """Omitting a setting leaves it as it is; none can be removed."""

    model_config = ConfigDict(extra="forbid")
    payments_enabled: bool | None = None
    min_purchase_usd: float | None = Field(
        default=None, ge=MIN_PURCHASE_FLOOR_USD, le=MAX_PURCHASE_CAP_USD, allow_inf_nan=False
    )
    max_purchase_usd: float | None = Field(
        default=None, ge=MIN_PURCHASE_FLOOR_USD, le=MAX_PURCHASE_CAP_USD, allow_inf_nan=False
    )
    purchase_fee_percent: float | None = Field(default=None, ge=0, le=MAX_PURCHASE_FEE_PERCENT, allow_inf_nan=False)

    @model_validator(mode="after")
    def _settings_keep_a_value(self) -> Self:
        for setting in self.model_fields_set:
            if getattr(self, setting) is None:
                raise ValueError(f"{setting} can't be removed")
        return self

    def changes(self) -> dict[str, bool | float]:
        return self.model_dump(include=self.model_fields_set)


class CreditHistoryItem(BaseModel):
    kind: str
    credit_usd: float
    # What was charged for it, and who bought it, for a purchase. None when the buyer
    # can't be named (a purchase from before buyers were recorded, or a deleted account).
    amount_paid_usd: float | None = None
    purchased_by: str | None = None
    created_at: datetime


class PlatformCreditRecordRead(BaseModel):
    """One change to an Organization's credit, in the platform's view of all of them."""

    organization_id: UUID
    organization_name: str
    kind: str
    credit_usd: float
    amount_paid_usd: float | None = None
    # Who made the change: the buyer, a Platform Administrator, or "Payment provider" for
    # what the payment provider did on its own (refunds, disputes) or a buyer it can't name.
    by: str
    # The payment provider's reference (payment, refund or dispute), when there is one.
    reference: str | None = None
    created_at: datetime


class OrganizationBillingRead(BaseModel):
    # Whether this Organization can buy credit: payments are on and it runs on credit.
    available: bool
    # Whether it runs on credit at all, rather than on a limit its plan renews.
    on_credit: bool
    credit_usd: float
    # None until spend has been observed.
    spend_usd: float | None = None
    balance_usd: float | None = None
    min_purchase_usd: float
    max_purchase_usd: float
    purchase_fee_percent: float
    # Newest first.
    history: list[CreditHistoryItem] = Field(default_factory=list)


class CheckoutCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credit_usd: Decimal = Field(gt=0, max_digits=10, decimal_places=2, allow_inf_nan=False)


class CheckoutRead(BaseModel):
    # Stripe's page, where the payment is made.
    url: str
