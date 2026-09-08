import logging
import threading
from typing import Any
from uuid import UUID

from injector import Injector

from api.core.utils import create_injector
from api.domains.events.constants import EVENT_DELIVERY_PROCESSING_STALE_SECONDS
from api.domains.events.handlers import EventHandlerRegistry
from api.domains.events.models import EventDeliveryDeadLetterReason
from api.domains.events.processor import EventDeliveryProcessor
from api.domains.events.repository import OutboxMessageRepository
from api.infrastructure.dramatiq import first_arg_as_uuid

logger = logging.getLogger(__name__)


_injector_lock = threading.Lock()
_injector: Injector | None = None


def _get_injector() -> Injector:
    """Return the process-wide injector, building it on first use.

    Dramatiq calls the actors below once per message. Building a fresh injector
    per call would build a fresh SQLAlchemy engine and connection pool per
    message, and those connections linger until GC collects the engine, which
    exhausts Postgres under load. The injector is created lazily so importing
    this module opens no database engine.
    """
    global _injector
    if _injector is None:
        with _injector_lock:
            if _injector is None:
                _injector = create_injector()
    return _injector


def reset_injector() -> None:
    """Drop the cached injector so the next call rebuilds it. Intended for tests."""
    global _injector
    with _injector_lock:
        _injector = None


def _processor() -> EventDeliveryProcessor:
    injector = _get_injector()
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
    return _get_injector().get(OutboxMessageRepository)


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
