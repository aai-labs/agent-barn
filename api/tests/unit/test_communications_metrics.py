from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

from hamcrest import assert_that, equal_to, greater_than_or_equal_to

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
    assert_that(CONNECTION_STATUS._labelnames, equal_to(("status",)))
    assert_that(DELIVERY_OUTCOMES._labelnames, equal_to(("direction", "outcome")))
    assert_that(QUEUE_DEPTH._labelnames, equal_to(("direction",)))
    assert_that(OLDEST_QUEUED_AGE._labelnames, equal_to(("direction",)))
    assert_that(DELIVERY_LATENCY._labelnames, equal_to(("direction", "outcome")))
    assert_that(POLICY_DISPOSITIONS._labelnames, equal_to(("disposition",)))


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

    assert_that(outcome._value.get(), equal_to(before + 1))
    assert_that(
        POLICY_DISPOSITIONS.labels(disposition="mention_required")._value.get(),
        greater_than_or_equal_to(1),
    )
