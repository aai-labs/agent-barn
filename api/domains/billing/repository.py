from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col, select

from api.domains.billing.models import (
    BILLING_SETTINGS_SUBJECT_DISPLAY,
    BillingCheckout,
    BillingSettingsRead,
    BillingUnappliedPayment,
    OrganizationBillingCustomer,
    PlatformBillingSettings,
)
from api.domains.events import ActorIdentity, ActorIdentityType, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import (
    EVENT_REGISTRY,
    PLATFORM_BILLING_SETTINGS_CHANGED,
    PLATFORM_CREDIT_PURCHASE_UNAPPLIED,
)
from api.domains.events.models import EventScope
from api.domains.events.repository import OutboxMessageRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

# Serializes billing settings changes, including creation of the singleton row.
_BILLING_SETTINGS_LOCK = 732914108


@inject
@singleton
@dataclass
class BillingSettingsRepository:
    delegate: PostgresRepositoryDelegate
    outbox: OutboxMessageRepository

    def read(self) -> BillingSettingsRead:
        with Session(self.delegate.engine) as session:
            return self._current(session.get(PlatformBillingSettings, 1))

    @staticmethod
    def _current(row: PlatformBillingSettings | None) -> BillingSettingsRead:
        if row is None:
            return BillingSettingsRead()
        return BillingSettingsRead(
            payments_enabled=row.payments_enabled,
            min_purchase_usd=row.min_purchase_usd,
            max_purchase_usd=row.max_purchase_usd,
            purchase_fee_percent=row.purchase_fee_percent,
            updated_at=row.updated_at,
        )

    def set_settings(
        self, changes: Mapping[str, bool | float], actor_id: UUID, actor_display: str
    ) -> tuple[BillingSettingsRead, list[UUID]]:
        """Store the settings and stage one audit Event per setting that moved, in one
        commit. A setting saved at the value already in force writes nothing. Raises
        ValueError when the result would allow no purchase at all."""
        with Session(self.delegate.engine) as session:
            session.connection().execute(sa.text(f"SELECT pg_advisory_xact_lock({_BILLING_SETTINGS_LOCK})"))
            row = session.get(PlatformBillingSettings, 1)
            current = self._current(row)
            moved = [
                (setting, getattr(current, setting), value)
                for setting, value in changes.items()
                if getattr(current, setting) != value
            ]
            if row and not moved:
                return current, []
            now = datetime.now(UTC)
            stored = current.model_copy(update={**dict(changes), "updated_at": now})
            if stored.min_purchase_usd > stored.max_purchase_usd:
                raise ValueError("The smallest purchase can't be more than the largest.")
            session.merge(
                PlatformBillingSettings(
                    id=1,
                    payments_enabled=stored.payments_enabled,
                    min_purchase_usd=stored.min_purchase_usd,
                    max_purchase_usd=stored.max_purchase_usd,
                    purchase_fee_percent=stored.purchase_fee_percent,
                    updated_at=now,
                    updated_by=actor_id,
                )
            )
            correlation_id = uuid4()
            event_ids = []
            for setting, previous, value in moved:
                event = EVENT_REGISTRY.build_event(
                    event_name=PLATFORM_BILLING_SETTINGS_CHANGED,
                    schema_version=1,
                    occurred_at=now,
                    event_scope=EventScope.PLATFORM,
                    organization_id=None,
                    actor=ActorIdentity(type=ActorIdentityType.USER, id=actor_id),
                    subject=SubjectIdentity(type=SubjectIdentityType.SYSTEM, id="platform-billing-settings"),
                    correlation_id=correlation_id,
                    payload={
                        "actor_user_id": actor_id,
                        "actor_display": actor_display,
                        "subject_display": BILLING_SETTINGS_SUBJECT_DISPLAY,
                        "setting": setting,
                        # Booleans stay booleans; amounts are numbers.
                        "previous": previous if isinstance(previous, bool) else float(previous),
                        "current": value if isinstance(value, bool) else float(value),
                    },
                )
                self.outbox.stage(session=session, registry=EVENT_REGISTRY, event=event)
                event_ids.append(event.event_id)
            ids = list(session.exec(select(EventDelivery.id).where(col(EventDelivery.event_id).in_(event_ids))))
            session.commit()
            return stored, ids


@inject
@singleton
@dataclass
class BillingCustomerRepository:
    delegate: PostgresRepositoryDelegate

    def get_customer_id(self, organization_id: UUID) -> str | None:
        with Session(self.delegate.engine) as session:
            row = session.get(OrganizationBillingCustomer, organization_id)
            return row.stripe_customer_id if row else None

    def save_customer_id(self, organization_id: UUID, stripe_customer_id: str) -> str:
        """Store the Organization's Customer, or return the one stored first when two
        purchases created one at the same moment."""
        with Session(self.delegate.engine) as session:
            session.connection().execute(
                insert(OrganizationBillingCustomer)
                .values(
                    organization_id=organization_id,
                    stripe_customer_id=stripe_customer_id,
                    created_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(index_elements=["organization_id"])
            )
            session.commit()
            row = session.get(OrganizationBillingCustomer, organization_id)
            return row.stripe_customer_id if row else stripe_customer_id


@inject
@singleton
@dataclass
class UnappliedPurchaseRepository:
    delegate: PostgresRepositoryDelegate
    outbox: OutboxMessageRepository

    def record(
        self,
        organization_name: str,
        *,
        payment_reference: str,
        credit_usd: Decimal,
        amount_paid_usd: Decimal,
        reason: str,
    ) -> list[UUID]:
        """Remember a payment no credit was granted for, and stage its platform audit
        Event; nothing new for a payment already remembered (a redelivery)."""
        with Session(self.delegate.engine) as session:
            remembered = session.connection().execute(
                insert(BillingUnappliedPayment)
                .values(payment_reference=payment_reference, created_at=datetime.now(UTC))
                .on_conflict_do_nothing(index_elements=["payment_reference"])
            )
            if not remembered.rowcount:
                return []
            event = EVENT_REGISTRY.build_event(
                event_name=PLATFORM_CREDIT_PURCHASE_UNAPPLIED,
                schema_version=1,
                occurred_at=datetime.now(UTC),
                event_scope=EventScope.PLATFORM,
                organization_id=None,
                actor=ActorIdentity(type=ActorIdentityType.SYSTEM, id="stripe"),
                subject=SubjectIdentity(type=SubjectIdentityType.SYSTEM, id=f"payment:{payment_reference}"),
                correlation_id=uuid4(),
                payload={
                    "payment_reference": payment_reference,
                    "credit_usd": float(credit_usd),
                    "amount_paid_usd": float(amount_paid_usd),
                    "reason": reason,
                    "actor_display": "Credit purchase",
                    "subject_display": organization_name,
                },
            )
            self.outbox.stage(session=session, registry=EVENT_REGISTRY, event=event)
            ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            return ids

    def includes(self, payment_reference: str) -> bool:
        with Session(self.delegate.engine) as session:
            return session.get(BillingUnappliedPayment, payment_reference) is not None


@inject
@singleton
@dataclass
class BillingCheckoutRepository:
    delegate: PostgresRepositoryDelegate

    def record(
        self,
        stripe_session_id: str,
        organization_id: UUID,
        *,
        credit_usd: Decimal,
        amount_cents: int,
        purchased_by_user_id: UUID | None,
    ) -> None:
        with Session(self.delegate.engine) as session:
            session.add(
                BillingCheckout(
                    stripe_session_id=stripe_session_id,
                    organization_id=organization_id,
                    credit_usd=credit_usd,
                    amount_cents=amount_cents,
                    purchased_by_user_id=purchased_by_user_id,
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()

    def get(self, stripe_session_id: str) -> BillingCheckout | None:
        with Session(self.delegate.engine) as session:
            return session.get(BillingCheckout, stripe_session_id)
