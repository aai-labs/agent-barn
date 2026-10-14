"""Buying credit: checkout through Stripe, and turning Stripe's signed events into Credit
Grants.

Every grant is keyed by Stripe's own reference — the payment intent for a purchase, the
refund or dispute id for what is taken back — so a redelivered event changes nothing.
Stripe doesn't deliver events in order: a refund settles on the refund's status as Stripe
has it now, and one for a purchase not recorded yet is answered with an error so Stripe
sends it again.
"""

import json
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from starlette.concurrency import run_in_threadpool

from api.core.config import Config
from api.domains.auth.models import CurrentUserContext
from api.domains.billing.models import (
    BillingCheckout,
    BillingSettingsRead,
    BillingSettingsUpdate,
    CheckoutCreate,
    CheckoutRead,
    CreditHistoryItem,
    OrganizationBillingRead,
    PlatformCreditRecordRead,
)
from api.domains.billing.repository import (
    BillingCheckoutRepository,
    BillingCustomerRepository,
    BillingSettingsRepository,
    UnappliedPurchaseRepository,
)
from api.domains.events import ActorIdentity, ActorIdentityType, EventDeliveryDispatcher
from api.domains.organizations.exceptions import OrganizationNotOnCredit
from api.domains.organizations.llm_budget_service import OrganizationLlmBudgetService
from api.domains.organizations.lookup import OrganizationLookupService, RecordedCredit
from api.domains.organizations.service import OrganizationService
from api.domains.platform_admin.service import PlatformAdminService
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.domains.users.service import UserService
from api.infrastructure.shared.models import PaginatedItems, Pagination
from api.infrastructure.stripe.client import PaymentProviderUnavailable, StripeGateway, StripeNotConfigured

logger = logging.getLogger(__name__)

_STRIPE = ActorIdentity(type=ActorIdentityType.SYSTEM, id="stripe")
# Shown wherever a change made by the payment provider is listed; never its name.
_STRIPE_DISPLAY = "Payment provider"
_CREDIT_PLACES = Decimal("0.000001")
_NOT_FOUND = "Not found"
# The smallest card payment Stripe takes in US dollars.
STRIPE_MINIMUM_CHARGE_CENTS = 50
_UNAVAILABLE = "Payments aren't available right now. Try again shortly."
# A refund in any of these didn't, or won't, send the money back.
_REFUND_UNDONE = frozenset({"failed", "canceled"})


def charge_cents(credit_usd: Decimal, settings: BillingSettingsRead) -> int:
    """What `credit_usd` of credit costs, in cents: the credit at the platform's rate, plus
    its purchase fee, rounded up so a fraction of a cent is never given away. Exact
    fractions, so no leftover from dividing by the rate rounds up a whole cent."""
    cents = Fraction(credit_usd) / Fraction(str(settings.credit_rate)) * 100
    cents *= 1 + Fraction(str(settings.purchase_fee_percent)) / 100
    return math.ceil(cents)


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
    users: UserService
    unapplied: UnappliedPurchaseRepository
    checkouts: BillingCheckoutRepository

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

    def list_credit_history(
        self,
        context: CurrentUserContext,
        *,
        page: int,
        page_size: int,
        kind: str | None = None,
        organization_id: UUID | None = None,
    ) -> PaginatedItems[PlatformCreditRecordRead]:
        """Every Organization's changes to its credit, newest first."""
        self.authority.require_platform_admin(context.user)
        grants = self.organizations.list_all_credit_grants(
            Pagination(page=page, size=page_size), kind=kind, organization_id=organization_id
        )
        return PaginatedItems(
            page=grants.page,
            page_size=grants.page_size,
            total=grants.total,
            items=[
                PlatformCreditRecordRead(
                    organization_id=grant.organization_id,
                    organization_name=grant.organization_name,
                    kind=grant.kind.value,
                    credit_usd=float(grant.credit_usd),
                    amount_paid_usd=None if grant.amount_paid_usd is None else float(grant.amount_paid_usd),
                    by=grant.actor_display,
                    reference=grant.external_ref,
                    created_at=grant.created_at,
                )
                for grant in grants.items
            ],
        )

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
            on_credit=credit.runs_on_credit,
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
                    purchased_by=(
                        grant.actor_display
                        if grant.kind.value == "purchase" and grant.actor_display != _STRIPE_DISPLAY
                        else None
                    ),
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
            detail="You don't have access to this organization's billing.",
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

        amount_cents = charge_cents(data.credit_usd, settings)
        if amount_cents < STRIPE_MINIMUM_CHARGE_CENTS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="That's below the smallest payment we can take."
            )

        try:
            customer_id = await run_in_threadpool(self.customers.get_customer_id, organization_id)
            if customer_id is None:
                created = await self.stripe.create_customer(
                    organization_id=organization_id, name=credit.name, email=context.user.email
                )
                customer_id = await run_in_threadpool(self.customers.save_customer_id, organization_id, created)
            else:
                # Receipts go to whoever is buying now: after an ownership change, the
                # former Owner must stop getting them.
                await self.stripe.update_customer_email(customer_id, context.user.email)

            billing_url = f"{self.config.web_app_url.rstrip('/')}/dashboard/{organization_id}/billing"
            session = await self.stripe.create_checkout_session(
                customer_id=customer_id,
                organization_id=organization_id,
                purchased_by_user_id=context.user.id,
                credit_usd=data.credit_usd,
                amount_cents=amount_cents,
                success_url=f"{billing_url}?checkout=success",
                cancel_url=f"{billing_url}?checkout=cancelled",
            )
        except PaymentProviderUnavailable as exc:
            logger.warning("Stripe checkout for Organization %s failed: %s", organization_id, exc)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_UNAVAILABLE) from exc
        except StripeNotConfigured as exc:
            logger.error("Stripe checkout for Organization %s refused: %s", organization_id, exc)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_UNAVAILABLE) from exc
        await run_in_threadpool(
            lambda: self.checkouts.record(
                session.id,
                organization_id,
                credit_usd=data.credit_usd,
                amount_cents=amount_cents,
                purchased_by_user_id=context.user.id,
            )
        )
        return CheckoutRead(url=session.url)

    # --- Stripe's events ------------------------------------------------------------

    async def handle_webhook(self, payload: bytes, signature: str) -> None:
        """Verify a Stripe event and apply it. PermissionError when it isn't Stripe's.

        Served whenever the deployment has a webhook secret, payments on or off: turning
        payments off stops new purchases, not the money already moving.

        Events for things that aren't ours (another product on the same Stripe account,
        a refund of someone else's payment) are acknowledged and ignored, so Stripe stops
        retrying them. One that depends on a purchase not recorded yet is refused with a
        409 so Stripe sends it again.
        """
        if not (self.config.stripe_webhook_secret or "").strip():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
        self.stripe.construct_event(payload, signature)
        # Verified: read it as plain JSON, since the SDK's objects aren't mappings.
        event = json.loads(payload)
        data = event["data"]["object"]
        try:
            match event["type"]:
                case "checkout.session.completed" | "checkout.session.async_payment_succeeded":
                    await run_in_threadpool(self._purchase, data)
                case "refund.created" | "refund.updated" | "refund.failed":
                    await self._settle_refund(data)
                case "charge.dispute.funds_withdrawn":
                    await self._withdraw(data)
                case "charge.dispute.funds_reinstated":
                    await self._withdraw(data)
                    await run_in_threadpool(self._reinstate, data)
                case _:
                    logger.debug("Ignoring Stripe event %s", event["type"])
        except PaymentProviderUnavailable as exc:
            # Stripe will send the event again.
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_UNAVAILABLE) from exc
        except StripeNotConfigured as exc:
            # Boot refuses this setup; if it happens anyway, keep the event for a retry.
            logger.error("Stripe event %s can't be settled: %s", event.get("id"), exc)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_UNAVAILABLE) from exc

    def _purchase(self, session: dict) -> None:
        """Grant a paid Checkout Session's credit, as our own record of the checkout says,
        once the session matches that record."""
        if session.get("payment_status") != "paid":
            # A delayed payment method: granted on async_payment_succeeded instead.
            return
        metadata = session.get("metadata") or {}
        if "organization_id" not in metadata or "credit_usd" not in metadata:
            logger.info("Ignoring a Stripe Checkout Session that isn't a credit purchase: %s", session.get("id"))
            return
        checkout = self.checkouts.get(session.get("id") or "")
        reference = session.get("payment_intent") or ""
        amount_paid_usd = Decimal(session.get("amount_total") or 0) / 100
        problem = self._mismatch(session, checkout)
        if problem is not None or checkout is None:
            organization_id = checkout.organization_id if checkout else self._uuid(metadata["organization_id"])
            self._unapplied(
                organization_id,
                reference or str(session.get("id")),
                Decimal(str(checkout.credit_usd if checkout else metadata["credit_usd"])),
                amount_paid_usd,
                problem or "No checkout was started for this payment.",
            )
            return
        organization_id = checkout.organization_id
        actor, actor_display = self._buyer(
            str(checkout.purchased_by_user_id) if checkout.purchased_by_user_id else None
        )
        try:
            self.budgets.record_purchase(
                organization_id,
                credit_usd=Decimal(str(checkout.credit_usd)),
                amount_paid_usd=amount_paid_usd,
                reference=reference,
                actor=actor,
                actor_display=actor_display,
            )
        except OrganizationNotOnCredit:
            # Paid for, but no longer on credit (a Platform Administrator moved it onto a
            # renewing limit meanwhile). Acknowledged so Stripe stops retrying, and
            # flagged on the platform's audit log so someone refunds or adjusts it.
            self._unapplied(
                organization_id,
                reference,
                Decimal(str(checkout.credit_usd)),
                amount_paid_usd,
                "The organization no longer runs on credit.",
            )
            return
        # Also on a redelivery: a first delivery that granted the credit but failed to
        # convert the trial must not leave it a trial for good.
        self.organization_service.convert_trial(organization_id, actor=_STRIPE, actor_display="Credit purchase")

    @staticmethod
    def _mismatch(session: dict, checkout: BillingCheckout | None) -> str | None:
        """Why a paid session isn't the checkout we created, or None when it is."""
        if checkout is None:
            return "No checkout was started for this payment."
        if session.get("mode") != "payment":
            return "The payment isn't a one-off payment."
        if session.get("currency") != "usd":
            return "The payment isn't in US dollars."
        if not session.get("payment_intent"):
            return "The payment has no payment reference."
        if session.get("client_reference_id") != str(checkout.organization_id):
            return "The payment names a different organization."
        if session.get("amount_total") != checkout.amount_cents:
            return "The amount paid doesn't match the price of the credit."
        return None

    @staticmethod
    def _uuid(value: str) -> UUID | None:
        try:
            return UUID(value)
        except ValueError:
            return None

    def _unapplied(
        self, organization_id: UUID | None, reference: str, credit_usd: Decimal, amount_paid_usd: Decimal, reason: str
    ) -> None:
        """Grant nothing, and put the payment on the platform's audit log to be refunded."""
        logger.error("Stripe payment %s granted no credit: %s", reference, reason)
        name = self.organizations.get_name(organization_id) if organization_id else ""
        self.dispatcher.enqueue_immediate(
            self.unapplied.record(
                name or "Unknown organization",
                payment_reference=reference,
                credit_usd=credit_usd,
                amount_paid_usd=amount_paid_usd,
                reason=reason,
            )
        )

    def _buyer(self, user_id: str | None) -> tuple[ActorIdentity, str]:
        """Who bought the credit, or the payment itself when they can't be named (an older
        session, or an account deleted since): the payment stands either way."""
        try:
            user = self.users.get_user(UUID(user_id)) if user_id else None
        except ValueError, HTTPException:
            user = None
        if user is None:
            return _STRIPE, _STRIPE_DISPLAY
        return ActorIdentity(type=ActorIdentityType.USER, id=user.id), user.full_name or user.email

    async def _purchase_for(self, reference: str, payment_intent: str | None) -> RecordedCredit | None:
        """The purchase a refund or dispute is against. None when it isn't one of ours;
        a 409 when it is but hasn't been recorded yet, so Stripe sends the event again."""
        if not payment_intent:
            return None
        purchase = await run_in_threadpool(self.organizations.find_credit_grant, payment_intent)
        if purchase is not None and purchase.amount_paid_usd:
            return purchase
        if await run_in_threadpool(self.unapplied.includes, payment_intent):
            logger.info("Ignoring Stripe %s for payment %s, which granted no credit", reference, payment_intent)
            return None
        metadata = await self.stripe.payment_metadata(payment_intent)
        organization_id = metadata.get("organization_id")
        if not organization_id or "credit_usd" not in metadata:
            logger.info("Ignoring Stripe %s for a payment that isn't a credit purchase", reference)
            return None
        credit = await run_in_threadpool(self.organizations.get_credit, UUID(organization_id))
        if credit is None or not credit.runs_on_credit:
            # Its payment was never granted (see _purchase), so there's nothing to take.
            logger.info("Ignoring Stripe %s for Organization %s, not on credit", reference, organization_id)
            return None
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="The payment this refers to hasn't been recorded yet"
        )

    async def _settle_refund(self, refund: dict) -> None:
        """Bring the ledger in line with the refund as Stripe has it now: credit taken back
        while it stands, given back once it has failed or been cancelled."""
        refund_id = refund["id"]
        purchase = await self._purchase_for(refund_id, refund.get("payment_intent"))
        if purchase is None:
            return
        if await self.stripe.refund_status(refund_id) in _REFUND_UNDONE:
            await run_in_threadpool(self._give_back, refund_id, f"{refund_id}:returned", Decimal(1))
        else:
            await run_in_threadpool(self._take_back, purchase, refund_id, refund["amount"], False)

    async def _withdraw(self, dispute: dict) -> None:
        purchase = await self._purchase_for(dispute["id"], dispute.get("payment_intent"))
        if purchase is not None:
            await run_in_threadpool(self._take_back, purchase, dispute["id"], dispute["amount"], True)

    def _reinstate(self, dispute: dict) -> None:
        """Give back the share of a lost dispute's credit that was reinstated: all of it
        unless Stripe says only part of the money came back."""
        transactions = dispute.get("balance_transactions") or []
        reinstated = sum(t["amount"] for t in transactions if t.get("amount", 0) > 0)
        share = Decimal(1)
        if transactions and dispute["amount"]:
            share = min(share, Decimal(reinstated) / dispute["amount"])
        self._give_back(dispute["id"], f"{dispute['id']}:reinstated", share)

    def _take_back(self, purchase: RecordedCredit, reference: str, cents: int, chargeback: bool) -> None:
        """Take back the share of a purchase's credit that `cents` of its payment bought."""
        if not purchase.amount_paid_usd:
            return
        share = (Decimal(cents) / 100) / purchase.amount_paid_usd
        credit = (purchase.credit_usd * share).quantize(_CREDIT_PLACES)
        if credit <= 0:
            return
        self._record(
            purchase.organization_id,
            reference,
            lambda: self.budgets.take_back_credit(
                purchase.organization_id,
                credit_usd=credit,
                reference=reference,
                chargeback=chargeback,
                actor=_STRIPE,
                actor_display=_STRIPE_DISPLAY,
            ),
        )

    def _give_back(self, taken_reference: str, reference: str, share: Decimal) -> None:
        """Return `share` of the credit taken back under `taken_reference`, if any was."""
        taken = self.organizations.find_credit_grant(taken_reference)
        if taken is None:
            logger.info("Ignoring Stripe reversal %s of credit never taken back", reference)
            return
        credit = (-taken.credit_usd * share).quantize(_CREDIT_PLACES)
        if credit <= 0:
            return
        self._record(
            taken.organization_id,
            reference,
            lambda: self.budgets.return_credit(
                taken.organization_id,
                credit_usd=credit,
                reference=reference,
                actor=_STRIPE,
                actor_display=_STRIPE_DISPLAY,
            ),
        )

    @staticmethod
    def _record(organization_id: UUID, reference: str, grant: Callable[[], bool]) -> None:
        try:
            grant()
        except OrganizationNotOnCredit:
            logger.error("Stripe %s for Organization %s, which no longer runs on credit", reference, organization_id)
