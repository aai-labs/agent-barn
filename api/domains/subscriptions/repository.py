from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlalchemy import text
from sqlmodel import Session, col, select

from api.domains.events import ActorIdentity, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import EVENT_REGISTRY
from api.domains.events.repository import OutboxMessageRepository
from api.domains.organizations.models import Organization
from api.domains.subscriptions.models import OrganizationSubscription, SubscriptionStatus
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

# The Organizations whose subscription lock this context holds.
_held_locks: ContextVar[frozenset[UUID]] = ContextVar("subscription_locks", default=frozenset())


@inject
@singleton
@dataclass
class SubscriptionRepository:
    """Subscriptions and their audit Events, committed together."""

    delegate: PostgresRepositoryDelegate
    outbox_repository: OutboxMessageRepository

    def live_for(self, organization_id: UUID) -> OrganizationSubscription | None:
        """The Organization's subscription that hasn't been cancelled, if any."""
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(OrganizationSubscription).where(
                    col(OrganizationSubscription.organization_id) == organization_id,
                    col(OrganizationSubscription.status) != SubscriptionStatus.CANCELED.value,
                )
            ).first()

    def due(self, now: datetime) -> list[OrganizationSubscription]:
        """Live subscriptions whose period has ended."""
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(OrganizationSubscription)
                    .where(
                        col(OrganizationSubscription.status) != SubscriptionStatus.CANCELED.value,
                        col(OrganizationSubscription.current_period_end) <= now,
                    )
                    .order_by(col(OrganizationSubscription.current_period_end))
                ).all()
            )

    def holds_due(self, now: datetime) -> list[UUID]:
        """Organizations whose time to choose what to keep has run out."""
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(Organization.id).where(
                        col(Organization.tier_holds_due_at).is_not(None), col(Organization.tier_holds_due_at) <= now
                    )
                ).all()
            )

    def clear_holds_due(self, organization_id: UUID) -> None:
        with Session(self.delegate.engine) as session:
            organization = session.get(Organization, organization_id)
            if organization is not None and organization.tier_holds_due_at is not None:
                organization.tier_holds_due_at = None
                session.add(organization)
                session.commit()

    def get(self, subscription_id: UUID) -> OrganizationSubscription | None:
        with Session(self.delegate.engine) as session:
            return session.get(OrganizationSubscription, subscription_id)

    def by_provider_reference(self, provider: str, reference: str) -> OrganizationSubscription | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(OrganizationSubscription).where(
                    col(OrganizationSubscription.provider) == provider,
                    col(OrganizationSubscription.provider_subscription_id) == reference,
                )
            ).first()

    def past_due_since_before(self, cutoff: datetime) -> list[OrganizationSubscription]:
        """Live subscriptions whose payment has been failing since before `cutoff`."""
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(OrganizationSubscription).where(
                        col(OrganizationSubscription.status) == SubscriptionStatus.PAST_DUE.value,
                        col(OrganizationSubscription.past_due_since) <= cutoff,
                    )
                ).all()
            )

    def unactivated(self) -> list[OrganizationSubscription]:
        """Live subscriptions whose activation didn't finish."""
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(OrganizationSubscription).where(
                        col(OrganizationSubscription.status) != SubscriptionStatus.CANCELED.value,
                        col(OrganizationSubscription.activated_at).is_(None),
                    )
                ).all()
            )

    @contextmanager
    def organization_lock(self, organization_id: UUID) -> Iterator[None]:
        """Held while an Organization's subscription is changed, so an Owner's change, a
        platform assignment, the sweep and the provider's events apply one at a time.

        A transaction-level lock in a transaction held open on its own connection, so a
        transaction-pooling proxy keeps it on one server connection; it is released when the
        block ends, however it ends. Taking it again inside the block doesn't wait.
        """
        held = _held_locks.get()
        if organization_id in held:
            yield
            return
        with self.delegate.engine.connect() as connection, connection.begin():
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"subscription:{organization_id}"}
            )
            token = _held_locks.set(held | {organization_id})
            try:
                yield
            finally:
                _held_locks.reset(token)

    def save(self, subscription: OrganizationSubscription) -> OrganizationSubscription:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            subscription.updated_at = datetime.now(UTC)
            subscription = session.merge(subscription)
            session.commit()
            session.refresh(subscription)
            return subscription

    def save_with_event(
        self,
        subscription: OrganizationSubscription,
        event_name: str,
        *,
        actor: ActorIdentity,
        actor_display: str,
        subject_display: str,
        details: Mapping[str, object] | None = None,
    ) -> tuple[OrganizationSubscription, list[UUID]]:
        """Store the subscription and stage its audit Event in the same commit."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            subscription.updated_at = datetime.now(UTC)
            subscription = session.merge(subscription)
            session.flush()
            event = EVENT_REGISTRY.build_event(
                event_name=event_name,
                schema_version=1,
                occurred_at=datetime.now(UTC),
                organization_id=subscription.organization_id,
                actor=actor,
                subject=SubjectIdentity(
                    type=SubjectIdentityType.ORGANIZATION,
                    id=subscription.organization_id,
                    organization_id=subscription.organization_id,
                ),
                correlation_id=uuid4(),
                payload={
                    "organization_id": subscription.organization_id,
                    "subscription_id": subscription.id,
                    "tier_id": subscription.tier_id,
                    "provider": subscription.provider,
                    "status": subscription.status,
                    "current_period_end": subscription.current_period_end,
                    "cancel_at_period_end": subscription.cancel_at_period_end,
                    "actor_display": actor_display,
                    "subject_display": subject_display,
                    **(details or {}),
                },
            )
            self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
            delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            session.refresh(subscription)
            return subscription, delivery_ids
