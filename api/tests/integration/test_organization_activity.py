from datetime import UTC, datetime, timedelta
from uuid import uuid7

import sqlalchemy as sa
from fastapi import status
from hamcrest import assert_that, contains_inanyorder, equal_to, has_entries

from api.domains.agent_webhooks.models import WebhookInvocationStatus
from api.domains.agents.models import AgentStatus
from api.domains.business_value.repository import DeliveryOutcomes, ValueActivityRepository
from api.domains.business_value.service import utc_bucket
from api.domains.communications.models import CommunicationDeliveryStatus, CommunicationPlatform
from api.domains.conversations.models import MessageDirection
from api.domains.costs.models import CostFilter
from api.domains.costs.repository import CostRepository
from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.domains.platform_admin.models import StatsGranularity, StatsWindow
from api.domains.rbac.policy import AuthorizationScope
from api.domains.tool_calls.models import ToolCallStatus
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.communication import (
    the_agent_is_soft_deleted,
    the_connection_is_retired,
    there_are_tool_calls,
    there_is_a_connection,
    there_is_a_message,
    there_is_a_webhook_invocation,
    there_is_an_inbound_delivery,
    there_is_an_outbound_delivery,
)
from api.tests.steps.cost import cost_records_are_clean, there_are_cost_records
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

WINDOW_START = datetime(2026, 9, 1, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 4, tzinfo=UTC)
INSIDE = WINDOW_START + timedelta(hours=12)
BEFORE_START = WINDOW_START - timedelta(microseconds=1)
SUCCEEDED = CommunicationDeliveryStatus.SUCCEEDED
DEAD_LETTERED = CommunicationDeliveryStatus.DEAD_LETTERED
UNAVAILABLE = CommunicationDeliveryStatus.UNAVAILABLE
CANCELLED = CommunicationDeliveryStatus.CANCELLED
PENDING = CommunicationDeliveryStatus.PENDING
PROCESSING = CommunicationDeliveryStatus.PROCESSING
DELIVERY_ACTIVITY_INDEX = "ix_communication_delivery_agent_direction_completed"
DELIVERY_ACTIVITY_COLUMNS = ["agent_id", "direction", "completed_at"]
MESSAGE_ACTIVITY_INDEX = "ix_agent_chat_message_agent_direction_occurred"
MESSAGE_ACTIVITY_COLUMNS = ["agent_id", "direction", "occurred_at"]
ACTIVITY_URL = "/api/v1/organizations/{organization_id}/value/activity"
WINDOW_PARAMS = {
    "from_date": "2026-09-01T00:00:00Z",
    "to_date": "2026-09-04T00:00:00Z",
    "granularity": "day",
}
BUCKETS = [
    "2026-09-01T00:00:00Z",
    "2026-09-02T00:00:00Z",
    "2026-09-03T00:00:00Z",
    "2026-09-04T00:00:00Z",
]
_ENV = set_env_variable(
    {
        "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
        "LITELLM_BASE_URL": "http://litellm:4000",
        "LITELLM_SECRET_NAME": "litellm",
        "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
        "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
    }
)

_GIVEN = [
    _ENV,
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
]

_API_GIVEN = [
    _ENV,
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    cost_records_are_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
]


def _window(granularity: StatsGranularity = StatsGranularity.DAY) -> StatsWindow:
    return StatsWindow(start=WINDOW_START, end=WINDOW_END, period=None, granularity=granularity)


def _scope(context) -> AuthorizationScope:
    return AuthorizationScope(organization_id=context.organization.id)


def _repository(context) -> ValueActivityRepository:
    return context.injector.get(ValueActivityRepository)


def _remember_agent(name: str):
    def step(context):
        if not hasattr(context, "agents"):
            context.agents = {}
        context.agents[name] = context.agent

    return step


def _there_is_another_organization_with_an_agent():
    def step(context):
        original = context.organization
        other = Organization(id=uuid7(), name="Other Organization")
        context.injector.get(OrganizationRepository).save(other)
        there_is_an_agent(name="Other Agent", organization_id=other.id, status=AgentStatus.RUNNING)(context)
        context.organization = original

    return step


def _delivered(seconds: float, *, attempt_count: int = 1, status=SUCCEEDED, completed_at: datetime = INSIDE):
    return there_is_an_inbound_delivery(
        occurred_at=completed_at - timedelta(seconds=seconds),
        status=status,
        attempt_count=attempt_count,
        created_at=completed_at - timedelta(seconds=seconds),
        completed_at=completed_at,
    )


def _index_columns(context, table: str) -> dict[str, list[str | None]]:
    inspector = sa.inspect(context.injector.get(PostgresRepositoryDelegate).engine)
    return {index["name"]: index["column_names"] for index in inspector.get_indexes(table)}


def test_activity_indexes_exist_after_migration():
    with given(_GIVEN) as context:
        with when("the migrated schema is inspected"):
            delivery_indexes = _index_columns(context, "communication_delivery")
            message_indexes = _index_columns(context, "agent_chat_message")

        with then("delivery outcomes and inbound messages can be read per Agent over a time range"):
            assert_that(delivery_indexes.get(DELIVERY_ACTIVITY_INDEX), equal_to(DELIVERY_ACTIVITY_COLUMNS))
            assert_that(message_indexes.get(MESSAGE_ACTIVITY_INDEX), equal_to(MESSAGE_ACTIVITY_COLUMNS))


def test_inbound_messages_are_counted_per_agent_inside_the_half_open_window():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(name="Web Agent"),
            _remember_agent("web"),
            there_is_a_connection(CommunicationPlatform.WEB),
            there_is_a_message(occurred_at=WINDOW_START),
            there_is_a_message(occurred_at=INSIDE),
            there_is_a_message(occurred_at=BEFORE_START),
            there_is_a_message(occurred_at=WINDOW_END),
            there_is_a_message(direction=MessageDirection.OUTBOUND, occurred_at=INSIDE),
            there_is_an_agent(name="Slack Agent"),
            _remember_agent("slack"),
            there_is_a_connection(CommunicationPlatform.SLACK),
            there_is_a_message(occurred_at=INSIDE),
            _there_is_another_organization_with_an_agent(),
            there_is_a_connection(CommunicationPlatform.WEB),
            there_is_a_message(occurred_at=INSIDE),
        ]
    ) as context:
        with when("inbound messages are counted per Agent"):
            rows = _repository(context).inbound_messages_by_agent(_window(), _scope(context))

        with then("only inbound messages from the start up to, not including, the end count, per Agent"):
            assert_that(
                rows,
                contains_inanyorder((context.agents["web"].id, 2), (context.agents["slack"].id, 1)),
            )


def test_inbound_messages_of_a_soft_deleted_agent_still_count():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(name="Retired Agent"),
            there_is_a_connection(CommunicationPlatform.SLACK),
            there_is_a_message(occurred_at=INSIDE),
            the_agent_is_soft_deleted(),
        ]
    ) as context:
        with when("inbound messages are counted per Agent"):
            rows = _repository(context).inbound_messages_by_agent(_window(), _scope(context))

        with then("the soft-deleted Agent's message is counted"):
            assert_that(rows, equal_to([(context.agent.id, 1)]))


def test_webhook_invocations_of_every_status_are_counted_per_agent_inside_the_window():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            _remember_agent("mine"),
            there_is_a_webhook_invocation(created_at=WINDOW_START),
            there_is_a_webhook_invocation(created_at=INSIDE, status=WebhookInvocationStatus.RECEIVED),
            there_is_a_webhook_invocation(created_at=INSIDE, status=WebhookInvocationStatus.DISPATCH_FAILED),
            there_is_a_webhook_invocation(created_at=BEFORE_START),
            there_is_a_webhook_invocation(created_at=WINDOW_END),
            _there_is_another_organization_with_an_agent(),
            there_is_a_webhook_invocation(created_at=INSIDE),
        ]
    ) as context:
        with when("webhook invocations are counted per Agent"):
            rows = _repository(context).webhook_invocations_by_agent(_window(), _scope(context))

        with then("every status counts once, inside the half-open window, for this Organization only"):
            assert_that(rows, equal_to([(context.agents["mine"].id, 3)]))


def test_webhook_invocations_by_bucket_share_the_spend_series_buckets():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_webhook_invocation(created_at=INSIDE),
            there_is_a_webhook_invocation(created_at=INSIDE),
            there_is_a_webhook_invocation(created_at=INSIDE + timedelta(days=2)),
        ]
    ) as context:
        window = _window()

        with when("webhook invocations are counted per bucket"):
            rows = _repository(context).webhook_invocations_by_bucket(window, _scope(context))

        with then("the buckets are exactly the spend series buckets, empty ones included"):
            spend_buckets = [
                bucket
                for bucket, _spend, _calls in context.injector.get(CostRepository).spend_series(
                    window, CostFilter(organization_id=context.organization.id)
                )
            ]
            assert_that([bucket for bucket, _count in rows], equal_to(spend_buckets))

        with then("invocations land in their UTC day"):
            assert_that([count for _bucket, count in rows], equal_to([2, 0, 1, 0]))


def test_delivery_outcomes_count_handled_statuses_and_leave_the_rest_out():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING),
            there_is_a_connection(CommunicationPlatform.WEB),
            _delivered(10),
            _delivered(10, status=DEAD_LETTERED, attempt_count=5),
            _delivered(10, status=CANCELLED),
            there_is_an_inbound_delivery(occurred_at=INSIDE),
            there_is_an_inbound_delivery(occurred_at=INSIDE, status=PROCESSING, attempt_count=1),
            there_is_an_outbound_delivery(completed_at=INSIDE),
            there_is_an_agent(name="Stopped Agent", status=AgentStatus.STOPPED),
            there_is_a_connection(CommunicationPlatform.WEB),
            there_is_an_inbound_delivery(occurred_at=INSIDE, completed_at=INSIDE),
        ]
    ) as context:
        with when("delivery outcomes are read for the Organization"):
            outcomes = _repository(context).delivery_outcomes_total(_window(), _scope(context))

        with then("SUCCEEDED, DEAD_LETTERED, and UNAVAILABLE inbound deliveries count; nothing else does"):
            assert_that(
                (outcomes.succeeded, outcomes.dead_lettered, outcomes.unavailable),
                equal_to((1, 1, 1)),
            )


def test_delivery_outcomes_use_the_half_open_window_on_completed_at():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING),
            there_is_a_connection(CommunicationPlatform.WEB),
            _delivered(10, completed_at=WINDOW_START),
            _delivered(10, completed_at=BEFORE_START),
            _delivered(10, completed_at=WINDOW_END),
        ]
    ) as context:
        with when("delivery outcomes are read for the Organization"):
            outcomes = _repository(context).delivery_outcomes_total(_window(), _scope(context))

        with then("only the delivery completed at the start counts"):
            assert_that(outcomes.succeeded, equal_to(1))


def test_the_median_covers_first_attempt_successes_only_and_interpolates():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING),
            there_is_a_connection(CommunicationPlatform.WEB),
            _delivered(10),
            _delivered(20),
            _delivered(600, attempt_count=2),
            _delivered(900, status=DEAD_LETTERED, attempt_count=5),
        ]
    ) as context:
        with when("delivery outcomes are read for the Organization"):
            outcomes = _repository(context).delivery_outcomes_total(_window(), _scope(context))

        with then("the retried success counts as succeeded"):
            assert_that(outcomes.succeeded, equal_to(3))

        with then("the median is interpolated over the two first-attempt successes"):
            assert_that(outcomes.first_attempt, equal_to(2))
            assert_that(outcomes.median_seconds, equal_to(15.0))


def test_the_median_is_null_without_deliveries():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        with when("delivery outcomes are read for the Organization"):
            outcomes = _repository(context).delivery_outcomes_total(_window(), _scope(context))

        with then("every count is zero and the median is null"):
            assert_that(outcomes, equal_to(DeliveryOutcomes()))


def test_delivery_outcomes_are_split_per_agent_and_exclude_other_organizations():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(name="Fast", status=AgentStatus.RUNNING),
            _remember_agent("fast"),
            there_is_a_connection(CommunicationPlatform.WEB),
            _delivered(4),
            there_is_an_agent(name="Slow", status=AgentStatus.RUNNING),
            _remember_agent("slow"),
            there_is_a_connection(CommunicationPlatform.EMAIL),
            _delivered(40),
            _delivered(60, status=DEAD_LETTERED, attempt_count=5),
            the_agent_is_soft_deleted(),
            _there_is_another_organization_with_an_agent(),
            there_is_a_connection(CommunicationPlatform.WEB),
            _delivered(1),
        ]
    ) as context:
        with when("delivery outcomes are read per Agent"):
            rows = dict(_repository(context).delivery_outcomes_by_agent(_window(), _scope(context)))

        with then("each Agent of this Organization has its own outcomes, the soft-deleted one included"):
            assert_that(
                rows,
                equal_to(
                    {
                        context.agents["fast"].id: DeliveryOutcomes(succeeded=1, first_attempt=1, median_seconds=4.0),
                        context.agents["slow"].id: DeliveryOutcomes(
                            succeeded=1, dead_lettered=1, first_attempt=1, median_seconds=40.0
                        ),
                    }
                ),
            )


def test_tool_calls_of_every_status_are_counted_per_agent_inside_the_window():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            _remember_agent("mine"),
            there_are_tool_calls(count=2, occurred_at=WINDOW_START),
            there_are_tool_calls(occurred_at=INSIDE, status=ToolCallStatus.PENDING),
            there_are_tool_calls(occurred_at=INSIDE, status=ToolCallStatus.ERROR),
            there_are_tool_calls(occurred_at=BEFORE_START),
            there_are_tool_calls(occurred_at=WINDOW_END),
            _there_is_another_organization_with_an_agent(),
            there_are_tool_calls(occurred_at=INSIDE),
        ]
    ) as context:
        with when("tool calls are counted per Agent"):
            rows = _repository(context).tool_calls_by_agent(_window(), _scope(context))

        with then("every status counts, inside the half-open window, for this Organization only"):
            assert_that(rows, equal_to([(context.agents["mine"].id, 4)]))


# --- API --------------------------------------------------------------------------


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _get_activity(context, params: dict | None = None):
    return context.client.get(ACTIVITY_URL, params=params or WINDOW_PARAMS, headers=_auth(context))


def _there_is_an_actor_in_the_organization(role: OrganizationRole, email: str):
    def step(context):
        there_is_a_user(email=email, role=role)(context)
        there_is_an_access_token_for_user()(context)

    return step


def _rows_by_name(body: dict) -> dict[str, dict]:
    return {row["agent_name"]: row for row in body["agents"]}


def test_requests_count_inbound_messages_and_webhook_invocations():
    with given(
        [
            *_API_GIVEN,
            there_is_an_agent(name="Busy", status=AgentStatus.RUNNING),
            there_is_a_connection(CommunicationPlatform.WEB),
            _delivered(10),
            _delivered(20),
            there_is_a_webhook_invocation(created_at=INSIDE),
            there_is_a_webhook_invocation(
                created_at=INSIDE + timedelta(days=2), status=WebhookInvocationStatus.DISPATCH_FAILED
            ),
        ]
    ) as context:
        with when("the Owner reads the Organization's activity"):
            body = _get_activity(context).json()

        with then("both Web Chat messages and both webhook invocations are requests"):
            assert_that(body["totals"]["requests"], equal_to(4))

        with then("the series spreads them over their UTC days and sums to the total"):
            assert_that(
                [(point["bucket"], point["requests"]) for point in body["requests_series"]],
                equal_to(list(zip(BUCKETS, [3, 0, 1, 0], strict=True))),
            )


def test_outbound_messages_and_deliveries_are_not_requests():
    with given(
        [
            *_API_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING),
            there_is_a_connection(CommunicationPlatform.WEB),
            there_is_a_message(direction=MessageDirection.OUTBOUND, occurred_at=INSIDE),
            there_is_an_outbound_delivery(completed_at=INSIDE),
        ]
    ) as context:
        with when("the Owner reads the Organization's activity"):
            totals = _get_activity(context).json()["totals"]

        with then("nothing is counted"):
            assert_that(totals, has_entries(requests=0, handled_coverage=0, handled_without_failure_rate=None))


def test_the_handled_rate_counts_unavailable_as_a_failure_and_leaves_unfinished_deliveries_out():
    with given(
        [
            *_API_GIVEN,
            there_is_an_agent(name="Running", status=AgentStatus.RUNNING),
            there_is_a_connection(CommunicationPlatform.WEB),
            _delivered(10),
            _delivered(10),
            _delivered(10, status=DEAD_LETTERED, attempt_count=5),
            _delivered(10, status=CANCELLED),
            there_is_an_inbound_delivery(occurred_at=INSIDE),
            there_is_an_inbound_delivery(occurred_at=INSIDE, status=PROCESSING, attempt_count=1),
            there_is_an_agent(name="Stopped", status=AgentStatus.STOPPED),
            there_is_a_connection(CommunicationPlatform.WEB),
            there_is_an_inbound_delivery(occurred_at=INSIDE, completed_at=INSIDE),
        ]
    ) as context:
        with when("the Owner reads the Organization's activity"):
            totals = _get_activity(context).json()["totals"]

        with then("two of the four handled deliveries succeeded"):
            assert_that(totals, has_entries(handled_without_failure_rate=0.5, handled_coverage=4))


def test_an_automatically_retried_delivery_is_handled_but_left_out_of_the_median():
    with given(
        [
            *_API_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING),
            there_is_a_connection(CommunicationPlatform.WEB),
            _delivered(10),
            _delivered(600, attempt_count=2),
        ]
    ) as context:
        with when("the Owner reads the Organization's activity"):
            totals = _get_activity(context).json()["totals"]

        with then("both succeeded, and only the first-attempt success is timed"):
            assert_that(
                totals,
                has_entries(
                    handled_without_failure_rate=1.0,
                    handled_coverage=2,
                    median_response_seconds=10.0,
                    response_time_coverage=1,
                ),
            )


def test_the_median_response_time_interpolates_first_attempt_successes():
    with given(
        [
            *_API_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING),
            there_is_a_connection(CommunicationPlatform.EMAIL),
            _delivered(10),
            _delivered(20),
        ]
    ) as context:
        with when("the Owner reads the Organization's activity"):
            totals = _get_activity(context).json()["totals"]

        with then("the median sits between the two"):
            assert_that(totals, has_entries(median_response_seconds=15.0, response_time_coverage=2))


def test_rates_and_medians_are_null_without_deliveries():
    with given([*_API_GIVEN, there_is_an_agent(), there_is_a_webhook_invocation(created_at=INSIDE)]) as context:
        with when("the Owner reads the Organization's activity"):
            totals = _get_activity(context).json()["totals"]

        with then("there is a request but nothing to rate or time"):
            assert_that(
                totals,
                has_entries(
                    requests=1,
                    handled_without_failure_rate=None,
                    handled_coverage=0,
                    median_response_seconds=None,
                    response_time_coverage=0,
                ),
            )


def test_per_request_figures_are_null_without_requests():
    with given(
        [
            *_API_GIVEN,
            there_is_an_agent(),
            there_are_cost_records(count=1, spend="2.00", occurred_at=INSIDE),
            there_are_tool_calls(count=3, occurred_at=INSIDE),
        ]
    ) as context:
        with when("the Owner reads the Organization's activity"):
            totals = _get_activity(context).json()["totals"]

        with then("spend and tool calls exist, but nothing is divided by zero requests"):
            assert_that(totals, has_entries(requests=0, cost_per_request=None, tool_calls_per_request=None))


def test_per_request_figures_divide_spend_and_tool_calls_by_requests():
    with given(
        [
            *_API_GIVEN,
            there_is_an_agent(),
            there_is_a_webhook_invocation(created_at=INSIDE),
            there_is_a_webhook_invocation(created_at=INSIDE),
            there_are_tool_calls(count=3, occurred_at=INSIDE),
        ]
    ) as context:
        with when("the Owner reads the Organization's activity"):
            totals = _get_activity(context).json()["totals"]

        with then("zero spend is a zero cost per request, and tool calls are averaged"):
            assert_that(totals, has_entries(requests=2, cost_per_request=0.0, tool_calls_per_request=1.5))


def test_a_native_only_agent_has_requests_but_no_coverage():
    with given(
        [
            *_API_GIVEN,
            there_is_an_agent(name="Slack Agent"),
            there_is_a_connection(CommunicationPlatform.SLACK),
            there_is_a_message(occurred_at=INSIDE),
            there_is_a_message(occurred_at=INSIDE),
        ]
    ) as context:
        with when("the Owner reads the Organization's activity"):
            row = _rows_by_name(_get_activity(context).json())["Slack Agent"]

        with then("its requests count, and its rate and median have nothing to base them on"):
            assert_that(
                row,
                has_entries(
                    requests=2,
                    handled_without_failure_rate=None,
                    handled_coverage=0,
                    median_response_seconds=None,
                    response_time_coverage=0,
                ),
            )


def test_a_soft_deleted_agent_stays_in_the_period_it_worked():
    with given(
        [
            *_API_GIVEN,
            there_is_an_agent(name="Retired", status=AgentStatus.RUNNING),
            there_is_a_connection(CommunicationPlatform.WEB),
            _delivered(10),
            there_is_a_webhook_invocation(created_at=INSIDE),
            the_agent_is_soft_deleted(),
        ]
    ) as context:
        with when("the Owner reads the Organization's activity"):
            body = _get_activity(context).json()

        with then("its requests and deliveries still count, flagged as deleted"):
            assert_that(body["totals"], has_entries(requests=2, handled_coverage=1))
            assert_that(
                _rows_by_name(body)["Retired"],
                has_entries(agent_deleted=True, requests=2, handled_coverage=1),
            )


def test_a_delivery_on_a_retired_connection_still_counts():
    with given(
        [
            *_API_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING),
            there_is_a_connection(CommunicationPlatform.EMAIL),
            _delivered(10),
            the_connection_is_retired(),
        ]
    ) as context:
        with when("the Owner reads the Organization's activity"):
            totals = _get_activity(context).json()["totals"]

        with then("the request and its outcome are still reported"):
            assert_that(totals, has_entries(requests=1, handled_coverage=1, handled_without_failure_rate=1.0))


def test_an_approval_answer_counts_as_a_request():
    with given([*_API_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        now = datetime.now(UTC)
        answer = context.client.post(
            f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/web-chat/messages",
            headers=_auth(context),
            json={"text": "once", "approval_id": "run_1:1726051234.5"},
        )

        with when("the Owner reads activity for the hour around the answer"):
            totals = _get_activity(
                context,
                {
                    "from_date": (now - timedelta(hours=1)).isoformat(),
                    "to_date": (now + timedelta(hours=1)).isoformat(),
                },
            ).json()["totals"]

        with then("the answer is an inbound message, so it is a request"):
            assert_that(answer.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(totals["requests"], equal_to(1))


def test_the_window_is_half_open_on_every_source_and_echoed():
    with given(
        [
            *_API_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING),
            there_is_a_connection(CommunicationPlatform.WEB),
            _delivered(0, completed_at=WINDOW_START),
            _delivered(0, completed_at=BEFORE_START),
            _delivered(0, completed_at=WINDOW_END),
            there_is_a_webhook_invocation(created_at=WINDOW_START),
            there_is_a_webhook_invocation(created_at=WINDOW_END),
            there_are_tool_calls(occurred_at=WINDOW_START),
            there_are_tool_calls(occurred_at=WINDOW_END),
        ]
    ) as context:
        with when("the Owner reads the Organization's activity"):
            body = _get_activity(context).json()

        with then("only what happened from the start up to, not including, the end counts"):
            assert_that(body["totals"], has_entries(requests=2, handled_coverage=1, tool_calls_per_request=0.5))

        with then("the resolved window is echoed"):
            assert_that(
                body,
                has_entries(
                    period=None,
                    from_date="2026-09-01T00:00:00Z",
                    to_date="2026-09-04T00:00:00Z",
                    granularity="day",
                ),
            )


def test_an_inverted_window_is_rejected():
    with given(_API_GIVEN) as context:
        with when("the Owner asks for a window that ends before it starts"):
            response = _get_activity(context, {"from_date": "2026-09-04T00:00:00Z", "to_date": "2026-09-01T00:00:00Z"})

        with then("it is a validation failure"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_the_requests_series_uses_the_spend_series_buckets():
    with given([*_API_GIVEN, there_is_an_agent()]) as context:
        with when("the Owner reads an empty period"):
            body = _get_activity(context).json()

        with then("every bucket is present, as UTC instants, with no requests"):
            spend_buckets = [
                utc_bucket(bucket).isoformat().replace("+00:00", "Z")
                for bucket, _spend, _calls in context.injector.get(CostRepository).spend_series(
                    _window(), CostFilter(organization_id=context.organization.id)
                )
            ]
            assert_that([point["bucket"] for point in body["requests_series"]], equal_to(spend_buckets))
            assert_that(spend_buckets, equal_to(BUCKETS))
            assert_that({point["requests"] for point in body["requests_series"]}, equal_to({0}))


def test_every_agent_with_activity_or_spend_gets_a_row_in_order():
    with given(
        [
            *_API_GIVEN,
            there_is_an_agent(name="Most"),
            there_is_a_webhook_invocation(created_at=INSIDE),
            there_is_a_webhook_invocation(created_at=INSIDE),
            there_is_a_webhook_invocation(created_at=INSIDE),
            there_is_an_agent(name="Some"),
            there_is_a_webhook_invocation(created_at=INSIDE),
            there_are_cost_records(count=1, spend="1.00", occurred_at=INSIDE),
            there_is_an_agent(name="Spender"),
            there_are_cost_records(count=1, spend="5.00", occurred_at=INSIDE),
            there_are_cost_records(count=1, spend="0.50", occurred_at=INSIDE, without_agent=True),
        ]
    ) as context:
        with when("the Owner reads the Organization's activity"):
            agents = _get_activity(context).json()["agents"]

        with then("rows follow requests, then spend, with unattributed spend last"):
            assert_that(
                [row["agent_name"] for row in agents],
                equal_to(["Most", "Some", "Spender", "Unattributed"]),
            )

        with then("an Agent with spend but no requests has no per-request figures"):
            assert_that(agents[2], has_entries(agent_deleted=False, requests=0, spend=5.0, cost_per_request=None))

        with then("an Agent with both is divided out"):
            assert_that(agents[1], has_entries(requests=1, spend=1.0, cost_per_request=1.0))


def test_an_admin_can_read_activity():
    with given(
        [*_API_GIVEN, _there_is_an_actor_in_the_organization(OrganizationRole.ADMIN, "admin-activity@example.com")]
    ) as context:
        with when("an Admin reads the Organization's activity"):
            response = _get_activity(context)

        with then("it succeeds"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))


def test_a_member_cannot_read_activity():
    with given(
        [*_API_GIVEN, _there_is_an_actor_in_the_organization(OrganizationRole.MEMBER, "member-activity@example.com")]
    ) as context:
        with when("a Member reads the Organization's activity"):
            response = _get_activity(context)

        with then("it is forbidden"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_non_member_cannot_read_activity():
    with given(_API_GIVEN) as context:
        target = context.organization.id
        there_is_a_user(email="outsider-activity@example.com", organization_id=uuid7(), role=OrganizationRole.OWNER)(
            context
        )
        there_is_an_access_token_for_user()(context)

        with when("an Owner of another Organization reads this Organization's activity"):
            response = context.client.get(
                ACTIVITY_URL.format(organization_id=target), params=WINDOW_PARAMS, headers=_auth(context)
            )

        with then("it is forbidden"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_activity_requires_authentication():
    with given(_API_GIVEN) as context:
        with when("an unauthenticated caller reads activity"):
            response = context.client.get(ACTIVITY_URL, params=WINDOW_PARAMS)

        with then("it is rejected"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
