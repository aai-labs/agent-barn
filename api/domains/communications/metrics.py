"""Low-cardinality Prometheus metrics for the Communications process."""

import logging
from datetime import UTC, datetime
from typing import Any

from prometheus_client import Counter, Gauge, Histogram

from api.domains.communications.models import (
    CommunicationDelivery,
    CommunicationDeliveryStatus,
    CommunicationDirection,
    CommunicationPolicyDisposition,
    ConnectionObservedStatus,
)
from api.domains.communications.operations import CommunicationOperationalRepository

logger = logging.getLogger(__name__)

CONNECTION_STATUS = Gauge(
    "agentbarn_communication_connection_status",
    "Number of Communication Connections by observed provider status",
    ["status"],
)
DELIVERY_OUTCOMES = Counter(
    "agentbarn_communication_delivery_outcomes",
    "Communication Delivery completions by direction and outcome",
    ["direction", "outcome"],
)
QUEUE_DEPTH = Gauge(
    "agentbarn_communication_queue_depth",
    "Current Communication Delivery queue depth by direction",
    ["direction"],
)
OLDEST_QUEUED_AGE = Gauge(
    "agentbarn_communication_oldest_queued_age_seconds",
    "Age of the oldest pending Communication Delivery by direction",
    ["direction"],
)
DELIVERY_LATENCY = Histogram(
    "agentbarn_communication_delivery_latency_seconds",
    "Time from Communication Delivery claim to completion",
    ["direction", "outcome"],
)
RECONNECTS = Counter(
    "agentbarn_communication_reconnects",
    "Requested Communication Connection reconnects",
)
POLICY_DISPOSITIONS = Counter(
    "agentbarn_communication_policy_dispositions",
    "Provider payload admission dispositions",
    ["disposition"],
)


def record_reconnect() -> None:
    RECONNECTS.inc()


def record_policy_disposition(disposition: CommunicationPolicyDisposition) -> None:
    POLICY_DISPOSITIONS.labels(disposition=_value(disposition)).inc()


def record_delivery_outcome(delivery: CommunicationDelivery) -> None:
    direction = _value(delivery.direction).lower()
    status = _value(delivery.status)
    outcome = {
        CommunicationDeliveryStatus.SUCCEEDED.value: "succeeded",
        CommunicationDeliveryStatus.DEAD_LETTERED.value: "dead_lettered",
        CommunicationDeliveryStatus.CANCELLED.value: "cancelled",
        CommunicationDeliveryStatus.UNAVAILABLE.value: "unavailable",
        CommunicationDeliveryStatus.PENDING.value: "retrying",
    }.get(status, "processing")
    DELIVERY_OUTCOMES.labels(direction=direction, outcome=outcome).inc()
    if delivery.completed_at is not None and delivery.claimed_at is not None:
        DELIVERY_LATENCY.labels(direction=direction, outcome=outcome).observe(
            max(0.0, (delivery.completed_at - delivery.claimed_at).total_seconds())
        )


def refresh_communication_metrics(operations: CommunicationOperationalRepository) -> None:
    """Refresh gauges from current rows; failures leave the last scrape intact."""
    try:
        snapshot = operations.get_metrics_snapshot()
        for status in ConnectionObservedStatus:
            CONNECTION_STATUS.labels(status=status.value).set(0)
        for status, count in snapshot.connection_statuses:
            if status is not None:
                CONNECTION_STATUS.labels(status=_value(status)).set(count)
        now = datetime.now(UTC)
        for direction in CommunicationDirection:
            label = _value(direction).lower()
            QUEUE_DEPTH.labels(direction=label).set(0)
            OLDEST_QUEUED_AGE.labels(direction=label).set(0)
        for direction, count, oldest in snapshot.queued_deliveries:
            label = _value(direction).lower()
            QUEUE_DEPTH.labels(direction=label).set(count)
            if oldest is not None:
                OLDEST_QUEUED_AGE.labels(direction=label).set(max(0.0, (now - oldest).total_seconds()))
    except Exception:
        # Metrics must never interrupt the communications worker or a scrape.
        logger.warning("Failed to refresh Communications metrics", exc_info=True)
        return


def _value(value: Any) -> str:
    return str(getattr(value, "value", value))
