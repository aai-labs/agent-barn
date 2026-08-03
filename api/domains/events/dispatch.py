import logging
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.domains.auth.models import CurrentUserContext
from api.domains.events.models import ActorIdentity, ActorIdentityType
from api.domains.events.repository import OutboxMessageRepository, bound_delivery_error
from api.domains.events.transport import EventDeliveryTransport

logger = logging.getLogger(__name__)


def resolve_actor_identity(context: CurrentUserContext, organization_id: UUID) -> ActorIdentity:
    membership = context.user_organization_map.get(organization_id)
    if membership is not None:
        return ActorIdentity(
            type=ActorIdentityType.MEMBERSHIP,
            id=membership.id,
            organization_id=organization_id,
        )
    return ActorIdentity(type=ActorIdentityType.USER, id=context.user.id)


@inject
@singleton
@dataclass
class EventDeliveryDispatcher:
    transport: EventDeliveryTransport
    outbox_repository: OutboxMessageRepository

    def enqueue_immediate(self, delivery_ids: list[UUID]) -> None:
        for delivery_id in delivery_ids:
            try:
                self.transport.enqueue(delivery_id, metadata={"source": "immediate"})
                self.outbox_repository.mark_delivery_enqueued(delivery_id)
            except Exception as exc:
                logger.warning(
                    "Immediate Event Delivery enqueue failed for %s: %s",
                    delivery_id,
                    bound_delivery_error(exc),
                )
