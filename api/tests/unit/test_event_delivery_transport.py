from typing import Any, cast
from uuid import uuid4

import pytest

from api.core.config import get_config
from api.domains.events.transport import (
    EventDeliveryTransport,
    EventDeliveryTransportError,
    safe_transport_metadata,
)


class FakeActor:
    def __init__(self):
        self.calls = []

    def send_with_options(self, **kwargs):
        self.calls.append(kwargs)


def test_transport_enqueue_sends_only_delivery_id_and_safe_metadata(monkeypatch):
    from api import worker_app

    actor = FakeActor()
    monkeypatch.setattr(worker_app, "event_delivery_actor", actor)
    delivery_id = uuid4()
    correlation_id = str(uuid4())

    EventDeliveryTransport(get_config()).enqueue(
        delivery_id,
        metadata={"correlation_id": correlation_id, "source": "immediate"},
    )

    assert len(actor.calls) == 1
    call = actor.calls[0]
    assert call["args"] == (str(delivery_id), {"correlation_id": correlation_id, "source": "immediate"})
    assert call["on_retry_exhausted"] == "event_delivery_retry_exhausted"
    assert "max_retries" in call
    assert "min_backoff" in call
    assert "max_backoff" in call


def test_transport_rejects_authoritative_or_unsafe_metadata():
    with pytest.raises(EventDeliveryTransportError, match="Unsupported"):
        safe_transport_metadata({"handler_name": "audit.projection"})

    with pytest.raises(EventDeliveryTransportError, match="Unsupported"):
        safe_transport_metadata(cast(Any, {"source": {"nested": "not-safe"}}))
