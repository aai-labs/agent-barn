from uuid import uuid4, uuid7

from fastapi import status
from hamcrest import assert_that, close_to, contains_string, equal_to, has_length, is_, none
from starlette.testclient import TestClient

from api.domains.agents.repository import AgentRepository
from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID, PERMISSION_ID_BY_KEY, PermissionKey
from api.domains.rbac.models import AgentAccessRole, AgentAccessRolePermission
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
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.resource_usage import (
    MockPrometheusModule,
    prometheus_is_down,
    prometheus_is_not_configured,
    prometheus_reports,
    prometheus_reports_history,
)
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_BASE = "/api/v1/organizations/{organization_id}/agents"

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
    there_is_an_agent(),
]

# What Prometheus holds for an Agent that is running the current healthz script.
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


def _url(context, agent_id=None) -> str:
    return f"{_BASE.format(organization_id=context.organization.id)}/{agent_id or context.agent.id}/resource-usage"


def _switch_to_member():
    """Replace the authenticated actor with a plain MEMBER of the same org.

    Owners and Admins hold implicit Agent Owner authority, so a permission can only be
    withheld from someone whose authority comes from an Agent Access Role.
    """

    def step(context):
        member_id = uuid7()
        there_is_a_user(
            id=member_id,
            email=f"member-usage-{member_id}@example.com",
            role=OrganizationRole.MEMBER,
            organization_id=context.organization.id,
        )(context)
        there_is_an_access_token_for_user(member_id)(context)

    return step


def _there_is_agent_access_with(context, permissions: set[PermissionKey]) -> None:
    repository: AgentRepository = context.injector.get(AgentRepository)
    role = AgentAccessRole(organization_id=context.organization.id, name=f"CUSTOM-{uuid7()}", is_system=False)
    repository.delegate.save(role)
    for permission in permissions:
        repository.delegate.save(
            AgentAccessRolePermission(role_id=role.id, permission_id=PERMISSION_ID_BY_KEY[permission])
        )
    there_is_agent_access(access_role_id=role.id)(context)


# --- authorization ---------------------------------------------------------


def test_resource_usage_without_auth_returns_401():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        with when("I read resource usage without a token"):
            response = client.get(_url(context))
        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_an_agent_viewer_can_read_resource_usage():
    with given([*_GIVEN, _switch_to_member()]) as context:
        there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID)(context)
        client: TestClient = context.client
        with when("an assigned viewer reads the agent's resource usage"):
            response = client.get(_url(context), headers=_auth(context))
        with then("they are allowed"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))


def test_resource_usage_requires_activity_read():
    with given([*_GIVEN, _switch_to_member()]) as context:
        _there_is_agent_access_with(context, {PermissionKey.AGENT_READ, PermissionKey.COST_READ})
        client: TestClient = context.client
        with when("a reader without activity.read asks how the container is doing"):
            response = client.get(_url(context), headers=_auth(context))
        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_resource_usage_does_not_need_cost_read():
    with given([*_GIVEN, _switch_to_member()]) as context:
        _there_is_agent_access_with(context, {PermissionKey.AGENT_READ, PermissionKey.ACTIVITY_READ})
        client: TestClient = context.client
        with when("a reader with activity.read but not cost.read asks"):
            response = client.get(_url(context), headers=_auth(context))
        with then("they are allowed, because this is not a cost fact"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))


def test_unassigned_member_cannot_read_resource_usage():
    with given([*_GIVEN, _switch_to_member()]) as context:
        client: TestClient = context.client
        with when("a member with no Agent Access reads the agent's resource usage"):
            response = client.get(_url(context), headers=_auth(context))
        with then("the agent is not acknowledged"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_an_unknown_agent_is_not_found():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        with when("I read resource usage for an agent that does not exist"):
            response = client.get(_url(context, agent_id=uuid4()), headers=_auth(context))
        with then("it is not found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_a_deleted_agent_is_not_found():
    with given([*_GIVEN, there_is_an_agent(name="Gone", deleted=True)]) as context:
        client: TestClient = context.client
        with when("I read resource usage for a deleted agent"):
            response = client.get(_url(context), headers=_auth(context))
        with then("it is not found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_an_unknown_range_is_rejected():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        with when("I ask for a range longer than Prometheus keeps"):
            response = client.get(_url(context), params={"range": "30d"}, headers=_auth(context))
        with then("it is a validation error"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


# --- what is reported ------------------------------------------------------


def test_reports_current_usage_limits_and_history():
    with given(
        [
            *_GIVEN,
            prometheus_reports(_REPORTING),
            prometheus_reports_history(
                {
                    "memory_working_set_bytes": {0: 100_000_000.0, 10: 300_000_000.0},
                    "cpu_cores": {0: 0.1, 10: 0.3},
                }
            ),
        ]
    ) as context:
        client: TestClient = context.client
        with when("I read the last day of usage"):
            response = client.get(_url(context), headers=_auth(context))
        body = response.json()
        with then("the source is reachable and the agent is reporting"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(body["availability"], equal_to("available"))
            assert_that(body["state"], equal_to("reporting"))
            assert_that(body["range"], equal_to("24h"))
        with then("the current figures and the container's limits are reported"):
            assert_that(body["memory_working_set_bytes"], equal_to(358_617_088))
            assert_that(body["memory_limit_bytes"], equal_to(1_073_741_824))
            assert_that(body["cpu_cores"], close_to(0.05, 1e-9))
            assert_that(body["cpu_limit_cores"], close_to(0.5, 1e-9))
            assert_that(body["cpu_throttled_ratio"], close_to(0.2, 1e-9))
        with then("history has one point per step and a missing reading is a gap"):
            assert_that(body["step_seconds"], equal_to(300))
            assert_that(body["series"], has_length(289))
            assert_that(body["series"][0]["memory_working_set_bytes"], equal_to(100_000_000))
            assert_that(body["series"][1]["memory_working_set_bytes"], none())
            assert_that(body["series"][10]["cpu_cores"], close_to(0.3, 1e-9))
        with then("peak memory and average CPU are computed over the range"):
            assert_that(body["memory_peak_bytes"], equal_to(300_000_000))
            assert_that(body["cpu_average_cores"], close_to(0.2, 1e-9))


def test_a_longer_range_uses_a_coarser_step():
    with given([*_GIVEN, prometheus_reports(_REPORTING)]) as context:
        client: TestClient = context.client
        with when("I read the last seven days"):
            response = client.get(_url(context), params={"range": "7d"}, headers=_auth(context))
        with then("the chart is drawn at half-hour steps"):
            body = response.json()
            assert_that(body["range"], equal_to("7d"))
            assert_that(body["step_seconds"], equal_to(1800))
            assert_that(body["series"], has_length(337))


def test_queries_are_scoped_to_this_agent_and_organization():
    with given([*_GIVEN, prometheus_reports(_REPORTING)]) as context:
        client: TestClient = context.client
        with when("I read the agent's resource usage"):
            client.get(_url(context), headers=_auth(context))
        prometheus = context.injector.get(PrometheusClient)
        with then("the instant query selects this agent in this organization only"):
            instant = prometheus.query.call_args.args[0]
            assert_that(instant, contains_string(f'org_id="{context.organization.id}"'))
            assert_that(instant, contains_string(f'app="agent-{context.agent.id}"'))
        with then("so does the range query"):
            history = prometheus.query_range.call_args.args[0]
            assert_that(history, contains_string(f'org_id="{context.organization.id}"'))
            assert_that(history, contains_string(f'app="agent-{context.agent.id}"'))


def test_a_stale_healthz_script_asks_for_a_restart():
    with given([*_GIVEN, prometheus_reports({"up": 1.0})]) as context:
        client: TestClient = context.client
        with when("the agent is scraped but has never reported usage"):
            response = client.get(_url(context), headers=_auth(context))
        with then("it is told to restart, with nothing invented"):
            body = response.json()
            assert_that(body["availability"], equal_to("available"))
            assert_that(body["state"], equal_to("restart_required"))
            assert_that(body["memory_working_set_bytes"], none())
            assert_that(body["cpu_cores"], none())


def test_an_agent_whose_node_has_no_cgroup_v2_is_unsupported():
    with given([*_GIVEN, prometheus_reports({"up": 1.0, "cgroup_metrics_available": 0.0})]) as context:
        client: TestClient = context.client
        with when("the container reports it cannot read its cgroup files"):
            response = client.get(_url(context), headers=_auth(context))
        with then("that is reported as unsupported"):
            assert_that(response.json()["state"], equal_to("unsupported"))


def test_an_agent_prometheus_has_never_seen_has_no_data():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        with when("Prometheus holds nothing for the agent"):
            response = client.get(_url(context), headers=_auth(context))
        with then("the state says so and the timeline is still complete"):
            body = response.json()
            assert_that(body["state"], equal_to("no_data"))
            assert_that(body["series"], has_length(289))


def test_rows_for_other_agents_are_ignored():
    with given([*_GIVEN, prometheus_reports(_REPORTING, agent_id=uuid4())]) as context:
        client: TestClient = context.client
        with when("Prometheus answers with a row that belongs to a different agent"):
            response = client.get(_url(context), headers=_auth(context))
        with then("none of it is attributed to this agent"):
            body = response.json()
            assert_that(body["state"], equal_to("no_data"))
            assert_that(body["memory_working_set_bytes"], none())


# --- when the source is not there ------------------------------------------


def test_an_unreachable_prometheus_is_reported_not_raised():
    with given([*_GIVEN, prometheus_is_down()]) as context:
        client: TestClient = context.client
        with when("Prometheus cannot be reached"):
            response = client.get(_url(context), headers=_auth(context))
        with then("the request still succeeds and says the source is unavailable"):
            body = response.json()
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(body["availability"], equal_to("unavailable"))
            assert_that(body["state"], none())
            assert_that(body["series"], equal_to([]))


def test_an_unconfigured_prometheus_is_reported_without_a_call():
    with given([*_GIVEN, prometheus_is_not_configured()]) as context:
        client: TestClient = context.client
        with when("no Prometheus is configured, as in a fresh local setup"):
            response = client.get(_url(context), headers=_auth(context))
        with then("that is the answer, and nothing was queried"):
            body = response.json()
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(body["availability"], equal_to("not_configured"))
            prometheus = context.injector.get(PrometheusClient)
            assert_that(prometheus.query.called, is_(False))
            assert_that(prometheus.query_range.called, is_(False))
