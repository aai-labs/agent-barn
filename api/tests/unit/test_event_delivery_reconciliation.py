from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from api.domains.events.constants import (
    EVENT_DELIVERY_PROCESSING_STALE_SECONDS,
    EVENT_DELIVERY_RECONCILIATION_BATCH_SIZE,
    EVENT_DELIVERY_RECONCILIATION_ENQUEUED_STALE_SECONDS,
    EVENT_DELIVERY_RECONCILIATION_PENDING_GRACE_SECONDS,
)
from api.domains.events.models import EventDelivery, EventDeliveryStatus
from api.domains.events.reconciliation import EventDeliveryReconciler


class FakeRepository:
    def __init__(self, candidates):
        self.candidates = candidates
        self.selection = None
        self.enqueued: list[UUID] = []

    def list_reconciliation_candidates(
        self,
        *,
        pending_created_before,
        enqueued_before,
        processing_claimed_before,
        limit,
        skip_locked=True,
    ):
        self.selection = {
            "pending_created_before": pending_created_before,
            "enqueued_before": enqueued_before,
            "processing_claimed_before": processing_claimed_before,
            "limit": limit,
            "skip_locked": skip_locked,
        }
        return self.candidates[:limit]

    def mark_delivery_enqueued(self, delivery_id):
        self.enqueued.append(delivery_id)


class FakeTransport:
    def __init__(self, fail_delivery_id=None):
        self.fail_delivery_id = fail_delivery_id
        self.published: list[tuple[UUID, dict]] = []

    def enqueue(self, delivery_id, *, metadata=None):
        if delivery_id == self.fail_delivery_id:
            raise RuntimeError("redis unavailable")
        self.published.append((delivery_id, metadata or {}))


def _delivery(status=EventDeliveryStatus.PENDING) -> EventDelivery:
    return EventDelivery(
        outbox_message_id=uuid4(),
        event_id=uuid4(),
        organization_id=uuid4(),
        handler_name="audit.projection",
        status=status,
    )


def test_reconciler_uses_default_thresholds_and_batch_limit():
    repository = FakeRepository([_delivery() for _ in range(EVENT_DELIVERY_RECONCILIATION_BATCH_SIZE + 1)])
    transport = FakeTransport()

    result = EventDeliveryReconciler(repository=repository, transport=transport).run_once()

    assert result.scanned == EVENT_DELIVERY_RECONCILIATION_BATCH_SIZE
    assert result.published == EVENT_DELIVERY_RECONCILIATION_BATCH_SIZE
    assert result.failed == 0
    assert repository.selection is not None
    selection = cast(dict[str, Any], repository.selection)
    now = datetime.now(UTC)
    assert now - selection["pending_created_before"] >= timedelta(
        seconds=EVENT_DELIVERY_RECONCILIATION_PENDING_GRACE_SECONDS - 1
    )
    assert now - selection["enqueued_before"] >= timedelta(
        seconds=EVENT_DELIVERY_RECONCILIATION_ENQUEUED_STALE_SECONDS - 1
    )
    assert now - selection["processing_claimed_before"] >= timedelta(
        seconds=EVENT_DELIVERY_PROCESSING_STALE_SECONDS - 1
    )
    assert selection["limit"] == EVENT_DELIVERY_RECONCILIATION_BATCH_SIZE


def test_reconciler_marks_each_successful_publish_and_continues_after_failures():
    failed = _delivery()
    succeeded = _delivery()
    repository = FakeRepository([failed, succeeded])
    transport = FakeTransport(fail_delivery_id=failed.id)

    result = EventDeliveryReconciler(repository=repository, transport=transport).run_once()

    assert result.scanned == 2
    assert result.published == 1
    assert result.failed == 1
    assert transport.published == [(succeeded.id, {"source": "reconciliation"})]
    assert repository.enqueued == [succeeded.id]


def test_reconciler_returns_empty_result_when_no_candidates():
    repository = FakeRepository([])
    transport = FakeTransport()

    result = EventDeliveryReconciler(repository=repository, transport=transport).run_once()

    assert result.scanned == 0
    assert result.published == 0
    assert result.failed == 0
    assert transport.published == []
    assert repository.enqueued == []
