from datetime import UTC, datetime, timedelta
from uuid import uuid4, uuid7

from fastapi import status
from hamcrest import assert_that, close_to, contains_exactly, contains_string, equal_to, has_length, is_, none, not_
from starlette.testclient import TestClient

from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.costs.repository import CostRepository
from api.domains.platform_admin.models import resolve_stats_window
from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID, PERMISSION_ID_BY_KEY, PermissionKey
from api.domains.rbac.models import AgentAccessRole, AgentAccessRolePermission
from api.domains.rbac.policy import AuthorizationScope
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.prometheus.client import PrometheusClient
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_agent_access,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.cost import cost_records_are_clean, there_are_cost_records
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.resource_usage import (
    MockPrometheusModule,
    prometheus_is_down,
    prometheus_is_not_configured,
    prometheus_reports_for_agents,
)
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_URL = "/api/v1/organizations/{organization_id}/agent-overview"

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "SKIP_SLACK_TOKEN_VALIDATION": "true",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), MockPrometheusModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_a_template(),
    cost_records_are_clean(),
]

_REPORTING = {
    "up": 1.0,
    "cgroup_metrics_available": 1.0,
    "memory_working_set_bytes": 358_617_088.0,
    "memory_limit_bytes": 1_073_741_824.0,
    "cpu_cores": 0.05,
    "cpu_limit_cores": 0.5,
    "cpu_throttled_ratio": 0.2,
}


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _url(context) -> str:
    return _URL.format(organization_id=context.organization.id)


def _there_is_an_agent_named(name: str, status: AgentStatus = AgentStatus.RUNNING):
    """Create an Agent and remember it, since `context.agent` only holds the latest."""

    def step(context):
        there_is_an_agent(name=name, status=status)(context)
        context.agents = {**getattr(context, "agents", {}), name: context.agent}

    return step


def _switch_to_member():
    def step(context):
        member_id = uuid7()
        there_is_a_user(
            id=member_id,
            email=f"member-overview-{member_id}@example.com",
            role=OrganizationRole.MEMBER,
            organization_id=context.organization.id,
        )(context)
        there_is_an_access_token_for_user(member_id)(context)

    return step


def _there_is_agent_access_with(context, agent_id, permissions: set[PermissionKey]) -> None:
    repository: AgentRepository = context.injector.get(AgentRepository)
    role = AgentAccessRole(organization_id=context.organization.id, name=f"CUSTOM-{uuid7()}", is_system=False)
    repository.delegate.save(role)
    for permission in permissions:
        repository.delegate.save(
            AgentAccessRolePermission(role_id=role.id, permission_id=PERMISSION_ID_BY_KEY[permission])
        )
    there_is_agent_access(agent_id=agent_id, access_role_id=role.id)(context)


def _by_name(body: dict) -> dict:
    return {item["name"]: item for item in body["items"]}


def test_overview_without_auth_returns_401():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        with when("I read the overview without a token"):
            response = client.get(_url(context))
        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_an_organization_without_agents_has_an_empty_overview():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        with when("I read the overview of an organization with no agents"):
            response = client.get(_url(context), headers=_auth(context))
        with then("it is empty rather than an error"):
            body = response.json()
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(body["items"], equal_to([]))
            assert_that(body["total"], equal_to(0))
            assert_that(body["resource_usage_availability"], equal_to("available"))


def test_overview_lists_every_agent_with_status_spend_and_usage():
    with given(
        [
            *_GIVEN,
            _there_is_an_agent_named("Alpha"),
            _there_is_an_agent_named("Beta"),
            _there_is_an_agent_named("Gamma", status=AgentStatus.STOPPED),
        ]
    ) as context:
        alpha, beta = context.agents["Alpha"], context.agents["Beta"]
        there_are_cost_records(count=2, spend="1.25", agent_id=alpha.id, minutes_ago=30)(context)
        prometheus_reports_for_agents({alpha.id: _REPORTING, beta.id: {"up": 1.0}})(context)
        client: TestClient = context.client
        with when("I read the overview"):
            response = client.get(_url(context), headers=_auth(context))
        body = response.json()
        rows = _by_name(body)
        with then("every agent is listed once, oldest first, with its status"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that([item["name"] for item in body["items"]], contains_exactly("Alpha", "Beta", "Gamma"))
            assert_that(body["total"], equal_to(3))
            assert_that(rows["Alpha"]["status"], equal_to("RUNNING"))
            assert_that(rows["Gamma"]["status"], equal_to("STOPPED"))
            assert_that(body["period"], equal_to("THIRTY_DAYS"))
        with then("spend is per agent, and an agent with no calls has zero"):
            assert_that(rows["Alpha"]["spend"]["spend"], close_to(2.5, 1e-6))
            assert_that(rows["Alpha"]["spend"]["calls"], equal_to(2))
            assert_that(rows["Beta"]["spend"]["spend"], equal_to(0.0))
            assert_that(rows["Beta"]["spend"]["calls"], equal_to(0))
            assert_that(rows["Beta"]["spend"]["last_call_at"], none())
        with then("a reporting agent shows its usage against its limits"):
            usage = rows["Alpha"]["resource_usage"]
            assert_that(usage["state"], equal_to("reporting"))
            assert_that(usage["memory_working_set_bytes"], equal_to(358_617_088))
            assert_that(usage["memory_limit_bytes"], equal_to(1_073_741_824))
            assert_that(usage["cpu_limit_cores"], close_to(0.5, 1e-9))
        with then("an agent on an older script is told to restart"):
            assert_that(rows["Beta"]["resource_usage"]["state"], equal_to("restart_required"))
        with then("a stopped agent has no container to measure"):
            assert_that(rows["Gamma"]["resource_usage"], none())
        with then("the usage source is reported as reachable"):
            assert_that(body["resource_usage_availability"], equal_to("available"))


def test_only_measurable_agents_are_queried_and_only_within_this_organization():
    with given(
        [
            *_GIVEN,
            _there_is_an_agent_named("Alpha"),
            _there_is_an_agent_named("Gamma", status=AgentStatus.STOPPED),
        ]
    ) as context:
        client: TestClient = context.client
        with when("I read the overview"):
            client.get(_url(context), headers=_auth(context))
        with then("one instant query names the running agent in this organization"):
            prometheus = context.injector.get(PrometheusClient)
            assert_that(prometheus.query.call_count, equal_to(1))
            promql = prometheus.query.call_args.args[0]
            assert_that(promql, contains_string(f'org_id="{context.organization.id}"'))
            assert_that(promql, contains_string(str(context.agents["Alpha"].id)))
        with then("the stopped agent is not part of it"):
            assert_that(promql, not_(contains_string(str(context.agents["Gamma"].id))))


def test_rows_for_agents_outside_the_page_are_dropped():
    with given([*_GIVEN, _there_is_an_agent_named("Alpha")]) as context:
        stranger = uuid4()
        prometheus_reports_for_agents({context.agents["Alpha"].id: _REPORTING, stranger: _REPORTING})(context)
        client: TestClient = context.client
        with when("Prometheus also answers with a row for an agent we did not ask about"):
            response = client.get(_url(context), headers=_auth(context))
        with then("the overview lists only our agents"):
            assert_that(response.json()["items"], has_length(1))


def test_overview_spend_matches_the_agents_own_costs_tab():
    with given([*_GIVEN, _there_is_an_agent_named("Alpha")]) as context:
        alpha = context.agents["Alpha"]
        there_are_cost_records(count=3, spend="0.75", agent_id=alpha.id, minutes_ago=90)(context)
        client: TestClient = context.client
        with when("I read the overview and the agent's own cost summary for the same period"):
            overview = client.get(_url(context), headers=_auth(context)).json()
            costs = client.get(
                f"/api/v1/organizations/{context.organization.id}/costs/agents/{alpha.id}",
                headers=_auth(context),
            ).json()
        with then("both report the same spend and the same number of calls"):
            assert_that(overview["items"][0]["spend"]["spend"], close_to(costs["total_cost"], 1e-6))
            assert_that(overview["items"][0]["spend"]["calls"], equal_to(costs["total_calls"]))


def test_spend_outside_the_selected_period_is_not_counted():
    with given([*_GIVEN, _there_is_an_agent_named("Alpha")]) as context:
        alpha = context.agents["Alpha"]
        there_are_cost_records(count=1, spend="5.0", agent_id=alpha.id, minutes_ago=60)(context)
        there_are_cost_records(
            count=1, spend="9.0", agent_id=alpha.id, occurred_at=datetime.now(UTC) - timedelta(days=20)
        )(context)
        client: TestClient = context.client
        with when("I read the overview for the last seven days"):
            response = client.get(_url(context), params={"period": "SEVEN_DAYS"}, headers=_auth(context))
        with then("only the recent call is counted"):
            body = response.json()
            assert_that(body["period"], equal_to("SEVEN_DAYS"))
            assert_that(body["items"][0]["spend"]["spend"], close_to(5.0, 1e-6))
        with when("I read it for the last thirty days"):
            response = client.get(_url(context), params={"period": "THIRTY_DAYS"}, headers=_auth(context))
        with then("both calls are counted"):
            assert_that(response.json()["items"][0]["spend"]["spend"], close_to(14.0, 1e-6))


# --- per-agent access ------------------------------------------------------


def test_a_member_sees_only_the_agents_they_were_given():
    with given(
        [
            *_GIVEN,
            _there_is_an_agent_named("Alpha"),
            _there_is_an_agent_named("Beta"),
            _switch_to_member(),
        ]
    ) as context:
        alpha, beta = context.agents["Alpha"], context.agents["Beta"]
        there_are_cost_records(count=1, spend="4.0", agent_id=alpha.id, minutes_ago=10)(context)
        there_are_cost_records(count=1, spend="8.0", agent_id=beta.id, minutes_ago=10)(context)
        there_is_agent_access(agent_id=alpha.id, access_role_id=AGENT_VIEWER_ROLE_ID)(context)
        prometheus_reports_for_agents({alpha.id: _REPORTING, beta.id: _REPORTING})(context)
        client: TestClient = context.client
        with when("a member with access to one agent reads the overview"):
            response = client.get(_url(context), headers=_auth(context))
        body = response.json()
        with then("only that agent is listed and counted"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that([item["name"] for item in body["items"]], contains_exactly("Alpha"))
            assert_that(body["total"], equal_to(1))
        with then("the other agent's spend and identity never leave"):
            assert_that(body["items"][0]["spend"]["spend"], close_to(4.0, 1e-6))
            assert_that(str(beta.id) in response.text, is_(False))
        with then("the usage query does not name the agent they cannot see"):
            promql = context.injector.get(PrometheusClient).query.call_args.args[0]
            assert_that(promql, not_(contains_string(str(beta.id))))


def test_a_reader_without_cost_read_still_sees_the_agent_but_not_its_spend():
    with given([*_GIVEN, _there_is_an_agent_named("Alpha"), _switch_to_member()]) as context:
        alpha = context.agents["Alpha"]
        there_are_cost_records(count=1, spend="4.0", agent_id=alpha.id, minutes_ago=10)(context)
        _there_is_agent_access_with(context, alpha.id, {PermissionKey.AGENT_READ, PermissionKey.ACTIVITY_READ})
        prometheus_reports_for_agents({alpha.id: _REPORTING})(context)
        client: TestClient = context.client
        with when("a reader with activity.read but not cost.read reads the overview"):
            body = client.get(_url(context), headers=_auth(context)).json()
        with then("the row is there with its usage, and spend is withheld"):
            assert_that(body["items"], has_length(1))
            assert_that(body["items"][0]["spend"], none())
            assert_that(body["items"][0]["resource_usage"]["state"], equal_to("reporting"))


def test_a_reader_without_activity_read_sees_spend_but_no_usage_and_no_query():
    with given([*_GIVEN, _there_is_an_agent_named("Alpha"), _switch_to_member()]) as context:
        alpha = context.agents["Alpha"]
        there_are_cost_records(count=1, spend="4.0", agent_id=alpha.id, minutes_ago=10)(context)
        _there_is_agent_access_with(context, alpha.id, {PermissionKey.AGENT_READ, PermissionKey.COST_READ})
        prometheus_reports_for_agents({alpha.id: _REPORTING})(context)
        client: TestClient = context.client
        with when("a reader with cost.read but not activity.read reads the overview"):
            body = client.get(_url(context), headers=_auth(context)).json()
        with then("spend is shown and resource usage is withheld"):
            assert_that(body["items"][0]["spend"]["spend"], close_to(4.0, 1e-6))
            assert_that(body["items"][0]["resource_usage"], none())
        with then("Prometheus was not asked about an agent they may not measure"):
            assert_that(context.injector.get(PrometheusClient).query.called, is_(False))


def test_the_spend_scope_admits_only_agents_the_caller_holds_cost_read_on():
    with given(
        [
            *_GIVEN,
            _there_is_an_agent_named("Alpha"),
            _there_is_an_agent_named("Beta"),
            _switch_to_member(),
        ]
    ) as context:
        alpha, beta = context.agents["Alpha"], context.agents["Beta"]
        there_are_cost_records(count=1, spend="4.0", agent_id=alpha.id, minutes_ago=10)(context)
        there_are_cost_records(count=1, spend="8.0", agent_id=beta.id, minutes_ago=10)(context)
        there_is_agent_access(agent_id=alpha.id, access_role_id=AGENT_VIEWER_ROLE_ID)(context)
        membership_id = context.organization_user.id
        scope = AuthorizationScope(
            organization_id=context.organization.id,
            membership_id=membership_id,
            permission=PermissionKey.COST_READ,
            include_general_access=False,
        )
        with when("spend is requested for both agents through the member's cost scope"):
            totals = context.injector.get(CostRepository).spend_for_agents(
                resolve_stats_window(), scope, [alpha.id, beta.id]
            )
        with then("the agent they cannot read is absent, not zero"):
            assert_that(set(totals), equal_to({alpha.id}))


# --- when the usage source is not there ------------------------------------


def test_an_unreachable_prometheus_blanks_usage_but_keeps_spend_and_status():
    with given([*_GIVEN, _there_is_an_agent_named("Alpha"), prometheus_is_down()]) as context:
        alpha = context.agents["Alpha"]
        there_are_cost_records(count=1, spend="4.0", agent_id=alpha.id, minutes_ago=10)(context)
        client: TestClient = context.client
        with when("Prometheus cannot be reached"):
            response = client.get(_url(context), headers=_auth(context))
        with then("the overview still answers, and says which part is missing"):
            body = response.json()
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(body["resource_usage_availability"], equal_to("unavailable"))
            assert_that(body["items"][0]["resource_usage"], none())
            assert_that(body["items"][0]["spend"]["spend"], close_to(4.0, 1e-6))
            assert_that(body["items"][0]["status"], equal_to("RUNNING"))


def test_an_unconfigured_prometheus_is_reported_without_a_query():
    with given([*_GIVEN, _there_is_an_agent_named("Alpha"), prometheus_is_not_configured()]) as context:
        client: TestClient = context.client
        with when("no Prometheus is configured"):
            body = client.get(_url(context), headers=_auth(context)).json()
        with then("the overview says so and nothing was queried"):
            assert_that(body["resource_usage_availability"], equal_to("not_configured"))
            assert_that(body["items"][0]["resource_usage"], none())
            assert_that(context.injector.get(PrometheusClient).query.called, is_(False))
