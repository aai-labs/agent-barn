import logging
from typing import Any
from uuid import UUID

from api.core.utils import create_injector
from api.domains.events.constants import EVENT_DELIVERY_PROCESSING_STALE_SECONDS
from api.domains.events.handlers import EventHandlerRegistry
from api.domains.events.models import EventDeliveryDeadLetterReason
from api.domains.events.processor import EventDeliveryProcessor
from api.domains.events.repository import OutboxMessageRepository
from api.infrastructure.dramatiq import first_arg_as_uuid

logger = logging.getLogger(__name__)


def _processor() -> EventDeliveryProcessor:
    injector = create_injector()
    repository = injector.get(OutboxMessageRepository)
    try:
        handlers = injector.get(EventHandlerRegistry)
    except Exception:
        handlers = EventHandlerRegistry()
    return EventDeliveryProcessor(
        repository=repository,
        handlers=handlers,
        processing_stale_seconds=EVENT_DELIVERY_PROCESSING_STALE_SECONDS,
    )


def _repository() -> OutboxMessageRepository:
    return create_injector().get(OutboxMessageRepository)


def process_event_delivery(delivery_id: UUID) -> bool:
    return _processor().process(delivery_id)


def handle_retry_exhausted(message: dict[str, Any], *, retries: int | None) -> None:
    delivery_id = first_arg_as_uuid(message)
    if delivery_id is None:
        logger.error("Retry exhaustion callback received message without Event Delivery ID")
        return
    error = f"Dramatiq retries exhausted for Event Delivery {delivery_id}"
    if retries is not None:
        error = f"{error} after {retries} retries"
    logger.warning(
        "Event Delivery dead-lettered: delivery_id=%s reason=%s retries=%s",
        delivery_id,
        EventDeliveryDeadLetterReason.RETRY_EXHAUSTED.value,
        retries,
    )
    _repository().mark_delivery_dead_lettered(
        delivery_id,
        reason=EventDeliveryDeadLetterReason.RETRY_EXHAUSTED,
        error=error,
    )
