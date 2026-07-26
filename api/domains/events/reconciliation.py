import argparse
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from api.domains.events.constants import (
    EVENT_DELIVERY_PROCESSING_STALE_SECONDS,
    EVENT_DELIVERY_RECONCILIATION_BATCH_SIZE,
    EVENT_DELIVERY_RECONCILIATION_ENQUEUED_STALE_SECONDS,
    EVENT_DELIVERY_RECONCILIATION_MAX_RUNTIME_SECONDS,
    EVENT_DELIVERY_RECONCILIATION_PENDING_GRACE_SECONDS,
    EVENT_DELIVERY_RECONCILIATION_PUBLISH_CONCURRENCY,
)
from api.domains.events.models import EventDelivery
from api.domains.events.repository import bound_delivery_error
from api.domains.events.transport import TransportMetadata

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EventDeliveryReconciliationResult:
    scanned: int = 0
    published: int = 0
    failed: int = 0


class EventDeliveryReconciliationRepository(Protocol):
    def list_reconciliation_candidates(
        self,
        *,
        pending_created_before: datetime,
        enqueued_before: datetime,
        processing_claimed_before: datetime,
        limit: int,
        skip_locked: bool = True,
    ) -> list[EventDelivery]: ...

    def mark_delivery_enqueued(self, delivery_id: UUID) -> EventDelivery | None: ...


class EventDeliveryReconciliationTransport(Protocol):
    def enqueue(self, delivery_id: UUID, *, metadata: TransportMetadata | None = None) -> None: ...


@dataclass
class EventDeliveryReconciler:
    repository: EventDeliveryReconciliationRepository
    transport: EventDeliveryReconciliationTransport

    def run_once(self) -> EventDeliveryReconciliationResult:
        started = time.monotonic()
        candidates = self._load_candidates()
        if not candidates:
            return EventDeliveryReconciliationResult()

        max_runtime = EVENT_DELIVERY_RECONCILIATION_MAX_RUNTIME_SECONDS
        publish_concurrency = EVENT_DELIVERY_RECONCILIATION_PUBLISH_CONCURRENCY
        published = 0
        failed = 0
        with ThreadPoolExecutor(max_workers=publish_concurrency) as executor:
            futures = {
                executor.submit(self._publish_candidate, candidate.id, started, max_runtime): candidate
                for candidate in candidates
                if time.monotonic() - started < max_runtime
            }
            for future in as_completed(futures):
                if future.result():
                    published += 1
                else:
                    failed += 1
        return EventDeliveryReconciliationResult(scanned=len(candidates), published=published, failed=failed)

    def _load_candidates(self) -> list[EventDelivery]:
        now = datetime.now(UTC)
        return self.repository.list_reconciliation_candidates(
            pending_created_before=now - timedelta(seconds=EVENT_DELIVERY_RECONCILIATION_PENDING_GRACE_SECONDS),
            enqueued_before=now - timedelta(seconds=EVENT_DELIVERY_RECONCILIATION_ENQUEUED_STALE_SECONDS),
            processing_claimed_before=now - timedelta(seconds=EVENT_DELIVERY_PROCESSING_STALE_SECONDS),
            limit=EVENT_DELIVERY_RECONCILIATION_BATCH_SIZE,
        )

    def _publish_candidate(self, delivery_id: UUID, started: float, max_runtime: int) -> bool:
        if time.monotonic() - started >= max_runtime:
            return False
        try:
            self.transport.enqueue(delivery_id, metadata={"source": "reconciliation"})
            self.repository.mark_delivery_enqueued(delivery_id)
            return True
        except Exception as exc:
            logger.warning(
                "Event Delivery reconciliation publish failed for %s: %s",
                delivery_id,
                bound_delivery_error(exc),
            )
            return False


def build_reconciler() -> EventDeliveryReconciler:
    from api.core.utils import create_injector

    injector = create_injector()
    return injector.get(EventDeliveryReconciler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Republish stale or unpublished Event Deliveries.")
    parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = build_reconciler().run_once()
    logger.info(
        "Event Delivery reconciliation finished: scanned=%s published=%s failed=%s",
        result.scanned,
        result.published,
        result.failed,
    )


if __name__ == "__main__":
    main()
