"""Buying credit: checkout through Stripe, and turning Stripe's signed events into Credit
Grants.

Every grant is keyed by Stripe's own reference — the payment intent for a purchase, the
refund or dispute id for what is taken back — so a redelivered event changes nothing.
"""

import json
import logging
import math
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from starlette.concurrency import run_in_threadpool

from api.core.config import Config
from api.domains.auth.models import CurrentUserContext
from api.domains.billing.models import (
    BillingSettingsRead,
    BillingSettingsUpdate,
    CheckoutCreate,
    CheckoutRead,
    CreditHistoryItem,
    OrganizationBillingRead,
)
from api.domains.billing.repository import BillingCustomerRepository, BillingSettingsRepository
from api.domains.events import ActorIdentity, ActorIdentityType, EventDeliveryDispatcher
from api.domains.organizations.exceptions import OrganizationNotOnCredit
from api.domains.organizations.llm_budget_service import OrganizationLlmBudgetService
from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.organizations.models import CreditGrantCreate, CreditGrantKind
from api.domains.organizations.service import OrganizationService
from api.domains.platform_admin.service import PlatformAdminService
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.infrastructure.stripe.client import StripeGateway

logger = logging.getLogger(__name__)

_STRIPE = ActorIdentity(type=ActorIdentityType.SYSTEM, id="stripe")
_STRIPE_DISPLAY = "Stripe"
_CREDIT_PLACES = Decimal("0.000001")
_NOT_FOUND = "Not found"


def charge_cents(credit_usd: Decimal, settings: BillingSettingsRead) -> int:
    """What `credit_usd` of credit costs, in cents: the credit at the platform's rate, plus
    its purchase fee, rounded up so a fraction of a cent is never given away."""
    dollars = credit_usd / Decimal(str(settings.credit_rate))
    dollars *= 1 + Decimal(str(settings.purchase_fee_percent)) / 100
    return math.ceil(dollars * 100)


@inject
@singleton
@dataclass
class BillingService:
    settings: BillingSettingsRepository
    customers: BillingCustomerRepository
    stripe: StripeGateway
    config: Config
    authority: PlatformAdminService
    permission_policy: PermissionPolicy
    dispatcher: EventDeliveryDispatcher
    organizations: OrganizationLookupService
    budgets: OrganizationLlmBudgetService
    organization_service: OrganizationService

    # --- platform settings ----------------------------------------------------------

    def read_settings(self, context: CurrentUserContext) -> BillingSettingsRead:
        self.authority.require_platform_admin(context.user)
        return self._settings()

    def update_settings(self, data: BillingSettingsUpdate, context: CurrentUserContext) -> BillingSettingsRead:
        self.authority.require_platform_admin(context.user)
        try:
            stored, delivery_ids = self.settings.set_settings(
                data.changes(), context.user.id, context.user.full_name or context.user.email
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        self.dispatcher.enqueue_immediate(delivery_ids)
        return stored.model_copy(update={"payments_enabled": self.config.payments_enabled})

    def _settings(self) -> BillingSettingsRead:
        return self.settings.read().model_copy(update={"payments_enabled": self.config.payments_enabled})

    # --- what an Organization sees --------------------------------------------------

    def get_billing(self, organization_id: UUID, context: CurrentUserContext) -> OrganizationBillingRead:
        self._require_billing(context, organization_id)
        credit = self.organizations.get_credit(organization_id)
        if credit is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
        settings = self._settings()
        grants = self.organizations.list_credit_grants(organization_id)
        # The same spend the limit is enforced on: the team's, plus what it doesn't count.
        spend = self.budgets.get_organization_llm_budget(organization_id, context).spend_usd
        return OrganizationBillingRead(
            available=self.config.payments_enabled and credit.runs_on_credit,
            credit_usd=credit.credit_usd,
            spend_usd=spend,
            balance_usd=None if spend is None else credit.credit_usd - spend,
            min_purchase_usd=settings.min_purchase_usd,
            max_purchase_usd=settings.max_purchase_usd,
            credit_rate=settings.credit_rate,
            purchase_fee_percent=settings.purchase_fee_percent,
            history=[
                CreditHistoryItem(
                    kind=grant.kind.value,
                    credit_usd=float(grant.credit_usd),
                    amount_paid_usd=None if grant.amount_paid_usd is None else float(grant.amount_paid_usd),
                    created_at=grant.created_at,
                )
                for grant in reversed(grants)
            ],
        )

    def _require_billing(self, context: CurrentUserContext, organization_id: UUID) -> None:
        self.permission_policy.require(
            context,
            organization_id,
            PermissionKey.BILLING_MANAGE,
            detail="Only the organization's owner can buy credit.",
        )

    # --- checkout -------------------------------------------------------------------

    async def create_checkout(
        self, organization_id: UUID, data: CheckoutCreate, context: CurrentUserContext
    ) -> CheckoutRead:
        """Send the Owner to Stripe's page to pay for `data.credit_usd` of credit. Nothing
        is granted here: credit arrives with Stripe's signed event once the payment is."""
        if not self.config.payments_enabled:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
        await run_in_threadpool(self._require_billing, context, organization_id)
        credit = await run_in_threadpool(self.organizations.get_credit, organization_id)
        if credit is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
        if not credit.runs_on_credit:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This organization's spend limit is set by the platform, so it doesn't buy credit.",
            )
        settings = await run_in_threadpool(self._settings)
        if not settings.min_purchase_usd <= float(data.credit_usd) <= settings.max_purchase_usd:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Choose between ${settings.min_purchase_usd:,.2f} and ${settings.max_purchase_usd:,.2f} of credit."
                ),
            )

        customer_id = await run_in_threadpool(self.customers.get_customer_id, organization_id)
        if customer_id is None:
            created = await self.stripe.create_customer(
                organization_id=organization_id, name=credit.name, email=context.user.email
            )
            customer_id = await run_in_threadpool(self.customers.save_customer_id, organization_id, created)

        billing_url = f"{self.config.web_app_url.rstrip('/')}/dashboard/{organization_id}/billing"
        session = await self.stripe.create_checkout_session(
            customer_id=customer_id,
            organization_id=organization_id,
            credit_usd=data.credit_usd,
            amount_cents=charge_cents(data.credit_usd, settings),
            success_url=f"{billing_url}?checkout=success",
            cancel_url=f"{billing_url}?checkout=cancelled",
        )
        return CheckoutRead(url=session.url)

    # --- Stripe's events ------------------------------------------------------------

    def handle_webhook(self, payload: bytes, signature: str) -> None:
        """Verify a Stripe event and apply it. PermissionError when it isn't Stripe's.

        Events for things that aren't ours (another product on the same Stripe account,
        a refund of a payment we never granted) are acknowledged and ignored, so Stripe
        stops retrying them.
        """
        if not self.config.payments_enabled:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
        self.stripe.construct_event(payload, signature)
        # Verified: read it as plain JSON, since the SDK's objects aren't mappings.
        event = json.loads(payload)
        data = event["data"]["object"]
        match event["type"]:
            case "checkout.session.completed" | "checkout.session.async_payment_succeeded":
                self._purchase(data)
            case "refund.created":
                if data.get("status") != "failed":
                    self._take_back(CreditGrantKind.REFUND, data["id"], data.get("payment_intent"), data["amount"])
            case "refund.failed":
                self._give_back(data["id"], f"{data['id']}:failed")
            case "charge.dispute.funds_withdrawn":
                self._take_back(CreditGrantKind.CHARGEBACK, data["id"], data.get("payment_intent"), data["amount"])
            case "charge.dispute.funds_reinstated":
                self._give_back(data["id"], f"{data['id']}:reinstated")
            case _:
                logger.debug("Ignoring Stripe event %s", event["type"])

    def _purchase(self, session: dict) -> None:
        if session.get("payment_status") != "paid":
            # A delayed payment method: granted on async_payment_succeeded instead.
            return
        metadata = session.get("metadata") or {}
        if "organization_id" not in metadata or "credit_usd" not in metadata:
            logger.info("Ignoring a Stripe Checkout Session that isn't a credit purchase: %s", session.get("id"))
            return
        organization_id = UUID(metadata["organization_id"])
        grant = CreditGrantCreate(
            kind=CreditGrantKind.PURCHASE,
            credit_usd=Decimal(metadata["credit_usd"]),
            amount_paid_usd=Decimal(session["amount_total"]) / 100,
            external_ref=session["payment_intent"],
        )
        try:
            self.budgets.grant_credit(organization_id, grant, actor=_STRIPE, actor_display=_STRIPE_DISPLAY)
        except OrganizationNotOnCredit:
            # Paid for, but no longer on credit (a Platform Administrator moved it onto a
            # renewing limit meanwhile). Acknowledged so Stripe stops retrying; someone has
            # to refund or adjust it by hand.
            logger.error(
                "Stripe payment %s for Organization %s, which no longer runs on credit",
                session["payment_intent"],
                organization_id,
            )
            return
        # Also on a redelivery: a first delivery that granted the credit but failed to
        # convert the trial must not leave it a trial for good.
        self.organization_service.convert_trial(organization_id, actor=_STRIPE, actor_display="Credit purchase")

    def _take_back(self, kind: CreditGrantKind, reference: str, payment_intent: str | None, cents: int) -> None:
        """Take back the share of a purchase's credit that `cents` of its payment bought."""
        purchase = self.organizations.find_credit_grant(payment_intent) if payment_intent else None
        if purchase is None or not purchase.amount_paid_usd:
            logger.info("Ignoring Stripe %s %s for a payment that granted no credit", kind.value, reference)
            return
        share = (Decimal(cents) / 100) / purchase.amount_paid_usd
        credit = -(purchase.credit_usd * share).quantize(_CREDIT_PLACES)
        if not credit:
            return
        self._grant(purchase.organization_id, kind, credit, reference)

    def _give_back(self, taken_reference: str, reference: str) -> None:
        """Return credit taken back by a refund that failed or a dispute that was won."""
        taken = self.organizations.find_credit_grant(taken_reference)
        if taken is None:
            logger.info("Ignoring Stripe reversal %s of credit never taken back", reference)
            return
        self._grant(taken.organization_id, CreditGrantKind.ADJUSTMENT, -taken.credit_usd, reference)

    def _grant(self, organization_id: UUID, kind: CreditGrantKind, credit_usd: Decimal, reference: str) -> None:
        try:
            self.budgets.grant_credit(
                organization_id,
                CreditGrantCreate(kind=kind, credit_usd=credit_usd, external_ref=reference),
                actor=_STRIPE,
                actor_display=_STRIPE_DISPLAY,
            )
        except OrganizationNotOnCredit:
            logger.error(
                "Stripe %s %s for Organization %s, which no longer runs on credit",
                kind.value,
                reference,
                organization_id,
            )
