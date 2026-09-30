from datetime import UTC, datetime, timedelta
from uuid import uuid7

from hamcrest import assert_that, contains_inanyorder, equal_to

from api.domains.agent_webhooks.models import WebhookInvocationStatus
from api.domains.agents.models import AgentStatus
from api.domains.business_value.repository import DeliveryOutcomes, ValueActivityRepository
from api.domains.communications.models import CommunicationDeliveryStatus, CommunicationPlatform
from api.domains.conversations.models import MessageDirection
from api.domains.costs.models import CostFilter
from api.domains.costs.repository import CostRepository
from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.domains.platform_admin.models import StatsGranularity, StatsWindow
from api.domains.rbac.policy import AuthorizationScope
from api.domains.tool_calls.models import ToolCallStatus
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.communication import (
    the_agent_is_soft_deleted,
    there_are_tool_calls,
    there_is_a_connection,
    there_is_a_message,
    there_is_a_webhook_invocation,
    there_is_an_inbound_delivery,
    there_is_an_outbound_delivery,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

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
