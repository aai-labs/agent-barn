import logging
from typing import Any
from uuid import UUID

import dramatiq

from api.core.config import get_config
from api.core.utils import create_injector
from api.domains.events.constants import (
    EVENT_DELIVERY_MAX_BACKOFF_MS,
    EVENT_DELIVERY_MAX_RETRIES,
    EVENT_DELIVERY_MIN_BACKOFF_MS,
    EVENT_DELIVERY_PROCESSING_STALE_SECONDS,
    EVENT_DELIVERY_QUEUE_NAME,
)
from api.domains.events.handlers import EventHandlerRegistry
from api.domains.events.models import EventDeliveryDeadLetterReason
from api.domains.events.processor import EventDeliveryProcessor
from api.domains.events.repository import OutboxMessageRepository
from api.domains.events.transport import build_event_delivery_broker, message_delivery_id, safe_transport_metadata

logger = logging.getLogger(__name__)

_config = get_config()
_broker = build_event_delivery_broker(_config)
dramatiq.set_broker(_broker)


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


@dramatiq.actor(
    actor_name="event_delivery.process",
    queue_name=EVENT_DELIVERY_QUEUE_NAME,
    max_retries=EVENT_DELIVERY_MAX_RETRIES,
    min_backoff=EVENT_DELIVERY_MIN_BACKOFF_MS,
    max_backoff=EVENT_DELIVERY_MAX_BACKOFF_MS,
    on_retry_exhausted="event_delivery_retry_exhausted",
)
def event_delivery_actor(delivery_id: str, metadata: dict[str, Any] | None = None) -> None:
    safe_transport_metadata(metadata)
    _processor().process(UUID(delivery_id))


@dramatiq.actor(actor_name="event_delivery_retry_exhausted", queue_name=EVENT_DELIVERY_QUEUE_NAME, max_retries=0)
def event_delivery_retry_exhausted(message: dict[str, Any], metadata: dict[str, Any] | None = None) -> None:
    delivery_id = message_delivery_id(message)
    if delivery_id is None:
        logger.error("Retry exhaustion callback received message without Event Delivery ID")
        return
    retries = None
    if isinstance(metadata, dict):
        retries = metadata.get("retries")
    error = f"Dramatiq retries exhausted for Event Delivery {delivery_id}"
    if retries is not None:
        error = f"{error} after {retries} retries"
    _repository().mark_delivery_dead_lettered(
        delivery_id,
        reason=EventDeliveryDeadLetterReason.RETRY_EXHAUSTED,
        error=error,
    )
