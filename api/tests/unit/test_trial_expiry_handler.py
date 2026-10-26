"""A trial whose credit has run out expires (AF-381): the budget-exhausted Event is what
says so, and the handler only records it."""

from unittest.mock import MagicMock
from uuid import uuid4

from hamcrest import assert_that, equal_to

from api.domains.events.catalog import ORGANIZATION_LLM_BUDGET_EXHAUSTED
from api.domains.organizations.event_handlers import OrganizationTrialExpiryHandler

ORG = str(uuid4())


def exhausted_event():
    return MagicMock(
        event_name=ORGANIZATION_LLM_BUDGET_EXHAUSTED,
        organization_id=ORG,
        payload={"organization_id": ORG, "threshold_percent": 100, "spend_usd": 10.0, "limit_usd": 10.0},
    )


def handler(delivery_ids):
    repository = MagicMock()
    repository.expire_trial_with_event.return_value = delivery_ids
    return OrganizationTrialExpiryHandler(repository=repository, event_delivery_dispatcher=MagicMock())


def test_running_out_of_credit_expires_the_trial_and_sends_its_event_on():
    expiry = handler(["delivery"])

    expiry.handle(exhausted_event(), MagicMock())

    assert_that(str(expiry.repository.expire_trial_with_event.call_args.args[0]), equal_to(ORG))
    expiry.event_delivery_dispatcher.enqueue_immediate.assert_called_once_with(["delivery"])


def test_only_the_exhausted_event_is_handled():
    assert_that(
        [event.event_name for event in OrganizationTrialExpiryHandler.supported_events],
        equal_to([ORGANIZATION_LLM_BUDGET_EXHAUSTED]),
    )
