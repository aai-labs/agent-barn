from datetime import UTC, datetime, timedelta
from uuid import uuid7

from hamcrest import assert_that, contains_inanyorder, empty, equal_to, has_length

from api.domains.business_value.catalogue import OutcomeType
from api.domains.business_value.classifier import BusinessActionStatus
from api.domains.business_value.repository import BusinessActionRepository
from api.domains.costs.models import CostFilter
from api.domains.costs.repository import CostRepository
from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.domains.platform_admin.models import StatsGranularity, StatsWindow
from api.domains.rbac.policy import AuthorizationScope
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.business_action import there_are_business_actions
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

WINDOW_START = datetime(2026, 9, 1, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 4, tzinfo=UTC)
INSIDE = WINDOW_START + timedelta(hours=12)
RECORD_CREATED = OutcomeType.RECORD_CREATED.value
COMMENT_POSTED = OutcomeType.COMMENT_POSTED.value
SUCCESS = BusinessActionStatus.SUCCESS
UNKNOWN = BusinessActionStatus.UNKNOWN
ERROR = BusinessActionStatus.ERROR

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
]


def _window(granularity: StatsGranularity = StatsGranularity.DAY) -> StatsWindow:
    return StatsWindow(start=WINDOW_START, end=WINDOW_END, period=None, granularity=granularity)


def _scope(context) -> AuthorizationScope:
    return AuthorizationScope(organization_id=context.organization.id)


def _repository(context) -> BusinessActionRepository:
    return context.injector.get(BusinessActionRepository)


def _remember_agent(name: str):
    def step(context):
        if not hasattr(context, "agents"):
            context.agents = {}
        context.agents[name] = context.agent

    return step


def _there_is_another_organization_with_an_agent():
    def step(context):
        other = Organization(id=uuid7(), name="Other Organization")
        context.injector.get(OrganizationRepository).save(other)
        there_is_an_agent(name="Other Agent", organization_id=other.id)(context)

    return step


def test_category_counts_group_actions_by_write_outcome_type_and_status():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_are_business_actions(
                outcome_type=RECORD_CREATED, is_write=True, status=SUCCESS, count=2, occurred_at=INSIDE
            ),
            there_are_business_actions(outcome_type=RECORD_CREATED, is_write=True, status=UNKNOWN, occurred_at=INSIDE),
            there_are_business_actions(outcome_type=COMMENT_POSTED, is_write=True, status=ERROR, occurred_at=INSIDE),
            there_are_business_actions(outcome_type=None, is_write=False, status=SUCCESS, count=3, occurred_at=INSIDE),
            there_are_business_actions(outcome_type=None, is_write=None, status=SUCCESS, occurred_at=INSIDE),
        ]
    ) as context:
        with when("category counts are read for the window"):
            rows = _repository(context).category_counts(_window(), _scope(context))

        with then("each (is_write, outcome_type, status) group carries its count"):
            assert_that(rows, has_length(5))
            assert_that(
                set(rows),
                equal_to(
                    {
                        (True, RECORD_CREATED, SUCCESS, 2),
                        (True, RECORD_CREATED, UNKNOWN, 1),
                        (True, COMMENT_POSTED, ERROR, 1),
                        (False, None, SUCCESS, 3),
                        (None, None, SUCCESS, 1),
                    }
                ),
            )


def test_category_counts_use_a_half_open_window():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_are_business_actions(
                outcome_type=RECORD_CREATED, is_write=True, status=SUCCESS, occurred_at=WINDOW_START
            ),
            there_are_business_actions(
                outcome_type=RECORD_CREATED,
                is_write=True,
                status=SUCCESS,
                occurred_at=WINDOW_END - timedelta(microseconds=1),
            ),
            there_are_business_actions(
                outcome_type=RECORD_CREATED,
                is_write=True,
                status=SUCCESS,
                occurred_at=WINDOW_START - timedelta(microseconds=1),
            ),
            there_are_business_actions(
                outcome_type=RECORD_CREATED, is_write=True, status=SUCCESS, occurred_at=WINDOW_END
            ),
        ]
    ) as context:
        with when("category counts are read for the window"):
            rows = _repository(context).category_counts(_window(), _scope(context))

        with then("the start is included and the end is excluded"):
            assert_that(rows, equal_to([(True, RECORD_CREATED, SUCCESS, 2)]))


def test_category_counts_include_soft_deleted_agents():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(name="Deleted Agent", deleted=True),
            there_are_business_actions(outcome_type=RECORD_CREATED, is_write=True, status=SUCCESS, occurred_at=INSIDE),
        ]
    ) as context:
        with when("category counts are read for the window"):
            rows = _repository(context).category_counts(_window(), _scope(context))

        with then("the soft-deleted Agent's work is still counted"):
            assert_that(rows, equal_to([(True, RECORD_CREATED, SUCCESS, 1)]))


def test_aggregates_exclude_another_organizations_actions():
    with given(
        [
            *_GIVEN,
            _there_is_another_organization_with_an_agent(),
            there_are_business_actions(outcome_type=RECORD_CREATED, is_write=True, status=SUCCESS, occurred_at=INSIDE),
        ]
    ) as context:
        with when("this Organization's aggregates are read"):
            categories = _repository(context).category_counts(_window(), _scope(context))
            by_agent = _repository(context).successful_counts_by_agent(_window(), _scope(context))
            by_bucket = _repository(context).successful_counts_by_bucket(_window(), _scope(context))

        with then("nothing from the other Organization is counted"):
            assert_that(categories, empty())
            assert_that(by_agent, empty())
            assert_that([count for _bucket, _outcome, count in by_bucket if count], empty())


def test_successful_counts_by_agent_count_only_successful_classified_writes():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(name="Agent A"),
            _remember_agent("a"),
            there_are_business_actions(
                outcome_type=RECORD_CREATED, is_write=True, status=SUCCESS, count=2, occurred_at=INSIDE
            ),
            there_are_business_actions(outcome_type=COMMENT_POSTED, is_write=True, status=SUCCESS, occurred_at=INSIDE),
            there_are_business_actions(outcome_type=RECORD_CREATED, is_write=True, status=UNKNOWN, occurred_at=INSIDE),
            there_are_business_actions(outcome_type=None, is_write=True, status=SUCCESS, occurred_at=INSIDE),
            there_are_business_actions(outcome_type=None, is_write=False, status=SUCCESS, occurred_at=INSIDE),
            there_is_an_agent(name="Agent B", deleted=True),
            _remember_agent("b"),
            there_are_business_actions(outcome_type=RECORD_CREATED, is_write=True, status=SUCCESS, occurred_at=INSIDE),
            there_are_business_actions(outcome_type=RECORD_CREATED, is_write=True, status=ERROR, occurred_at=INSIDE),
        ]
    ) as context:
        with when("successful counts are read per Agent"):
            rows = _repository(context).successful_counts_by_agent(_window(), _scope(context))

        with then("each Agent's successful writes are grouped by Outcome Type"):
            agent_a = context.agents["a"].id
            agent_b = context.agents["b"].id
            assert_that(
                rows,
                contains_inanyorder(
                    (agent_a, RECORD_CREATED, 2),
                    (agent_a, COMMENT_POSTED, 1),
                    (agent_b, RECORD_CREATED, 1),
                ),
            )


def test_successful_counts_by_bucket_share_the_spend_series_buckets():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_are_business_actions(
                outcome_type=RECORD_CREATED, is_write=True, status=SUCCESS, count=2, occurred_at=INSIDE
            ),
            there_are_business_actions(
                outcome_type=COMMENT_POSTED,
                is_write=True,
                status=SUCCESS,
                occurred_at=INSIDE + timedelta(days=2),
            ),
            there_are_business_actions(outcome_type=RECORD_CREATED, is_write=True, status=UNKNOWN, occurred_at=INSIDE),
        ]
    ) as context:
        window = _window()

        with when("successful counts are read per bucket"):
            rows = _repository(context).successful_counts_by_bucket(window, _scope(context))

        with then("the buckets are exactly the ones the spend series uses, empty ones included"):
            spend_buckets = [
                bucket
                for bucket, _spend, _calls in context.injector.get(CostRepository).spend_series(
                    window, CostFilter(organization_id=context.organization.id)
                )
            ]
            assert_that(sorted({bucket for bucket, _outcome, _count in rows}), equal_to(spend_buckets))

        with then("successful writes land in their UTC day, and unverified ones are not counted"):
            first_day = spend_buckets[0]
            third_day = spend_buckets[2]
            counted = [(bucket, outcome, count) for bucket, outcome, count in rows if count]
            assert_that(counted, has_length(2))
            assert_that(set(counted), equal_to({(first_day, RECORD_CREATED, 2), (third_day, COMMENT_POSTED, 1)}))
