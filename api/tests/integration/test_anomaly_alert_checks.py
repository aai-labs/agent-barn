"""The scheduled check raises an alert Event for what it newly flags (AF-464).

The contract under test:

- a check that starts Anomalies for an Agent records one alert Event naming them, in
  the same transaction as the Anomalies, so an alert can't be lost to a crash after
  that transaction commits;
- the Event goes out only after the check has classified them, so the alert can say
  how they were classified;
- an ongoing Anomaly raises no further Event, and neither does a check that flags
  nothing new;
- Hermes and OpenClaw Agents are alike.

Whether an Event becomes an email (severity, probably fine) is the handler's call.
"""

from unittest.mock import patch

import pytest
from hamcrest import assert_that, contains_inanyorder, empty, equal_to, has_entries, has_length

from api.domains.agents.models import AgentType
from api.domains.events import EventDeliveryDispatcher, OutboxMessage
from api.domains.events.catalog import AGENT_ANOMALY_FLAGGED
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.integration.test_anomaly_checks import LATER, _anomalies, _check
from api.tests.integration.test_anomaly_classification_checks import (
    _a_tool_call_spike,
    _given,
    the_decision_model_classifies,
)


def _flagged_events(context) -> list[OutboxMessage]:
    messages = context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
    return [message for message in messages if message.event_name == AGENT_ANOMALY_FLAGGED]


@pytest.mark.parametrize("agent_type", [AgentType.OPENCLAW, AgentType.HERMES])
def test_a_newly_flagged_anomaly_raises_one_alert_event_naming_it(agent_type):
    with given(_given(the_decision_model_classifies(), agent_type=agent_type)) as context:
        _a_tool_call_spike(context)

        _check(context)

        anomaly_ids = [str(anomaly.id) for anomaly in _anomalies(context)]
        assert_that(anomaly_ids, has_length(1))
        events = _flagged_events(context)
        assert_that(events, has_length(1))
        assert_that(
            events[0].payload,
            has_entries(
                organization_id=str(context.agent.organization_id),
                agent_id=str(context.agent.id),
                anomaly_ids=contains_inanyorder(*anomaly_ids),
            ),
        )
        assert_that(events[0].organization_id, equal_to(context.agent.organization_id))


def test_an_ongoing_anomaly_raises_no_further_alert_event():
    with given(_given(the_decision_model_classifies())) as context:
        _a_tool_call_spike(context)
        _check(context)

        _check(context, LATER)

        assert_that(_flagged_events(context), has_length(1))


def test_a_check_that_flags_nothing_new_raises_no_alert_event():
    with given(_given(the_decision_model_classifies())) as context:
        _check(context)

        assert_that(_anomalies(context), empty())
        assert_that(_flagged_events(context), empty())


def test_the_alert_event_goes_out_only_after_classification():
    with given(_given(the_decision_model_classifies())) as context:
        _a_tool_call_spike(context)
        classified_when_enqueued: list[bool] = []

        def enqueue(_self, delivery_ids):
            if delivery_ids:
                classified_when_enqueued.append(context.decide.called)

        with patch.object(EventDeliveryDispatcher, "enqueue_immediate", autospec=True, side_effect=enqueue):
            _check(context)

        assert_that(classified_when_enqueued, equal_to([True]))


def test_the_alert_event_survives_a_crash_after_the_anomaly_is_recorded():
    with given(_given(the_decision_model_classifies())) as context:
        _a_tool_call_spike(context)
        # Not a DecisionError: the check itself dies before it gets to send anything.
        context.decide.side_effect = RuntimeError("worker killed")

        with patch.object(EventDeliveryDispatcher, "enqueue_immediate") as enqueue:
            _check(context)

        assert_that(_anomalies(context), has_length(1))
        assert_that(_flagged_events(context), has_length(1))
        enqueue.assert_not_called()
