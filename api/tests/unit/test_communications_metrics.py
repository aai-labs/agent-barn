from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

from api.domains.communications.metrics import (
    CONNECTION_STATUS,
    DELIVERY_LATENCY,
    DELIVERY_OUTCOMES,
    OLDEST_QUEUED_AGE,
    POLICY_DISPOSITIONS,
    QUEUE_DEPTH,
    record_delivery_outcome,
    record_policy_disposition,
)
from api.domains.communications.models import (
    CommunicationDelivery,
    CommunicationDeliveryStatus,
    CommunicationDirection,
    CommunicationPolicyDisposition,
)


def test_communication_metrics_have_no_resource_identity_labels() -> None:
    assert CONNECTION_STATUS._labelnames == ("status",)
    assert DELIVERY_OUTCOMES._labelnames == ("direction", "outcome")
    assert QUEUE_DEPTH._labelnames == ("direction",)
    assert OLDEST_QUEUED_AGE._labelnames == ("direction",)
    assert DELIVERY_LATENCY._labelnames == ("direction", "outcome")
    assert POLICY_DISPOSITIONS._labelnames == ("disposition",)


def test_delivery_and_policy_metrics_record_bounded_outcomes() -> None:
    delivery = cast(
        CommunicationDelivery,
        SimpleNamespace(
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationDeliveryStatus.SUCCEEDED,
            claimed_at=datetime.now(UTC) - timedelta(milliseconds=125),
            completed_at=datetime.now(UTC),
        ),
    )
    outcome = DELIVERY_OUTCOMES.labels(direction="outbound", outcome="succeeded")
    before = outcome._value.get()

    record_delivery_outcome(delivery)
    record_policy_disposition(CommunicationPolicyDisposition.MENTION_REQUIRED)

    assert outcome._value.get() == before + 1
    assert POLICY_DISPOSITIONS.labels(disposition="mention_required")._value.get() >= 1
