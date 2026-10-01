import json
from datetime import UTC, datetime, timedelta
from uuid import uuid7

from fastapi import status
from hamcrest import (
    assert_that,
    close_to,
    contains_exactly,
    contains_inanyorder,
    empty,
    equal_to,
    has_entries,
    has_length,
)

from api.domains.business_value.catalogue import DEFAULT_MINUTES, OutcomeType
from api.domains.business_value.classifier import BusinessActionStatus
from api.domains.business_value.repository import BusinessActionRepository
from api.domains.costs.models import CostFilter
from api.domains.costs.repository import CostRepository
from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.domains.platform_admin.models import StatsGranularity, StatsWindow
from api.domains.rbac.policy import AuthorizationScope
from api.domains.tool_calls.repository import ToolCallRepository
from api.domains.users.organization_users.models import OrganizationRole
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.business_action import there_are_business_actions
from api.tests.steps.cost import cost_records_are_clean, there_are_cost_records
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

WINDOW_START = datetime(2026, 9, 1, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 4, tzinfo=UTC)
INSIDE = WINDOW_START + timedelta(hours=12)
RECORD_CREATED = OutcomeType.RECORD_CREATED.value
COMMENT_POSTED = OutcomeType.COMMENT_POSTED.value
PULL_REQUEST_OPENED = OutcomeType.PULL_REQUEST_OPENED.value
STALE_OUTCOME_TYPE = "OUTCOME_REMOVED_FROM_CATALOGUE"
SUCCESS = BusinessActionStatus.SUCCESS
UNKNOWN = BusinessActionStatus.UNKNOWN
ERROR = BusinessActionStatus.ERROR
VALUE_URL = "/api/v1/organizations/{organization_id}/value"
SETTINGS_URL = "/api/v1/organizations/{organization_id}/value-settings"
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


def test_successful_counts_by_bucket_are_keyed_on_the_spend_series_buckets():
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

        with then("only buckets with successful writes are returned, keyed like the spend series buckets"):
            spend_buckets = [
                bucket
                for bucket, _spend, _calls in context.injector.get(CostRepository).spend_series(
                    window, CostFilter(organization_id=context.organization.id)
                )
            ]
            assert_that(rows, has_length(2))
            assert_that(
                set(rows),
                equal_to({(spend_buckets[0], RECORD_CREATED, 2), (spend_buckets[2], COMMENT_POSTED, 1)}),
            )


# --- API --------------------------------------------------------------------------


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _get_value(context, params: dict | None = None):
    return context.client.get(VALUE_URL, params=params or WINDOW_PARAMS, headers=_auth(context))


def _the_value_settings_are(body: dict):
    def step(context):
        response = context.client.put(SETTINGS_URL, json=body, headers=_auth(context))
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))

    return step


def _there_is_an_actor_in_the_organization(role: OrganizationRole, email: str):
    def step(context):
        there_is_a_user(email=email, role=role)(context)
        there_is_an_access_token_for_user()(context)

    return step


def _a_shell_tool_call_is_recorded(command: str, exit_code: int):
    def step(context):
        tool_calls: ToolCallRepository = context.injector.get(ToolCallRepository)
        business_actions: BusinessActionRepository = context.injector.get(BusinessActionRepository)
        result = json.dumps({"output": "{}", "exit_code": exit_code, "error": None})
        external_id = f"call-{uuid7()}"
        with tool_calls.get_session() as session:
            tool_calls.upsert_pending(
                session,
                context.organization.id,
                context.agent.id,
                "session",
                external_id,
                "terminal",
                {"command": command},
                INSIDE,
            )
            completed = tool_calls.complete(session, context.agent.id, external_id, result, False, INSIDE)
            assert completed is not None
            business_actions.record_in_session(session, completed)
            session.commit()

    return step


def _the_split_scenario():
    return [
        *_API_GIVEN,
        _the_value_settings_are({"hourly_rate_usd": 60}),
        there_is_an_agent(name="Agent A"),
        _remember_agent("a"),
        there_are_business_actions(
            outcome_type=RECORD_CREATED, is_write=True, status=SUCCESS, count=2, occurred_at=INSIDE
        ),
        there_are_business_actions(outcome_type=COMMENT_POSTED, is_write=True, status=SUCCESS, occurred_at=INSIDE),
        there_are_cost_records(count=3, spend="1.00", occurred_at=INSIDE),
        there_is_an_agent(name="Agent B", deleted=True),
        _remember_agent("b"),
        there_are_business_actions(outcome_type=PULL_REQUEST_OPENED, is_write=True, status=SUCCESS, occurred_at=INSIDE),
        there_are_cost_records(count=1, spend="1.00", occurred_at=INSIDE),
        there_are_cost_records(count=1, spend="0.50", without_agent=True, occurred_at=INSIDE),
        _there_is_spend_for_a_hard_deleted_agent("Gone Agent", "0.25"),
    ]


def _there_is_spend_for_a_hard_deleted_agent(name: str, spend: str):
    def step(context):
        context.gone_agent_id = uuid7()
        there_are_cost_records(
            count=1,
            spend=spend,
            agent_id=context.gone_agent_id,
            agent_name=name,
            occurred_at=INSIDE,
        )(context)

    return step


def test_value_totals_add_up_the_organizations_work_and_spend():
    with given(_the_split_scenario()) as context:
        with when("the Owner reads the Organization's value"):
            response = _get_value(context)

        with then("the totals value every successful write and include all of the Organization's spend"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            totals = response.json()["totals"]
            assert_that(
                totals,
                has_entries(
                    successful_writes=4,
                    minutes_saved=35,
                    value=35.0,
                    spend=4.75,
                    unverified_writes=0,
                    failed_writes=0,
                    unclassified_actions=0,
                    hourly_rate_usd=60.0,
                ),
            )
            assert_that(totals["value_to_spend_ratio"], close_to(35 / 4.75, 1e-9))


def test_value_echoes_the_resolved_window():
    with given(_API_GIVEN) as context:
        with when("the Owner reads value for an explicit range"):
            body = _get_value(context).json()

        with then("the resolved window is echoed back"):
            assert_that(
                body,
                has_entries(
                    period=None,
                    from_date="2026-09-01T00:00:00Z",
                    to_date="2026-09-04T00:00:00Z",
                    granularity="day",
                ),
            )


def test_value_counts_only_the_half_open_period():
    with given(
        [
            *_API_GIVEN,
            _the_value_settings_are({"hourly_rate_usd": 60}),
            there_is_an_agent(),
            there_are_business_actions(
                outcome_type=RECORD_CREATED, is_write=True, status=SUCCESS, occurred_at=WINDOW_START
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
            there_are_cost_records(count=1, spend="2.00", occurred_at=WINDOW_START),
            there_are_cost_records(count=1, spend="9.00", occurred_at=WINDOW_END),
        ]
    ) as context:
        with when("the Owner reads value for the period"):
            totals = _get_value(context).json()["totals"]

        with then("only work and spend from the start up to, not including, the end are counted"):
            assert_that(totals, has_entries(successful_writes=1, minutes_saved=5, spend=2.0))


def test_value_is_split_per_agent_including_deleted_and_unattributed_spend():
    with given(_the_split_scenario()) as context:
        with when("the Owner reads the Organization's value"):
            agents = _get_value(context).json()["agents"]

        with then("each Agent, the unattributed spend and the hard-deleted Agent's spend have a row"):
            assert_that(
                agents,
                contains_exactly(
                    has_entries(
                        agent_id=str(context.agents["b"].id),
                        agent_name="Agent B",
                        agent_deleted=True,
                        successful_writes=1,
                        minutes_saved=20,
                        value=20.0,
                        spend=1.0,
                        value_to_spend_ratio=20.0,
                    ),
                    has_entries(
                        agent_id=str(context.agents["a"].id),
                        agent_name="Agent A",
                        agent_deleted=False,
                        successful_writes=3,
                        minutes_saved=15,
                        value=15.0,
                        spend=3.0,
                        value_to_spend_ratio=5.0,
                    ),
                    has_entries(
                        agent_id=None,
                        agent_name="Unattributed",
                        agent_deleted=False,
                        successful_writes=0,
                        minutes_saved=0,
                        value=0.0,
                        spend=0.5,
                        value_to_spend_ratio=0.0,
                    ),
                    has_entries(
                        agent_id=str(context.gone_agent_id),
                        agent_name="Gone Agent",
                        agent_deleted=True,
                        successful_writes=0,
                        minutes_saved=0,
                        spend=0.25,
                    ),
                ),
            )


def test_an_agent_with_work_but_no_spend_has_no_ratio():
    with given(
        [
            *_API_GIVEN,
            _the_value_settings_are({"hourly_rate_usd": 60}),
            there_is_an_agent(name="Frugal Agent"),
            there_are_business_actions(outcome_type=RECORD_CREATED, is_write=True, status=SUCCESS, occurred_at=INSIDE),
        ]
    ) as context:
        with when("the Owner reads the Organization's value"):
            agents = _get_value(context).json()["agents"]

        with then("the Agent is listed with its value and no ratio"):
            assert_that(
                agents,
                contains_exactly(
                    has_entries(
                        agent_name="Frugal Agent",
                        minutes_saved=5,
                        value=5.0,
                        spend=0.0,
                        value_to_spend_ratio=None,
                    )
                ),
            )


def test_top_outcome_types_are_ordered_by_minutes_saved():
    with given(_the_split_scenario()) as context:
        with when("the Owner reads the Organization's value"):
            top = _get_value(context).json()["top_outcome_types"]

        with then("only Outcome Types with successful writes are listed, most minutes first"):
            assert_that(
                top,
                contains_exactly(
                    has_entries(
                        outcome_type=PULL_REQUEST_OPENED,
                        successful_writes=1,
                        effective_minutes=20,
                        minutes_saved=20,
                        value=20.0,
                    ),
                    has_entries(
                        outcome_type=RECORD_CREATED,
                        successful_writes=2,
                        effective_minutes=5,
                        minutes_saved=10,
                        value=10.0,
                    ),
                    has_entries(
                        outcome_type=COMMENT_POSTED,
                        successful_writes=1,
                        effective_minutes=5,
                        minutes_saved=5,
                        value=5.0,
                    ),
                ),
            )


def test_top_outcome_types_break_minute_ties_by_count():
    with given(
        [
            *_API_GIVEN,
            _the_value_settings_are({"outcome_minutes": {RECORD_CREATED: 10, COMMENT_POSTED: 5}}),
            there_is_an_agent(),
            there_are_business_actions(outcome_type=RECORD_CREATED, is_write=True, status=SUCCESS, occurred_at=INSIDE),
            there_are_business_actions(
                outcome_type=COMMENT_POSTED, is_write=True, status=SUCCESS, count=2, occurred_at=INSIDE
            ),
        ]
    ) as context:
        with when("two Outcome Types saved the same minutes"):
            top = _get_value(context).json()["top_outcome_types"]

        with then("the one with more writes comes first"):
            assert_that(
                [entry["outcome_type"] for entry in top],
                equal_to([COMMENT_POSTED, RECORD_CREATED]),
            )


def test_value_series_carries_minutes_value_and_spend_per_utc_bucket():
    with given(_the_split_scenario()) as context:
        with when("the Owner reads the Organization's value"):
            series = _get_value(context).json()["series"]

        with then("every bucket in the window is present, with the day's figures in the first"):
            assert_that(
                series,
                contains_exactly(
                    has_entries(bucket=BUCKETS[0], minutes_saved=35, value=35.0, spend=4.75),
                    has_entries(bucket=BUCKETS[1], minutes_saved=0, value=0.0, spend=0.0),
                    has_entries(bucket=BUCKETS[2], minutes_saved=0, value=0.0, spend=0.0),
                    has_entries(bucket=BUCKETS[3], minutes_saved=0, value=0.0, spend=0.0),
                ),
            )


def test_value_applies_the_organizations_minute_overrides():
    with given(
        [
            *_API_GIVEN,
            _the_value_settings_are({"hourly_rate_usd": 30, "outcome_minutes": {RECORD_CREATED: 10}}),
            there_is_an_agent(),
            there_are_business_actions(
                outcome_type=RECORD_CREATED, is_write=True, status=SUCCESS, count=2, occurred_at=INSIDE
            ),
            there_are_business_actions(outcome_type=COMMENT_POSTED, is_write=True, status=SUCCESS, occurred_at=INSIDE),
        ]
    ) as context:
        with when("the Owner reads the Organization's value"):
            body = _get_value(context).json()

        with then("the override replaces the default for its Outcome Type only"):
            expected_minutes = 2 * 10 + DEFAULT_MINUTES[OutcomeType.COMMENT_POSTED]
            assert_that(
                body["totals"],
                has_entries(minutes_saved=expected_minutes, value=expected_minutes * 30 / 60, hourly_rate_usd=30.0),
            )
            record_created = next(
                entry for entry in body["top_outcome_types"] if entry["outcome_type"] == RECORD_CREATED
            )
            assert_that(record_created, has_entries(effective_minutes=10, minutes_saved=20, value=10.0))


def test_without_a_rate_minutes_are_reported_but_value_and_ratio_are_null():
    with given(
        [
            *_API_GIVEN,
            there_is_an_agent(),
            there_are_business_actions(outcome_type=RECORD_CREATED, is_write=True, status=SUCCESS, occurred_at=INSIDE),
            there_are_cost_records(count=1, spend="1.00", occurred_at=INSIDE),
        ]
    ) as context:
        with when("the Owner reads value before any rate is set"):
            body = _get_value(context).json()

        with then("minutes and spend are reported and every value is null"):
            assert_that(
                body["totals"],
                has_entries(
                    minutes_saved=5,
                    spend=1.0,
                    value=None,
                    value_to_spend_ratio=None,
                    hourly_rate_usd=None,
                ),
            )
            assert_that(body["agents"][0], has_entries(minutes_saved=5, value=None, value_to_spend_ratio=None))
            assert_that(body["top_outcome_types"][0], has_entries(minutes_saved=5, value=None))
            assert_that(body["series"][0], has_entries(minutes_saved=5, value=None, spend=1.0))


def test_zero_spend_leaves_the_ratio_null():
    with given(
        [
            *_API_GIVEN,
            _the_value_settings_are({"hourly_rate_usd": 60}),
            there_is_an_agent(),
            there_are_business_actions(outcome_type=RECORD_CREATED, is_write=True, status=SUCCESS, occurred_at=INSIDE),
        ]
    ) as context:
        with when("the Owner reads value for a period with no spend"):
            totals = _get_value(context).json()["totals"]

        with then("value is reported and the ratio is null rather than infinite"):
            assert_that(totals, has_entries(value=5.0, spend=0.0, value_to_spend_ratio=None))


def test_unverified_failed_and_unclassified_actions_are_reported_and_not_valued():
    with given(
        [
            *_API_GIVEN,
            _the_value_settings_are({"hourly_rate_usd": 60}),
            there_is_an_agent(),
            there_are_business_actions(
                outcome_type=RECORD_CREATED, is_write=True, status=UNKNOWN, count=2, occurred_at=INSIDE
            ),
            there_are_business_actions(outcome_type=RECORD_CREATED, is_write=True, status=ERROR, occurred_at=INSIDE),
            there_are_business_actions(outcome_type=None, is_write=None, status=SUCCESS, occurred_at=INSIDE),
            there_are_business_actions(outcome_type=None, is_write=True, status=SUCCESS, occurred_at=INSIDE),
            there_are_business_actions(
                outcome_type=STALE_OUTCOME_TYPE, is_write=True, status=SUCCESS, occurred_at=INSIDE
            ),
            there_are_business_actions(outcome_type=None, is_write=False, status=SUCCESS, count=3, occurred_at=INSIDE),
        ]
    ) as context:
        with when("the Owner reads the Organization's value"):
            body = _get_value(context).json()

        with then("each is counted in its own category and none is valued"):
            assert_that(
                body["totals"],
                has_entries(
                    successful_writes=0,
                    minutes_saved=0,
                    value=0.0,
                    unverified_writes=2,
                    failed_writes=1,
                    unclassified_actions=3,
                ),
            )
            assert_that(body["top_outcome_types"], empty())


def test_an_empty_period_reports_zeros_and_every_bucket():
    with given(_API_GIVEN) as context:
        with when("the Owner reads value for a period with nothing in it"):
            body = _get_value(context).json()

        with then("totals are zero, lists are empty, and the bucket spine is complete"):
            assert_that(
                body["totals"],
                has_entries(
                    successful_writes=0,
                    minutes_saved=0,
                    value=None,
                    spend=0.0,
                    value_to_spend_ratio=None,
                    unverified_writes=0,
                    failed_writes=0,
                    unclassified_actions=0,
                    hourly_rate_usd=None,
                ),
            )
            assert_that(body["agents"], empty())
            assert_that(body["top_outcome_types"], empty())
            assert_that([point["bucket"] for point in body["series"]], equal_to(BUCKETS))


def test_an_admin_can_read_value():
    with given(
        [*_API_GIVEN, _there_is_an_actor_in_the_organization(OrganizationRole.ADMIN, "admin-kpi@example.com")]
    ) as context:
        with when("an Admin reads the Organization's value"):
            response = _get_value(context)

        with then("it succeeds"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))


def test_a_member_cannot_read_value():
    with given(
        [*_API_GIVEN, _there_is_an_actor_in_the_organization(OrganizationRole.MEMBER, "member-kpi@example.com")]
    ) as context:
        with when("a Member reads the Organization's value"):
            response = _get_value(context)

        with then("it is forbidden"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_non_member_cannot_read_value():
    with given(_API_GIVEN) as context:
        target = context.organization.id
        there_is_a_user(email="outsider-kpi@example.com", organization_id=uuid7(), role=OrganizationRole.OWNER)(context)
        there_is_an_access_token_for_user()(context)

        with when("an Owner of another Organization reads this Organization's value"):
            response = context.client.get(
                VALUE_URL.format(organization_id=target), params=WINDOW_PARAMS, headers=_auth(context)
            )

        with then("it is forbidden"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_value_requires_authentication():
    with given(_API_GIVEN) as context:
        with when("an unauthenticated caller reads value"):
            response = context.client.get(VALUE_URL, params=WINDOW_PARAMS)

        with then("it is rejected"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_recorded_gog_writes_are_valued_like_any_other_business_action():
    with given(
        [
            *_API_GIVEN,
            _the_value_settings_are({"hourly_rate_usd": 60}),
            there_is_an_agent(name="Workspace Agent"),
            _a_shell_tool_call_is_recorded("gog drive mkdir probe --json --no-input", exit_code=0),
            _a_shell_tool_call_is_recorded("gog gmail send --to a@example.com --subject s", exit_code=1),
        ]
    ) as context:
        with when("the Owner reads the Organization's value"):
            body = _get_value(context).json()

        with then("the successful gog write is valued and the failed one is reported, not valued"):
            minutes = DEFAULT_MINUTES[OutcomeType.RECORD_CREATED]
            assert_that(
                body["totals"],
                has_entries(successful_writes=1, minutes_saved=minutes, value=float(minutes), failed_writes=1),
            )
            assert_that(
                body["top_outcome_types"],
                contains_exactly(has_entries(outcome_type=OutcomeType.RECORD_CREATED.value, successful_writes=1)),
            )
            assert_that(
                body["agents"], contains_exactly(has_entries(agent_name="Workspace Agent", minutes_saved=minutes))
            )
