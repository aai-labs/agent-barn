import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.domains.auth.models import CurrentUserContext
from api.domains.billing.repository import BillingSettingsRepository
from api.domains.events import ActorIdentity, ActorIdentityType, EventDeliveryDispatcher, resolve_actor_identity
from api.domains.events.catalog import (
    ORGANIZATION_SUBSCRIPTION_CHANGED,
    ORGANIZATION_SUBSCRIPTION_ENDED,
    ORGANIZATION_SUBSCRIPTION_RENEWED,
    ORGANIZATION_SUBSCRIPTION_STARTED,
)
from api.domains.organizations.llm_budget_service import OrganizationLlmBudgetService
from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.organizations.models import CreditGrantCreate, CreditGrantKind
from api.domains.organizations.repository import OrganizationRepository
from api.domains.organizations.service import OrganizationService
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.domains.subscriptions.models import (
    MOCK_PERIOD_DAYS,
    Buyer,
    OrganizationSubscription,
    SubscriptionPortal,
    SubscriptionProviderKey,
    SubscriptionRead,
    SubscriptionStartRead,
    SubscriptionStatus,
)
from api.domains.subscriptions.provider import SubscriptionProvider, SubscriptionProviders
from api.domains.subscriptions.repository import SubscriptionRepository
from api.domains.tiers.holds import TierHoldService
from api.domains.tiers.models import FREE_TIER_KEY, Tier, TierActivation, TierHoldPreviewRead
from api.domains.tiers.repository import TierRepository
from api.domains.usage.models import OrganizationTierRead
from api.infrastructure.stripe.client import PaymentProviderUnavailable, StripeNotConfigured
from api.infrastructure.stripe.subscriptions import PaymentDeclined

logger = logging.getLogger(__name__)

_SYSTEM = ActorIdentity(type=ActorIdentityType.SYSTEM, id="subscriptions")
_SYSTEM_DISPLAY = "Subscription renewal"
_UNAVAILABLE = "Payments are unavailable right now. Try again in a few minutes."
_CENT = Decimal("0.01")


def _money(value: float | Decimal | None) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.000001"))


@dataclass(frozen=True)
class _Actor:
    identity: ActorIdentity
    display: str


@inject
@singleton
@dataclass
class SubscriptionService:
    """Subscribing an Organization to a paid Tier, whichever provider takes the payment.

    Activation puts the Organization on the Tier, ends a trial, grants the Tier's one-time
    credit (once per Organization) and the first period's allowance. Each period's end
    expires what is left of its allowance, then renews or ends the subscription; ending
    drops the Organization to Free and holds what Free doesn't cover.
    """

    repository: SubscriptionRepository
    tiers: TierRepository
    providers: SubscriptionProviders
    organizations: OrganizationRepository
    organization_service: OrganizationService
    organization_lookup: OrganizationLookupService
    budgets: OrganizationLlmBudgetService
    holds: TierHoldService
    permission_policy: PermissionPolicy
    event_delivery_dispatcher: EventDeliveryDispatcher
    billing_settings: BillingSettingsRepository
    config: Config

    # --- what an Owner does ------------------------------------------------------------

    def provider(self) -> SubscriptionProvider | None:
        """The provider that takes new subscriptions, or None when none is set up."""
        return self.providers.active()

    def available(self) -> bool:
        return self.providers.paid_tiers_purchasable()

    def get(self, organization_id: UUID, context: CurrentUserContext) -> SubscriptionRead | None:
        self._require_billing(context, organization_id)
        return self.read(organization_id)

    def preview(self, organization_id: UUID, tier_key: str, context: CurrentUserContext) -> TierHoldPreviewRead:
        """What moving to `tier_key` would put on hold: Free, where a cancellation ends, or
        an offered paid Tier to switch to."""
        self._require_billing(context, organization_id)
        tier = next(
            (
                tier
                for tier in self.tiers.list_all()
                if tier.key == tier_key
                and (tier.key == FREE_TIER_KEY or (tier.enabled and tier.activation == TierActivation.PAID))
            ),
            None,
        )
        if tier is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That tier isn't offered.")
        return self.holds.preview(organization_id, tier)

    def read(self, organization_id: UUID) -> SubscriptionRead | None:
        subscription = self.repository.live_for(organization_id)
        return self._read(subscription) if subscription is not None else None

    def start(
        self,
        organization_id: UUID,
        tier_key: str,
        context: CurrentUserContext,
        *,
        return_to: str = "billing",
    ) -> SubscriptionStartRead:
        """Subscribe to a paid Tier, or move a live subscription to another one."""
        self._require_billing(context, organization_id)
        provider = self.provider()
        if provider is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscriptions aren't available.")
        tier = next(
            (
                tier
                for tier in self.tiers.list_offered()
                if tier.key == tier_key and tier.activation == TierActivation.PAID
            ),
            None,
        )
        if tier is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That tier isn't offered.")
        organization = self.organizations.get(organization_id)
        if organization is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
        if not organization.runs_on_credit:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This organization's spend is set by the platform, so it doesn't subscribe.",
            )
        if organization.tier_assigned_by_platform:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A platform administrator chose this organization's tier. Contact them to change it.",
            )
        actor = self._actor(context, organization_id)
        live = self.repository.live_for(organization_id)
        if live is not None:
            return SubscriptionStartRead(outcome="active", subscription=self._change_tier(live, tier, actor))
        buyer = Buyer(
            organization_id=organization_id,
            organization_name=organization.name,
            email=context.user.email,
            return_url=(
                f"{self.config.web_app_url.rstrip('/')}/onboarding"
                if return_to == "onboarding"
                else self._billing_url(organization_id)
            ),
        )
        with _provider_errors():
            begun = provider.begin(buyer, tier)
        if not begun.activate_now:
            return SubscriptionStartRead(outcome="redirect", redirect_url=begun.redirect_url)
        now = datetime.now(UTC)
        subscription = self.activate(
            organization_id,
            tier,
            provider=provider.key,
            provider_subscription_id=begun.provider_subscription_id,
            period_start=now,
            period_end=now + timedelta(days=MOCK_PERIOD_DAYS),
            actor=actor,
        )
        return SubscriptionStartRead(outcome="active", subscription=self._read(subscription))

    def set_cancel_at_period_end(
        self, organization_id: UUID, cancel: bool, context: CurrentUserContext
    ) -> SubscriptionRead:
        """Cancel at the end of the period, or take a scheduled cancellation back."""
        self._require_billing(context, organization_id)
        live = self.repository.live_for(organization_id)
        if live is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This organization has no subscription.")
        if live.cancel_at_period_end == cancel:
            return self._read(live)
        with _provider_errors():
            self._provider_for(live).cancel_at_period_end(live, cancel)
        live.cancel_at_period_end = cancel
        if cancel:
            # A cancellation ends the subscription as it is; a scheduled downgrade goes with it.
            live.scheduled_tier_id = None
            live.provider_schedule_id = None
        actor = self._actor(context, organization_id)
        saved = self._save(
            live,
            ORGANIZATION_SUBSCRIPTION_CHANGED,
            actor,
            change="cancel_scheduled" if cancel else "cancel_withdrawn",
        )
        return self._read(saved)

    def portal(self, organization_id: UUID, context: CurrentUserContext) -> SubscriptionPortal:
        """The payment provider's page for the card, billing details and invoices."""
        self._require_billing(context, organization_id)
        live = self.repository.live_for(organization_id)
        if live is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This organization has no subscription.")
        with _provider_errors():
            url = self._provider_for(live).portal_url(live, self._billing_url(organization_id))
        if url is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This subscription has no billing page.")
        return SubscriptionPortal(url=url)

    # --- what the platform does --------------------------------------------------------

    def end_period_now(self, organization_id: UUID, context: CurrentUserContext) -> SubscriptionRead | None:
        """End the current period now, as if it had run out: for demonstrating renewal."""
        context.require_platform_admin()
        live = self.repository.live_for(organization_id)
        if live is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This organization has no subscription.")
        if not self._provider_for(live).renews_itself():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only demo subscriptions can end their period early; a payment provider renews this one.",
            )
        self.end_period(live, self._actor(context, organization_id), now=datetime.now(UTC))
        return self.read(organization_id)

    def read_for_platform(self, organization_id: UUID, context: CurrentUserContext) -> SubscriptionRead | None:
        context.require_platform_admin()
        return self.read(organization_id)

    def sweep(self, now: datetime | None = None) -> None:
        """End every period that has run out, apply holds whose choosing time is up, and stop
        any held Agent still running."""
        now = now or datetime.now(UTC)
        for subscription in self.repository.due(now):
            if not self._provider_for(subscription).renews_itself():
                # The provider reports renewals and endings itself.
                continue
            try:
                self.end_period(subscription, _Actor(_SYSTEM, _SYSTEM_DISPLAY), now=subscription.current_period_end)
            except Exception:
                logger.exception("Could not end the period of subscription %s", subscription.id)
        grace = timedelta(days=self.billing_settings.read().payment_grace_days)
        for subscription in self.repository.past_due_since_before(now - grace):
            try:
                # Out of grace: stop charging, then end it here without waiting for the provider.
                self._provider_for(subscription).end_now(subscription)
                self.finish(subscription, _Actor(_SYSTEM, "Payment grace period"))
            except Exception:
                logger.exception("Could not end past-due subscription %s", subscription.id)
        for organization_id in self.repository.holds_due(now):
            try:
                self.holds.apply(organization_id, actor=_SYSTEM, actor_display="Tier change")
                self.repository.clear_holds_due(organization_id)
            except Exception:
                logger.exception("Could not apply the holds of organization %s", organization_id)
        self.holds.stop_running_held(_SYSTEM)

    # --- what a payment provider drives --------------------------------------------------

    def activate(
        self,
        organization_id: UUID,
        tier: Tier,
        *,
        provider: SubscriptionProviderKey,
        provider_subscription_id: str | None,
        period_start: datetime,
        period_end: datetime,
        actor: _Actor,
    ) -> OrganizationSubscription:
        """The first payment landed: put the Organization on the Tier and grant its credit."""
        self.organization_service.convert_trial(organization_id, actor=actor.identity, actor_display=actor.display)
        self._set_tier(organization_id, tier, actor)
        subscription, delivery_ids = self.repository.save_with_event(
            OrganizationSubscription(
                organization_id=organization_id,
                tier_id=tier.id,
                provider=provider.value,
                provider_subscription_id=provider_subscription_id,
                current_period_start=period_start,
                current_period_end=period_end,
                period_spend_start_usd=_money(self.budgets.observed_spend(organization_id)),
            ),
            ORGANIZATION_SUBSCRIPTION_STARTED,
            actor=actor.identity,
            actor_display=actor.display,
            subject_display=self._organization_name(organization_id),
        )
        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)
        self._grant_one_time_credit(organization_id, tier, actor)
        subscription = self._grant_allowance(subscription, tier.monthly_usage_usd, actor)
        self.holds.apply(organization_id, actor=actor.identity, actor_display=actor.display)
        return subscription

    def end_period(self, subscription: OrganizationSubscription, actor: _Actor, *, now: datetime) -> None:
        """A period ran out: expire what's left of its allowance, then renew or end."""
        self._expire_allowance(subscription, actor)
        provider = self._provider_for(subscription)
        if subscription.cancel_at_period_end or not provider.renews_itself():
            self.end(subscription, actor)
            return
        if subscription.scheduled_tier_id is not None:
            subscription = self.apply_tier(subscription, self._tier(subscription.scheduled_tier_id), actor)
        self.renew(subscription, period_start=now, period_end=now + timedelta(days=MOCK_PERIOD_DAYS), actor=actor)

    def renew(
        self,
        subscription: OrganizationSubscription,
        *,
        period_start: datetime,
        period_end: datetime,
        actor: _Actor,
        paid: bool = True,
    ) -> OrganizationSubscription:
        """The next period began: start it, with a fresh allowance once it is paid for. An
        unpaid one gets its allowance when its payment lands (`set_payment_failed`)."""
        tier = self._tier(subscription.tier_id)
        subscription.current_period_start = period_start
        subscription.current_period_end = period_end
        if paid:
            subscription.status = SubscriptionStatus.ACTIVE.value
            subscription.past_due_since = None
        subscription.period_allowance_usd = Decimal(0)
        subscription.period_spend_start_usd = _money(self.budgets.observed_spend(subscription.organization_id))
        subscription = self._save(subscription, ORGANIZATION_SUBSCRIPTION_RENEWED, actor)
        if not paid:
            return subscription
        return self._grant_allowance(subscription, tier.monthly_usage_usd, actor)

    def end(self, subscription: OrganizationSubscription, actor: _Actor) -> None:
        """The subscription is over: drop to Free, keeping the credit, and hold what Free
        doesn't cover."""
        subscription.status = SubscriptionStatus.CANCELED.value
        subscription.canceled_at = datetime.now(UTC)
        self._save(subscription, ORGANIZATION_SUBSCRIPTION_ENDED, actor)
        free = self._tier(self.tiers.system_tier_id(FREE_TIER_KEY))
        self._set_tier(subscription.organization_id, free, actor)
        self.holds.apply(subscription.organization_id, actor=actor.identity, actor_display=actor.display)

    def finish(self, subscription: OrganizationSubscription, actor: _Actor) -> None:
        """The provider ended it: expire what's left of the period's allowance, then end it.
        Nothing happens to one already ended."""
        if subscription.status == SubscriptionStatus.CANCELED.value:
            return
        self._expire_allowance(subscription, actor)
        self.end(subscription, actor)

    def renew_period(
        self,
        subscription: OrganizationSubscription,
        *,
        period_start: datetime,
        period_end: datetime,
        actor: _Actor,
        paid: bool,
    ) -> OrganizationSubscription:
        """The provider moved to a new period: expire the last one's allowance, then start it."""
        self._expire_allowance(subscription, actor)
        return self.renew(subscription, period_start=period_start, period_end=period_end, actor=actor, paid=paid)

    def apply_tier(self, subscription: OrganizationSubscription, tier: Tier, actor: _Actor) -> OrganizationSubscription:
        """The subscription moved to another Tier: a scheduled downgrade took effect, or the
        change was made at the provider. A bigger Tier tops the period's allowance up."""
        subscription.scheduled_tier_id = None
        subscription.provider_schedule_id = None
        if subscription.tier_id == tier.id:
            return self.repository.save(subscription)
        current = self._tier(subscription.tier_id)
        if tier.price_usd > current.price_usd:
            self._switch(subscription, tier, actor)
            return self._refreshed(subscription)
        subscription.tier_id = tier.id
        subscription = self._save(subscription, ORGANIZATION_SUBSCRIPTION_CHANGED, actor, change="tier")
        self._set_tier(subscription.organization_id, tier, actor)
        self.holds.apply(subscription.organization_id, actor=actor.identity, actor_display=actor.display)
        return subscription

    def set_payment_failed(
        self, subscription: OrganizationSubscription, failed: bool, actor: _Actor
    ) -> OrganizationSubscription:
        """A renewal payment failed, or a failed one was paid after all. The Tier is kept
        through the payment grace period."""
        past_due = subscription.status == SubscriptionStatus.PAST_DUE.value
        if failed == past_due or subscription.status == SubscriptionStatus.CANCELED.value:
            return subscription
        subscription.status = (SubscriptionStatus.PAST_DUE if failed else SubscriptionStatus.ACTIVE).value
        subscription.past_due_since = datetime.now(UTC) if failed else None
        subscription = self._save(
            subscription,
            ORGANIZATION_SUBSCRIPTION_CHANGED,
            actor,
            change="payment_failed" if failed else "payment_recovered",
        )
        if not failed and subscription.period_allowance_usd == 0:
            # The period it couldn't pay for is paid now: its allowance arrives.
            tier = self._tier(subscription.tier_id)
            subscription = self._grant_allowance(subscription, tier.monthly_usage_usd, actor)
        return subscription

    def note_cancel_at_period_end(
        self, subscription: OrganizationSubscription, cancel: bool, actor: _Actor
    ) -> OrganizationSubscription:
        """The provider scheduled or withdrew a cancellation, from its own pages."""
        if subscription.cancel_at_period_end == cancel:
            return subscription
        subscription.cancel_at_period_end = cancel
        if cancel:
            subscription.scheduled_tier_id = None
            subscription.provider_schedule_id = None
        return self._save(
            subscription,
            ORGANIZATION_SUBSCRIPTION_CHANGED,
            actor,
            change="cancel_scheduled" if cancel else "cancel_withdrawn",
        )

    # --- inside ----------------------------------------------------------------------

    def _change_tier(self, live: OrganizationSubscription, tier: Tier, actor: _Actor) -> SubscriptionRead:
        """A bigger Tier applies at once and is charged for the rest of the period; a smaller
        one takes over when the period ends. Choosing the current Tier again keeps it, dropping
        a scheduled downgrade."""
        provider = self._provider_for(live)
        if live.scheduled_tier_id == tier.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=f"You're already moving to {tier.name} at renewal."
            )
        if live.tier_id == tier.id:
            if live.scheduled_tier_id is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"You're already on {tier.name}.")
            with _provider_errors():
                provider.cancel_scheduled_change(live)
            live.scheduled_tier_id = None
            live.provider_schedule_id = None
            return self._read(self._save(live, ORGANIZATION_SUBSCRIPTION_CHANGED, actor, change="downgrade_withdrawn"))
        current = self._tier(live.tier_id)
        if live.cancel_at_period_end:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Keep your subscription before switching tiers: it's set to end.",
            )
        if tier.price_usd > current.price_usd:
            with self.repository.provider_lock(live.provider_subscription_id), _provider_errors():
                provider.upgrade_now(live, tier)
                live = self._refreshed(live)
                live.scheduled_tier_id = None
                live.provider_schedule_id = None
                return self._switch(live, tier, actor)
        with _provider_errors():
            schedule_id = provider.schedule_change(live, tier)
        live.scheduled_tier_id = tier.id
        live.provider_schedule_id = schedule_id
        return self._read(self._save(live, ORGANIZATION_SUBSCRIPTION_CHANGED, actor, change="downgrade_scheduled"))

    def _refreshed(self, subscription: OrganizationSubscription) -> OrganizationSubscription:
        return self.repository.get(subscription.id) or subscription

    def _billing_url(self, organization_id: UUID) -> str:
        return f"{self.config.web_app_url.rstrip('/')}/dashboard/{organization_id}/billing"

    def _switch(self, subscription: OrganizationSubscription, tier: Tier, actor: _Actor) -> SubscriptionRead:
        """Move to another paid Tier at once. A bigger allowance tops this period up to it;
        a smaller one takes nothing back."""
        subscription.tier_id = tier.id
        subscription = self._save(subscription, ORGANIZATION_SUBSCRIPTION_CHANGED, actor, change="tier")
        self._set_tier(subscription.organization_id, tier, actor)
        top_up = tier.monthly_usage_usd - subscription.period_allowance_usd
        if top_up > 0:
            subscription = self._grant_allowance(subscription, top_up, actor, reference_suffix=f":{tier.key}")
        self.holds.apply(subscription.organization_id, actor=actor.identity, actor_display=actor.display)
        return self._read(subscription)

    def _set_tier(self, organization_id: UUID, tier: Tier, actor: _Actor) -> None:
        result = self.tiers.assign_with_event(
            organization_id, tier, actor=actor.identity, actor_display=actor.display, by_platform=False
        )
        if result is not None:
            self.event_delivery_dispatcher.enqueue_immediate(result[1])

    def _grant_one_time_credit(self, organization_id: UUID, tier: Tier, actor: _Actor) -> None:
        """Once per Organization: one that had Free's trial credit already had its share."""
        if tier.one_time_credit_usd <= 0:
            return
        already = any(
            grant.kind in (CreditGrantKind.TRIAL, CreditGrantKind.TIER_CREDIT)
            for grant in self.organization_lookup.list_credit_grants(organization_id)
        )
        if already:
            return
        self.budgets.grant_credit(
            organization_id,
            CreditGrantCreate(
                kind=CreditGrantKind.TIER_CREDIT,
                credit_usd=tier.one_time_credit_usd,
                external_ref=f"tier-credit:{organization_id}",
            ),
            actor=actor.identity,
            actor_display=actor.display,
        )

    def _grant_allowance(
        self,
        subscription: OrganizationSubscription,
        amount: Decimal,
        actor: _Actor,
        *,
        reference_suffix: str = "",
    ) -> OrganizationSubscription:
        if amount <= 0:
            return subscription
        granted = self.budgets.grant_credit(
            subscription.organization_id,
            CreditGrantCreate(
                kind=CreditGrantKind.ALLOWANCE,
                credit_usd=amount,
                external_ref=(
                    f"allowance:{subscription.id}:{subscription.current_period_start.isoformat()}{reference_suffix}"
                ),
            ),
            actor=actor.identity,
            actor_display=actor.display,
        )
        if not granted:
            return subscription
        subscription.period_allowance_usd += amount
        # The grant itself is the audit record of the allowance.
        return self.repository.save(subscription)

    def _expire_allowance(self, subscription: OrganizationSubscription, actor: _Actor) -> None:
        """What's left of this period's allowance expires; purchased and one-time credit
        stay. Spend is counted against the allowance first."""
        left = self._allowance_left(subscription)
        if left <= 0:
            return
        self.budgets.grant_credit(
            subscription.organization_id,
            CreditGrantCreate(
                kind=CreditGrantKind.ALLOWANCE_EXPIRY,
                credit_usd=-left,
                external_ref=f"allowance-expiry:{subscription.id}:{subscription.current_period_start.isoformat()}",
            ),
            actor=actor.identity,
            actor_display=actor.display,
        )

    def _allowance_left(self, subscription: OrganizationSubscription) -> Decimal:
        spend = self.budgets.observed_spend(subscription.organization_id)
        used = max(Decimal(0), _money(spend) - subscription.period_spend_start_usd)
        left = subscription.period_allowance_usd - used
        return max(Decimal(0), left).quantize(_CENT, rounding=ROUND_HALF_UP)

    def _save(
        self, subscription: OrganizationSubscription, event_name: str, actor: _Actor, *, change: str | None = None
    ) -> OrganizationSubscription:
        saved, delivery_ids = self.repository.save_with_event(
            subscription,
            event_name,
            actor=actor.identity,
            actor_display=actor.display,
            subject_display=self._organization_name(subscription.organization_id),
            details={"change": change},
        )
        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)
        return saved

    def _read(self, subscription: OrganizationSubscription) -> SubscriptionRead:
        tier = self._tier(subscription.tier_id)
        scheduled = self._tier(subscription.scheduled_tier_id) if subscription.scheduled_tier_id else None
        grace_ends_at = (
            subscription.past_due_since + timedelta(days=self.billing_settings.read().payment_grace_days)
            if subscription.past_due_since
            else None
        )
        return SubscriptionRead(
            id=subscription.id,
            tier=OrganizationTierRead.model_validate(tier),
            scheduled_tier=OrganizationTierRead.model_validate(scheduled) if scheduled else None,
            past_due_since=subscription.past_due_since,
            grace_ends_at=grace_ends_at,
            manageable=subscription.provider == SubscriptionProviderKey.STRIPE.value,
            status=SubscriptionStatus(subscription.status),
            provider=SubscriptionProviderKey(subscription.provider),
            current_period_start=subscription.current_period_start,
            current_period_end=subscription.current_period_end,
            cancel_at_period_end=subscription.cancel_at_period_end,
            allowance_usd=float(subscription.period_allowance_usd),
            allowance_remaining_usd=float(self._allowance_left(subscription)),
        )

    def _tier(self, tier_id: UUID) -> Tier:
        tier = self.tiers.get(tier_id)
        if tier is None:
            raise RuntimeError(f"Tier {tier_id} is missing")
        return tier

    def _provider_for(self, subscription: OrganizationSubscription) -> SubscriptionProvider:
        return self.providers.for_key(subscription.provider)

    def _organization_name(self, organization_id: UUID) -> str:
        return self.organization_lookup.get_name(organization_id)

    def _actor(self, context: CurrentUserContext, organization_id: UUID) -> _Actor:
        return _Actor(resolve_actor_identity(context, organization_id), context.user.full_name or context.user.email)

    def _require_billing(self, context: CurrentUserContext, organization_id: UUID) -> None:
        self.permission_policy.require(
            context,
            organization_id,
            PermissionKey.BILLING_MANAGE,
            detail="You don't have access to this organization's billing.",
        )


class _provider_errors:
    """A provider's failure as the answer the Owner sees: a declined card says so; anything
    else is a temporary outage to try again after."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, kind, error, traceback) -> bool:
        if isinstance(error, PaymentDeclined):
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(error)) from error
        if isinstance(error, PaymentProviderUnavailable | StripeNotConfigured):
            logger.warning("Subscription provider failed: %s", error)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_UNAVAILABLE) from error
        return False
