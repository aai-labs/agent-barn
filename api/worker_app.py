from typing import Any
from uuid import UUID

import dramatiq

from api.core.config import get_config
from api.domains.events import worker as events_worker
from api.domains.events.constants import (
    EVENT_DELIVERY_MAX_BACKOFF_MS,
    EVENT_DELIVERY_MAX_RETRIES,
    EVENT_DELIVERY_MIN_BACKOFF_MS,
    EVENT_DELIVERY_QUEUE_NAME,
    EVENT_DELIVERY_REDIS_NAMESPACE,
)
from api.domains.events.transport import safe_transport_metadata
from api.infrastructure.dramatiq import build_redis_broker

_config = get_config()
dramatiq.set_broker(build_redis_broker(url=_config.redis_url, namespace=EVENT_DELIVERY_REDIS_NAMESPACE))


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
    events_worker.process_event_delivery(UUID(delivery_id))


@dramatiq.actor(actor_name="event_delivery_retry_exhausted", queue_name=EVENT_DELIVERY_QUEUE_NAME, max_retries=0)
def event_delivery_retry_exhausted(message: dict[str, Any], metadata: dict[str, Any] | None = None) -> None:
    retries = metadata.get("retries") if isinstance(metadata, dict) else None
    events_worker.handle_retry_exhausted(message, retries=retries)
