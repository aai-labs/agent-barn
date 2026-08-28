from datetime import UTC, datetime
from uuid import uuid4

import pytest
from hamcrest import assert_that, equal_to

from api.domains.communications.models import CommunicationJournalEntry, CommunicationJournalStage
from api.domains.communications.operations import CommunicationOperationalRepository


def test_safe_error_summary_keeps_only_known_operational_messages() -> None:
    assert_that(
        CommunicationOperationalRepository.safe_error_summary("Communication Connection is unavailable"),
        equal_to("Communication Connection is unavailable"),
    )


@pytest.mark.parametrize(
    "provider_error",
    [
        "Provider rejected the request with status 409",
        "message body: customer email and private response",
        "request trace value opaque-value",
    ],
)
def test_safe_error_summary_redacts_provider_details(provider_error: str) -> None:
    assert_that(
        CommunicationOperationalRepository.safe_error_summary(provider_error),
        equal_to("Provider error details were redacted"),
    )


def test_journal_read_redacts_legacy_error_values() -> None:
    entry = CommunicationJournalEntry(
        organization_id=uuid4(),
        agent_id=uuid4(),
        connection_id=uuid4(),
        occurred_at=datetime.now(UTC),
        stage=CommunicationJournalStage.CONNECTION_ERROR,
        error_code="authorization-token",
        error_summary="provider rejected a bearer token containing customer data",
    )

    projected = CommunicationOperationalRepository._journal_read(
        entry,
        direction=None,
        delivery_status=None,
        delivery=None,
    )

    assert_that(projected.error_code, equal_to("REDACTED"))
    assert_that(projected.error_summary, equal_to("Provider error details were redacted"))
