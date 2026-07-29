from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from api.core.config import Config
from api.domains.events.constants import (
    EVENT_DELIVERY_MAX_BACKOFF_MS,
    EVENT_DELIVERY_MAX_RETRIES,
    EVENT_DELIVERY_MIN_BACKOFF_MS,
    EVENT_DELIVERY_REDIS_NAMESPACE,
)
from api.infrastructure.dramatiq import build_redis_broker

TransportMetadataValue = str | int | float | bool | None
TransportMetadata = dict[str, TransportMetadataValue]

_ALLOWED_METADATA_KEYS = frozenset({"correlation_id", "published_at", "source"})


class EventDeliveryTransportError(RuntimeError):
    pass


def safe_transport_metadata(metadata: dict[str, Any] | None = None) -> TransportMetadata:
    if metadata is None:
        return {}
    safe: TransportMetadata = {}
    for key, value in metadata.items():
        if key not in _ALLOWED_METADATA_KEYS:
            raise EventDeliveryTransportError(f"Unsupported Event Delivery transport metadata key {key}")
        if isinstance(value, datetime):
            safe[key] = value.isoformat()
        elif isinstance(value, str | int | float | bool) or value is None:
            safe[key] = value
        else:
            raise EventDeliveryTransportError(f"Unsupported Event Delivery transport metadata value for {key}")
    return safe


@dataclass
class EventDeliveryTransport:
    config: Config

    def enqueue(self, delivery_id: UUID, *, metadata: dict[str, Any] | None = None) -> None:
        from api.worker_app import event_delivery_actor

        safe_metadata = safe_transport_metadata(metadata)
        event_delivery_actor.send_with_options(
            args=(str(delivery_id), safe_metadata),
            max_retries=EVENT_DELIVERY_MAX_RETRIES,
            min_backoff=EVENT_DELIVERY_MIN_BACKOFF_MS,
            max_backoff=EVENT_DELIVERY_MAX_BACKOFF_MS,
            on_retry_exhausted="event_delivery_retry_exhausted",
        )

    def check_ready(self) -> None:
        broker = build_redis_broker(url=self.config.redis_url, namespace=EVENT_DELIVERY_REDIS_NAMESPACE)
        broker.client.ping()
