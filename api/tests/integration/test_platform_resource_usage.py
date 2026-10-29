"""Integration tests for the Platform resource usage surface.

Cross-Organization by design: a Platform Administrator reads it without an Active
Organization, so the scenarios seed more than one Organization and expect both counted.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4, uuid7

from fastapi import status
from hamcrest import assert_that, close_to, contains_exactly, contains_string, equal_to, has_length, is_not, none, not_
from kubernetes.client.exceptions import ApiException

from api.domains.agents.models import AgentStatus
from api.domains.agents.provisioning_errors import persisted_provisioning_error
from api.domains.agents.repository import AgentRepository
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.prometheus.client import PrometheusClient, PrometheusSample
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
    there_is_an_agent,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.resource_usage import (
    MockPrometheusModule,
    prometheus_fails_agent_requests,
    prometheus_is_down,
    prometheus_is_not_configured,
    prometheus_reports_agent_requests,
    prometheus_reports_for_agents,
    prometheus_reports_namespace_commitments,
)
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_URL = "/api/v1/platform/resource-usage"

_BASE_GIVEN = [
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
]

_GiB = 1024**3


def _reading(memory_gib: float, cpu: float) -> dict[str, float]:
    return {
        "up": 1.0,
        "cgroup_metrics_available": 1.0,
        "memory_working_set_bytes": memory_gib * _GiB,
        "memory_limit_bytes": 2.0 * _GiB,
        "cpu_cores": cpu,
        "cpu_limit_cores": 1.0,
        "cpu_throttled_ratio": 0.0,
    }


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _platform_admin(email: str):
    """A Platform Administrator with no Membership, whose token lands last in context.

    `there_is_a_user` attaches a new user to `context.organization` as OWNER when one is
    present, which would hand this user the Membership these endpoints must not need.
    """
    admin_id = uuid7()

    def step(context):
        original_organization = getattr(context, "organization", None)
        context.organization = None
        there_is_a_user(id=admin_id, email=email, is_platform_admin=True)(context)
        context.organization = original_organization
        there_is_an_access_token_for_user(user_id=admin_id)(context)

    return [step]


def _two_organizations(first_email: str, second_email: str, *, second_status: AgentStatus = AgentStatus.RUNNING):
    """Acme with "Ada" and Globex with "Cy", remembered as context.ada / context.cy."""

    def step(context):
        there_is_an_organization_with_user_and_access_token(email=first_email)(context)
        there_is_a_template()(context)
        there_is_an_agent(name="Ada", status=AgentStatus.RUNNING)(context)
        context.acme, context.ada = context.organization, context.agent
        context.organization = None
        there_is_an_organization_with_user_and_access_token(email=second_email)(context)
        there_is_a_template()(context)
        there_is_an_agent(name="Cy", status=second_status)(context)
        context.globex, context.cy = context.organization, context.agent
        context.organization = context.acme

    return step


def _reports(rows):
    """Report these readings, keyed by a function of the scenario so ids need not be known."""

    def step(context):
        prometheus_reports_for_agents(rows(context))(context)

    return step


def _set_limits(context, **limits) -> None:
    """Enter capacity limits the way the admin does, through the endpoint."""
    response = context.client.put("/api/v1/platform/resource-limits", json=limits, headers=_auth(context.access_token))
    assert response.status_code == status.HTTP_200_OK, response.text


def _prometheus(context) -> Any:
    """The scenario's mock client, which the type checker cannot see through."""
    return context.injector.get(PrometheusClient)


# --- authorization -------------------------------------------------------


def test_platform_resource_usage_requires_authentication():
    with given(_BASE_GIVEN) as context:
        response = context.client.get(_URL)

        assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_platform_resource_usage_rejects_an_organization_owner():
    with given(
        [*_BASE_GIVEN, there_is_an_organization_with_user_and_access_token(email="owner-only@example.com")]
    ) as context:
        with when("an owner without Platform Privilege asks for it"):
            response = context.client.get(_URL, headers=_auth(context.access_token))

        with then("it is refused, and Prometheus was never asked"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            _prometheus(context).query.assert_not_called()


# --- cross-organization reads --------------------------------------------


def test_every_organization_is_counted_and_named_from_the_database():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-a@example.com", "owner-b@example.com"),
            _reports(lambda c: {c.ada.id: _reading(0.5, 0.2), c.cy.id: _reading(1.0, 0.1)}),
            *_platform_admin("admin-all@example.com"),
        ]
    ) as context:
        with when("the platform admin asks"):
            response = context.client.get(_URL, headers=_auth(context.access_token))

        with then("both organizations and both agents are in the answer"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["availability"], equal_to("available"))
            assert_that(body["totals"]["agents_with_container"], equal_to(2))
            assert_that(body["totals"]["agents_reporting"], equal_to(2))
            assert_that(body["totals"]["memory_working_set_bytes"], equal_to(int(1.5 * _GiB)))
            assert_that([org["organization_name"] for org in body["organizations"]], has_length(2))
            assert_that([agent["agent_name"] for agent in body["agents"]], contains_exactly("Cy", "Ada"))
            ids = {org["organization_id"] for org in body["organizations"]}
            assert_that(ids, equal_to({str(context.acme.id), str(context.globex.id)}))


def test_one_platform_wide_query_is_made_for_the_readings_the_requests_the_chart_and_the_namespace():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-c@example.com", "owner-d@example.com"),
            _reports(lambda c: {c.ada.id: _reading(0.5, 0.2)}),
            *_platform_admin("admin-queries@example.com"),
        ]
    ) as context:
        with when("the platform admin asks without a filter"):
            context.client.get(_URL, headers=_auth(context.access_token))

        with then("none of them is pinned to an organization"):
            client = _prometheus(context)
            queries = [call.args[0] for call in client.query.call_args_list]
            readings = [q for q in queries if "agent_memory_working_set_bytes" in q]
            namespace = [q for q in queries if '"kind"' in q]
            agent_requests = [q for q in queries if '"app", "$1", "pod"' in q]
            # One instant query for the agents' readings, one for what each agent's pod
            # requests, and one for what the namespace commits (limits and requests
            # together), and nothing else.
            assert_that(queries, has_length(3))
            assert_that(readings, has_length(1))
            assert_that(namespace, has_length(1))
            assert_that(agent_requests, has_length(1))
            assert "org_id" not in agent_requests[0]
            assert_that(client.query_range.call_count, equal_to(1))
            assert "org_id" not in readings[0]
            assert "org_id" not in client.query_range.call_args.args[0]
            assert '{job="agent"}' in readings[0]


def test_a_label_cannot_rename_an_organization_or_move_an_agent():
    """Names come from the database; a label that says otherwise is ignored."""
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-e@example.com", "owner-f@example.com"),
            *_platform_admin("admin-labels@example.com"),
        ]
    ) as context:
        _prometheus(context).query.return_value = [
            PrometheusSample(
                labels={
                    "app": f"agent-{context.ada.id}",
                    "usage_field": field,
                    "org_id": str(context.globex.id),
                    "org_name": "Evil Corp",
                    "agent_name": "someone-else",
                },
                value=value,
            )
            for field, value in _reading(0.5, 0.2).items()
        ]

        with when("a reading claims another organization in its labels"):
            body = context.client.get(_URL, headers=_auth(context.access_token)).json()

        with then("it is still filed under its agent's own organization"):
            [agent] = body["agents"]
            assert_that(agent["agent_name"], equal_to("Ada"))
            assert_that(agent["organization_id"], equal_to(str(context.acme.id)))
            assert_that(agent["organization_name"], equal_to(context.acme.name))


def test_a_container_with_no_live_agent_is_shown_apart():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-g@example.com", "owner-h@example.com"),
            _reports(lambda c: {c.ada.id: _reading(0.25, 0.1), uuid4(): _reading(2.0, 0.1)}),
            *_platform_admin("admin-orphan@example.com"),
        ]
    ) as context:
        with when("Prometheus reports a container the database does not know"):
            body = context.client.get(_URL, headers=_auth(context.access_token)).json()

        with then("it has its own last row, and still counts toward the platform"):
            leaked = body["organizations"][-1]
            assert_that(leaked["organization_id"], none())
            assert_that(leaked["organization_name"], none())
            assert_that(leaked["agents_reporting"], equal_to(1))
            assert_that(body["totals"]["memory_working_set_bytes"], equal_to(int(2.25 * _GiB)))
            orphan = next(agent for agent in body["agents"] if agent["agent_name"] is None)
            assert_that(orphan["organization_id"], none())


def test_a_stopped_agent_is_not_counted_as_having_a_container():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-i@example.com", "owner-j@example.com", second_status=AgentStatus.STOPPED),
            _reports(lambda c: {c.ada.id: _reading(0.5, 0.2), c.cy.id: _reading(1.0, 0.1)}),
            *_platform_admin("admin-stopped@example.com"),
        ]
    ) as context:
        body = context.client.get(_URL, headers=_auth(context.access_token)).json()

        assert_that(body["totals"]["agents_with_container"], equal_to(1))
        assert_that(body["totals"]["agents_reporting"], equal_to(1))
        assert_that([agent["agent_name"] for agent in body["agents"]], contains_exactly("Ada"))


# --- the organization filter ---------------------------------------------


def test_the_filter_narrows_totals_agents_and_chart_but_not_the_organization_list():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-k@example.com", "owner-l@example.com"),
            _reports(lambda c: {c.ada.id: _reading(0.5, 0.2), c.cy.id: _reading(1.0, 0.1)}),
            *_platform_admin("admin-narrow@example.com"),
        ]
    ) as context:
        with when("the admin filters to Globex"):
            response = context.client.get(
                f"{_URL}?organization_id={context.globex.id}", headers=_auth(context.access_token)
            )

        with then("the figures cover Globex only, and the list still offers both"):
            body = response.json()
            assert_that(body["organization_id"], equal_to(str(context.globex.id)))
            assert_that(body["totals"]["agents_reporting"], equal_to(1))
            assert_that(body["totals"]["memory_working_set_bytes"], equal_to(1 * _GiB))
            assert_that([agent["agent_name"] for agent in body["agents"]], contains_exactly("Cy"))
            assert_that(body["organizations"], has_length(2))

        with then("the chart asks about exactly Globex's agents"):
            promql = _prometheus(context).query_range.call_args.args[0]
            assert f'org_id="{context.globex.id}"' in promql
            assert f"agent-{context.cy.id}" in promql
            assert str(context.ada.id) not in promql


def test_filtering_to_an_organization_with_no_agents_asks_for_no_chart():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-m@example.com", "owner-n@example.com"),
            _reports(lambda c: {c.ada.id: _reading(0.5, 0.2)}),
            *_platform_admin("admin-empty@example.com"),
        ]
    ) as context:
        with when("the admin filters to an organization that does not exist"):
            response = context.client.get(f"{_URL}?organization_id={uuid4()}", headers=_auth(context.access_token))

        with then("everything is zero and no chart query is made"):
            body = response.json()
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(body["totals"]["agents_with_container"], equal_to(0))
            assert_that(body["agents"], has_length(0))
            _prometheus(context).query_range.assert_not_called()


# --- the source ------------------------------------------------------------


def test_an_unreachable_prometheus_still_returns_the_database_counts():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-o@example.com", "owner-p@example.com"),
            prometheus_is_down(),
            *_platform_admin("admin-down@example.com"),
        ]
    ) as context:
        response = context.client.get(_URL, headers=_auth(context.access_token))

        body = response.json()
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(body["availability"], equal_to("unavailable"))
        assert_that(body["totals"]["agents_with_container"], equal_to(2))
        assert_that(body["totals"]["agents_reporting"], none())
        # Unknown, not zero: with no source nobody can say which agents still need an update.
        assert_that(body["totals"]["agents_restart_required"], none())
        assert_that(body["totals"]["memory_working_set_bytes"], none())
        assert_that(body["organizations"], has_length(0))


def test_agents_still_on_an_older_healthz_script_are_counted_per_organization():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-old-a@example.com", "owner-old-b@example.com"),
            # Ada reports; Cy is scraped but has not been updated since usage was added.
            _reports(lambda c: {c.ada.id: _reading(0.5, 0.2), c.cy.id: {"up": 1.0}}),
            *_platform_admin("admin-old-script@example.com"),
        ]
    ) as context:
        body = context.client.get(_URL, headers=_auth(context.access_token)).json()

        assert_that(body["totals"]["agents_with_container"], equal_to(2))
        assert_that(body["totals"]["agents_reporting"], equal_to(1))
        assert_that(body["totals"]["agents_restart_required"], equal_to(1))
        by_id = {row["organization_id"]: row for row in body["organizations"]}
        assert_that(by_id[str(context.globex.id)]["agents_restart_required"], equal_to(1))
        assert_that(by_id[str(context.acme.id)]["agents_restart_required"], equal_to(0))


def test_an_unconfigured_prometheus_is_reported_without_a_query():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-q@example.com", "owner-r@example.com"),
            prometheus_is_not_configured(),
            *_platform_admin("admin-unconfigured@example.com"),
        ]
    ) as context:
        response = context.client.get(_URL, headers=_auth(context.access_token))

        assert_that(response.json()["availability"], equal_to("not_configured"))
        _prometheus(context).query.assert_not_called()
        _prometheus(context).query_range.assert_not_called()


# --- requests -------------------------------------------------------------


def test_each_agent_row_and_the_totals_carry_what_the_pods_request():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-req-a@example.com", "owner-req-b@example.com"),
            _reports(lambda c: {c.ada.id: _reading(0.5, 0.2), c.cy.id: _reading(1.0, 0.1)}),
            prometheus_reports_agent_requests(lambda c: {c.ada.id: (0.25 * _GiB, 0.05), c.cy.id: (0.5 * _GiB, 0.1)}),
            *_platform_admin("admin-requests@example.com"),
        ]
    ) as context:
        body = context.client.get(_URL, headers=_auth(context.access_token)).json()

        agents = {agent["agent_name"]: agent for agent in body["agents"]}
        assert_that(agents["Ada"]["memory_request_bytes"], equal_to(int(0.25 * _GiB)))
        assert_that(agents["Ada"]["cpu_request_cores"], equal_to(0.05))
        assert_that(body["totals"]["memory_request_bytes"], equal_to(int(0.75 * _GiB)))
        assert_that(body["totals"]["cpu_request_cores"], close_to(0.15, 1e-9))
        by_id = {row["organization_id"]: row for row in body["organizations"]}
        assert_that(by_id[str(context.globex.id)]["memory_request_bytes"], equal_to(int(0.5 * _GiB)))


def test_a_failed_requests_read_leaves_them_unknown_and_the_rest_of_the_page_standing():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-req-c@example.com", "owner-req-d@example.com"),
            _reports(lambda c: {c.ada.id: _reading(0.5, 0.2)}),
            prometheus_fails_agent_requests(),
            *_platform_admin("admin-requests-down@example.com"),
        ]
    ) as context:
        response = context.client.get(_URL, headers=_auth(context.access_token))

        body = response.json()
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        # The readings did not depend on it.
        assert_that(body["availability"], equal_to("available"))
        assert_that(body["agents"][0]["memory_working_set_bytes"], equal_to(int(0.5 * _GiB)))
        # Unknown, not zero.
        assert_that(body["agents"][0]["memory_request_bytes"], none())
        assert_that(body["totals"]["memory_request_bytes"], none())
        assert_that(body["totals"]["cpu_request_cores"], none())


def test_a_request_for_an_agent_that_is_not_reporting_is_left_out_of_the_page():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-req-e@example.com", "owner-req-f@example.com"),
            _reports(lambda c: {c.ada.id: _reading(0.5, 0.2)}),
            # Cy has a pod, but no readings: it is not reporting, so it has no row and no share.
            prometheus_reports_agent_requests(lambda c: {c.ada.id: (0.25 * _GiB, 0.05), c.cy.id: (4 * _GiB, 2.0)}),
            *_platform_admin("admin-requests-unreporting@example.com"),
        ]
    ) as context:
        body = context.client.get(_URL, headers=_auth(context.access_token)).json()

        assert_that([agent["agent_name"] for agent in body["agents"]], contains_exactly("Ada"))
        assert_that(body["totals"]["memory_request_bytes"], equal_to(int(0.25 * _GiB)))


# --- capacity limits -------------------------------------------------------


def test_the_response_holds_the_entered_limits_beside_what_the_namespace_commits():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-cap-a@example.com", "owner-cap-b@example.com"),
            _reports(lambda c: {c.ada.id: _reading(0.5, 0.2)}),
            prometheus_reports_namespace_commitments(
                limits_memory=46 * _GiB, limits_cpu=11.5, requests_memory=9 * _GiB, requests_cpu=2.5
            ),
            *_platform_admin("admin-capacity@example.com"),
        ]
    ) as context:
        _set_limits(
            context,
            limits_memory_bytes=70 * _GiB,
            limits_cpu_cores=24,
            requests_memory_bytes=20 * _GiB,
            requests_cpu_cores=5,
        )

        with when("the admin opens the page"):
            body = context.client.get(_URL, headers=_auth(context.access_token)).json()

        with then("both halves are there: the ceiling they typed and the figure we read"):
            capacity = body["capacity"]
            assert_that(capacity["limits_memory_bytes"], equal_to(70 * _GiB))
            assert_that(capacity["limits_cpu_cores"], equal_to(24))
            assert_that(capacity["requests_memory_bytes"], equal_to(20 * _GiB))
            assert_that(capacity["requests_cpu_cores"], equal_to(5))
            assert_that(capacity["ceilings_updated_at"], is_not(none()))
            assert_that(capacity["committed_limits_memory_bytes"], equal_to(46 * _GiB))
            assert_that(capacity["committed_limits_cpu_cores"], equal_to(11.5))
            assert_that(capacity["committed_requests_memory_bytes"], equal_to(9 * _GiB))
            assert_that(capacity["committed_requests_cpu_cores"], equal_to(2.5))


def test_the_committed_figure_is_asked_of_kube_state_metrics_for_the_whole_namespace():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-cap-c@example.com", "owner-cap-d@example.com"),
            _reports(lambda c: {c.ada.id: _reading(0.5, 0.2)}),
            prometheus_reports_namespace_commitments(limits_memory=4 * _GiB, limits_cpu=1.5),
            *_platform_admin("admin-capacity-query@example.com"),
        ]
    ) as context:
        context.client.get(_URL, headers=_auth(context.access_token))

        queries = [call.args[0] for call in _prometheus(context).query.call_args_list]
        committed = [q for q in queries if '"kind"' in q]
        assert_that(committed, has_length(1))
        assert 'job="kube-state-metrics"' in committed[0]
        # Namespace-wide, never narrowed to an agent or an organization.
        assert "org_id" not in committed[0] and "agent-" not in committed[0]


def test_the_organization_filter_does_not_change_the_capacity():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-cap-e@example.com", "owner-cap-f@example.com"),
            _reports(lambda c: {c.ada.id: _reading(0.5, 0.2), c.cy.id: _reading(1.0, 0.1)}),
            prometheus_reports_namespace_commitments(limits_memory=46 * _GiB, limits_cpu=11.5),
            *_platform_admin("admin-capacity-filter@example.com"),
        ]
    ) as context:
        _set_limits(context, limits_memory_bytes=70 * _GiB)

        everyone = context.client.get(_URL, headers=_auth(context.access_token)).json()
        one = context.client.get(
            f"{_URL}?organization_id={context.globex.id}", headers=_auth(context.access_token)
        ).json()

        # The quota belongs to the namespace, not to an organization.
        assert_that(one["capacity"], equal_to(everyone["capacity"]))


def test_the_limits_survive_an_unreachable_prometheus_and_the_committed_figure_does_not():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-cap-g@example.com", "owner-cap-h@example.com"),
            prometheus_is_down(),
            *_platform_admin("admin-capacity-down@example.com"),
        ]
    ) as context:
        _set_limits(context, limits_memory_bytes=70 * _GiB, limits_cpu_cores=24)

        body = context.client.get(_URL, headers=_auth(context.access_token)).json()

        assert_that(body["availability"], equal_to("unavailable"))
        assert_that(body["capacity"]["limits_memory_bytes"], equal_to(70 * _GiB))
        assert_that(body["capacity"]["limits_cpu_cores"], equal_to(24))
        # Unknown is not zero: nothing is drawn as "no memory committed".
        assert_that(body["capacity"]["committed_limits_memory_bytes"], none())
        assert_that(body["capacity"]["committed_limits_cpu_cores"], none())


def test_the_limits_are_there_when_prometheus_is_not_configured():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-cap-i@example.com", "owner-cap-j@example.com"),
            prometheus_is_not_configured(),
            *_platform_admin("admin-capacity-unconfigured@example.com"),
        ]
    ) as context:
        _set_limits(context, limits_cpu_cores=24)

        body = context.client.get(_URL, headers=_auth(context.access_token)).json()

        assert_that(body["availability"], equal_to("not_configured"))
        assert_that(body["capacity"]["limits_cpu_cores"], equal_to(24))
        assert_that(body["capacity"]["committed_limits_cpu_cores"], none())


def test_nothing_is_set_and_nothing_is_committed_until_someone_says_so():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-cap-k@example.com", "owner-cap-l@example.com"),
            *_platform_admin("admin-capacity-empty@example.com"),
        ]
    ) as context:
        capacity = context.client.get(_URL, headers=_auth(context.access_token)).json()["capacity"]

        assert_that(capacity["limits_memory_bytes"], none())
        assert_that(capacity["limits_cpu_cores"], none())
        assert_that(capacity["ceilings_updated_at"], none())
        # A reachable Prometheus that reports no pods leaves the figure unknown, not zero.
        assert_that(capacity["committed_limits_memory_bytes"], none())
        assert_that(capacity["requests_memory_bytes"], none())
        assert_that(capacity["committed_requests_cpu_cores"], none())


def test_a_kind_the_source_did_not_answer_for_is_unknown_while_the_other_is_known():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-cap-m@example.com", "owner-cap-n@example.com"),
            _reports(lambda c: {c.ada.id: _reading(0.5, 0.2)}),
            prometheus_reports_namespace_commitments(limits_memory=4 * _GiB, limits_cpu=1.5),
            *_platform_admin("admin-capacity-partial@example.com"),
        ]
    ) as context:
        capacity = context.client.get(_URL, headers=_auth(context.access_token)).json()["capacity"]

        assert_that(capacity["committed_limits_memory_bytes"], equal_to(4 * _GiB))
        # Not 0: no answer is not the same as nothing committed.
        assert_that(capacity["committed_requests_memory_bytes"], none())
        assert_that(capacity["committed_requests_cpu_cores"], none())


# --- one Agent's details, for a row that is opened ------------------------

_DETAILS = "/api/v1/platform/resource-usage/agents/{agent_id}"
_SECRET_LOG = "SECRET LOG LINE from the agent's own container"
_SECRET_REASON = "SECRET free-text reason from the agent's healthz"


def _details(context, agent_id: UUID):
    return context.client.get(_DETAILS.format(agent_id=agent_id), headers=_auth(context.access_token))


def _cluster_says(
    *,
    pod: tuple[str, str | None] = ("ready", None),
    healthz: dict | Exception | None = None,
    diagnostics: dict | Exception | None = None,
):
    """What the cluster answers about a running Agent's pod, its healthz and its restarts."""

    def step(context):
        k8s: Any = context.injector.get(KubernetesClient)
        k8s.get_pod_readiness.return_value = pod
        healthz_answer = {"status": "ok", "reason": _SECRET_REASON} if healthz is None else healthz
        if isinstance(healthz_answer, Exception):
            k8s.fetch_agent_healthz.side_effect = healthz_answer
        else:
            k8s.fetch_agent_healthz.return_value = healthz_answer
        diagnostics_answer = (
            {
                "observed_at": datetime.now(UTC),
                "available": True,
                "restart_count": 3,
                "ready": True,
                "termination_reason": "OOMKilled",
                "exit_code": 137,
                "current_logs": [_SECRET_LOG],
                "current_logs_available": True,
            }
            if diagnostics is None
            else diagnostics
        )
        if isinstance(diagnostics_answer, Exception):
            k8s.get_runtime_diagnostics.side_effect = diagnostics_answer
        else:
            k8s.get_runtime_diagnostics.return_value = diagnostics_answer

    return step


def _cy_failed_with(code: str | None, detail: str | None, legacy: str | None = None):
    """Put the second Agent into ERROR with a stored failure, as a failed start leaves it."""

    def step(context):
        repository: AgentRepository = context.injector.get(AgentRepository)
        agent = repository.get_by_id(context.cy.id)
        assert agent is not None
        agent.status = AgentStatus.ERROR
        agent.last_error_code, agent.last_error_detail, agent.last_error = code, detail, legacy
        repository.delegate.save(agent)

    return step


def test_agent_details_require_a_platform_administrator():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-det-a@example.com", "owner-det-b@example.com"),
            _cluster_says(),
        ]
    ) as context:
        with when("nobody, then an organization owner, asks about an agent"):
            anonymous = context.client.get(_DETAILS.format(agent_id=context.cy.id))
            owner = context.client.get(_DETAILS.format(agent_id=context.ada.id), headers=_auth(context.access_token))

        with then("both are refused, and the cluster was never asked"):
            assert_that(anonymous.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
            assert_that(owner.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            k8s: Any = context.injector.get(KubernetesClient)
            k8s.get_pod_readiness.assert_not_called()
            k8s.get_runtime_diagnostics.assert_not_called()


def test_an_unknown_or_deleted_agent_is_not_found():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-det-c@example.com", "owner-det-d@example.com"),
            *_platform_admin("admin-details-404@example.com"),
        ]
    ) as context:
        there_is_an_agent(name="Gone", deleted=True, organization_id=context.acme.id)(context)

        assert_that(_details(context, uuid4()).status_code, equal_to(status.HTTP_404_NOT_FOUND))
        assert_that(_details(context, context.agent.id).status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_a_running_agent_has_its_status_restarts_and_last_day_of_usage():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-det-e@example.com", "owner-det-f@example.com"),
            _reports(lambda c: {c.cy.id: _reading(1.0, 0.1)}),
            _cluster_says(),
            *_platform_admin("admin-details@example.com"),
        ]
    ) as context:
        with when("the admin opens an agent in another organization"):
            response = _details(context, context.cy.id)

        with then("the agent is named from the database, with its organization"):
            body = response.json()
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(body["name"], equal_to("Cy"))
            assert_that(body["status"], equal_to("RUNNING"))
            assert_that(body["organization_id"], equal_to(str(context.globex.id)))
            assert_that(body["organization_name"], equal_to(context.globex.name))
            assert_that(body["effective_model"], is_not(none()))

        with then("it is working, and says how often it restarted and why the last one ended"):
            assert_that(body["health_status"], equal_to("ok"))
            assert_that(body["restart_count"], equal_to(3))
            assert_that(body["termination_reason"], equal_to("OOMKilled"))

        with then("its usage covers the last 24 hours, with the limits it runs with"):
            usage = body["resource_usage"]
            assert_that(usage["range"], equal_to("24h"))
            assert_that(usage["availability"], equal_to("available"))
            assert_that(usage["state"], equal_to("reporting"))
            assert_that(usage["memory_working_set_bytes"], equal_to(1 * _GiB))
            assert_that(usage["memory_limit_bytes"], equal_to(2 * _GiB))
            assert_that(usage["cpu_limit_cores"], equal_to(1))


def test_an_opened_row_carries_the_agents_request_beside_its_limit():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-det-req-a@example.com", "owner-det-req-b@example.com"),
            _reports(lambda c: {c.cy.id: _reading(1.0, 0.1)}),
            prometheus_reports_agent_requests(lambda c: {c.cy.id: (0.5 * _GiB, 0.1)}),
            _cluster_says(),
            *_platform_admin("admin-details-req@example.com"),
        ]
    ) as context:
        usage = _details(context, context.cy.id).json()["resource_usage"]

        assert_that(usage["memory_request_bytes"], equal_to(int(0.5 * _GiB)))
        assert_that(usage["memory_limit_bytes"], equal_to(2 * _GiB))
        assert_that(usage["cpu_request_cores"], close_to(0.1, 1e-9))
        assert_that(usage["cpu_limit_cores"], equal_to(1))


def test_an_opened_row_asks_only_about_that_agents_requests():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-det-req-c@example.com", "owner-det-req-d@example.com"),
            _reports(lambda c: {c.cy.id: _reading(1.0, 0.1)}),
            _cluster_says(),
            *_platform_admin("admin-details-req-scope@example.com"),
        ]
    ) as context:
        _details(context, context.cy.id)

        queries = [call.args[0] for call in _prometheus(context).query.call_args_list]
        requests = [q for q in queries if '"app", "$1", "pod"' in q]
        assert_that(requests, has_length(1))
        assert_that(requests[0], contains_string(f'pod=~"agent-{context.cy.id}-.+"'))
        assert_that(requests[0], not_(contains_string(str(context.ada.id))))


def test_the_page_never_asks_the_cluster_for_logs_and_none_come_back():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-det-g@example.com", "owner-det-h@example.com"),
            _reports(lambda c: {c.cy.id: _reading(1.0, 0.1)}),
            _cluster_says(),
            *_platform_admin("admin-details-leaks@example.com"),
        ]
    ) as context:
        response = _details(context, context.cy.id)

        # The call asks for no logs at all, so there is nothing to filter out afterwards.
        k8s: Any = context.injector.get(KubernetesClient)
        assert_that(k8s.get_runtime_diagnostics.call_args.kwargs, equal_to({"include_logs": False}))
        # And what the cluster did hand back that is free text stays out of the answer.
        assert _SECRET_LOG not in response.text
        assert _SECRET_REASON not in response.text
        # The model is an allowlist: exactly these fields, nothing added by accident.
        assert_that(
            sorted(response.json()),
            equal_to(
                sorted(
                    [
                        "agent_id",
                        "name",
                        "status",
                        "agent_type",
                        "effective_model",
                        "created_at",
                        "organization_id",
                        "organization_name",
                        "last_error_summary",
                        "health_status",
                        "restart_count",
                        "termination_reason",
                        "resource_usage",
                    ]
                )
            ),
        )


def test_an_agent_in_error_shows_its_fixed_copy_summary_and_not_the_detail():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-det-i@example.com", "owner-det-j@example.com"),
            _cy_failed_with("QUOTA_EXHAUSTED", "requested 2Gi, namespace has 0Gi left"),
            _cluster_says(),
            *_platform_admin("admin-details-error@example.com"),
        ]
    ) as context:
        body = _details(context, context.cy.id).json()

        summary = persisted_provisioning_error(code="QUOTA_EXHAUSTED", detail=None, legacy_message=None)
        assert summary is not None
        assert_that(body["status"], equal_to("ERROR"))
        assert_that(body["health_status"], equal_to("error"))
        assert_that(body["last_error_summary"], equal_to(summary.summary))
        assert "0Gi" not in str(body)


def test_a_legacy_failure_message_straight_from_the_cluster_is_not_shown():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-det-k@example.com", "owner-det-l@example.com"),
            _cy_failed_with(None, None, legacy="pods is forbidden: User system:serviceaccount:agent-farm cannot"),
            _cluster_says(),
            *_platform_admin("admin-details-legacy@example.com"),
        ]
    ) as context:
        body = _details(context, context.cy.id).json()

        # Reported as an unclassified failure, the stored text dropped, as in the product.
        assert_that(body["last_error_summary"], is_not(none()))
        assert "forbidden" not in str(body)


def test_a_stopped_agent_has_no_container_to_ask_about():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-det-m@example.com", "owner-det-n@example.com", second_status=AgentStatus.STOPPED),
            _cluster_says(),
            *_platform_admin("admin-details-stopped@example.com"),
        ]
    ) as context:
        body = _details(context, context.cy.id).json()

        assert_that(body["status"], equal_to("STOPPED"))
        assert_that(body["health_status"], none())
        assert_that(body["restart_count"], none())
        assert_that(body["resource_usage"], none())
        assert_that(body["last_error_summary"], none())
        k8s: Any = context.injector.get(KubernetesClient)
        k8s.get_pod_readiness.assert_not_called()
        k8s.get_runtime_diagnostics.assert_not_called()
        _prometheus(context).query.assert_not_called()


def test_an_unreachable_healthz_or_cluster_leaves_those_fields_empty_and_the_rest_in_place():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-det-o@example.com", "owner-det-p@example.com"),
            _reports(lambda c: {c.cy.id: _reading(1.0, 0.1)}),
            _cluster_says(healthz=RuntimeError("unreachable"), diagnostics=RuntimeError("cluster down")),
            *_platform_admin("admin-details-down@example.com"),
        ]
    ) as context:
        response = _details(context, context.cy.id)

        # The Organization route answers 503 for these. A row that is opened should still
        # show what is known, so here they are just empty.
        body = response.json()
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(body["health_status"], none())
        assert_that(body["restart_count"], none())
        assert_that(body["termination_reason"], none())
        assert_that(body["resource_usage"]["availability"], equal_to("available"))


def test_an_unreachable_prometheus_leaves_usage_unavailable_and_the_rest_in_place():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-det-q@example.com", "owner-det-r@example.com"),
            prometheus_is_down(),
            _cluster_says(),
            *_platform_admin("admin-details-prom@example.com"),
        ]
    ) as context:
        body = _details(context, context.cy.id).json()

        assert_that(body["resource_usage"]["availability"], equal_to("unavailable"))
        assert_that(body["health_status"], equal_to("ok"))
        assert_that(body["restart_count"], equal_to(3))


def test_a_cluster_error_asking_about_the_pod_leaves_health_empty_and_the_rest_in_place():
    """An API-server hiccup on the pod lookup must not fail the row, as the restart read does not."""

    def pod_lookup_fails(context):
        k8s: Any = context.injector.get(KubernetesClient)
        k8s.get_pod_readiness.side_effect = ApiException(status=500, reason="API server hiccup")

    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("owner-det-s@example.com", "owner-det-t@example.com"),
            _reports(lambda c: {c.cy.id: _reading(1.0, 0.1)}),
            _cluster_says(),
            pod_lookup_fails,
            *_platform_admin("admin-details-pod@example.com"),
        ]
    ) as context:
        response = _details(context, context.cy.id)

        body = response.json()
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(body["health_status"], none())
        # Everything the cluster could still answer is there.
        assert_that(body["name"], equal_to("Cy"))
        assert_that(body["restart_count"], equal_to(3))
        assert_that(body["resource_usage"]["availability"], equal_to("available"))
