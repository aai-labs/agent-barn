"""Integration tests for the environment health page (AF-266).

A Platform Administrator reads the namespace's health without an Active Organization, so the
scenarios seed more than one Organization. The cluster and Prometheus are mocks that answer
what each scenario says; the rules for reading their objects are covered field by field in
`tests/unit/test_environment_health_cluster.py`.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4, uuid7

from fastapi import status
from hamcrest import assert_that, contains_exactly, equal_to, has_entries, has_item, none
from kubernetes.client import (
    CoreV1Event,
    V1ContainerState,
    V1ContainerStateWaiting,
    V1ContainerStatus,
    V1Deployment,
    V1DeploymentSpec,
    V1DeploymentStatus,
    V1LabelSelector,
    V1ObjectMeta,
    V1ObjectReference,
    V1PersistentVolumeClaim,
    V1PersistentVolumeClaimSpec,
    V1PersistentVolumeClaimStatus,
    V1Pod,
    V1PodCondition,
    V1PodStatus,
    V1PodTemplateSpec,
    V1ResourceQuota,
    V1ResourceQuotaStatus,
    V1VolumeResourceRequirements,
)
from kubernetes.client.exceptions import ApiException
from kubernetes.config import ConfigException

from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.prometheus.client import PrometheusClient, PrometheusError, PrometheusSample
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.resource_usage import MockPrometheusModule, prometheus_is_not_configured
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_URL = "/api/v1/platform/environment-health"
_GiB = 1024**3

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


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _platform_admin(email: str):
    """A Platform Administrator with no Membership, whose token lands last in context."""
    admin_id = uuid7()

    def step(context):
        original_organization = getattr(context, "organization", None)
        context.organization = None
        there_is_a_user(id=admin_id, email=email, is_platform_admin=True)(context)
        context.organization = original_organization
        there_is_an_access_token_for_user(user_id=admin_id)(context)

    return [step]


def _two_organizations(first_email: str, second_email: str):
    """Acme with a running "Ada" and Globex with a stopped "Cy", as context.ada / context.cy."""

    def step(context):
        there_is_an_organization_with_user_and_access_token(email=first_email)(context)
        there_is_a_template()(context)
        there_is_an_agent(name="Ada", status=AgentStatus.RUNNING)(context)
        context.acme, context.ada = context.organization, context.agent
        context.organization = None
        there_is_an_organization_with_user_and_access_token(email=second_email)(context)
        there_is_a_template()(context)
        there_is_an_agent(name="Cy", status=AgentStatus.STOPPED)(context)
        context.globex, context.cy = context.organization, context.agent
        context.organization = context.acme

    return step


def _cluster(context) -> Any:
    """The scenario's mock cluster, which the type checker cannot see through."""
    return context.injector.get(KubernetesClient)


def _prometheus(context) -> Any:
    return context.injector.get(PrometheusClient)


def _quiet_cluster(context) -> None:
    """A namespace that answers every read with nothing."""
    k8s = _cluster(context)
    for method in (
        "list_pods",
        "list_deployments",
        "list_stateful_sets",
        "list_pvcs",
        "list_resource_quotas",
        "list_warning_events",
    ):
        getattr(k8s, method).return_value = []
        getattr(k8s, method).side_effect = None


def _agent_labels(agent_id, org_label=None) -> dict[str, str]:
    return {"app": f"agent-{agent_id}", "org-id": org_label or str(uuid4()), "agentbarn.io/component": "agent"}


def _claim(name: str, size: str, labels: dict[str, str] | None = None) -> V1PersistentVolumeClaim:
    return V1PersistentVolumeClaim(
        metadata=V1ObjectMeta(name=name, labels=labels),
        spec=V1PersistentVolumeClaimSpec(resources=V1VolumeResourceRequirements(requests={"storage": size})),
        status=V1PersistentVolumeClaimStatus(phase="Bound"),
    )


def _pod(name: str, labels: dict[str, str] | None = None, *, ready: bool = True, waiting: str | None = None) -> V1Pod:
    return V1Pod(
        metadata=V1ObjectMeta(name=name, labels=labels, creation_timestamp=datetime.now(UTC) - timedelta(hours=1)),
        status=V1PodStatus(
            phase="Running",
            conditions=[V1PodCondition(type="Ready", status="True" if ready else "False")],
            container_statuses=[
                V1ContainerStatus(
                    name="agent",
                    image="x",
                    image_id="",
                    ready=ready,
                    restart_count=4 if waiting else 0,
                    state=V1ContainerState(waiting=V1ContainerStateWaiting(reason=waiting)) if waiting else None,
                )
            ],
        ),
    )


def _deployment(name: str, ready: int) -> V1Deployment:
    return V1Deployment(
        metadata=V1ObjectMeta(name=name),
        spec=V1DeploymentSpec(replicas=1, selector=V1LabelSelector(), template=V1PodTemplateSpec()),
        status=V1DeploymentStatus(ready_replicas=ready),
    )


def _forbidden() -> ApiException:
    return ApiException(status=403, reason="Forbidden")


def _get(context):
    return context.client.get(_URL, headers=_auth(context.access_token))


def _sources(body) -> dict[str, str]:
    return {row["source"]: row["state"] for row in body["sources"]}


# --- authorization -------------------------------------------------------


def test_environment_health_requires_authentication():
    with given(_BASE_GIVEN) as context:
        assert_that(context.client.get(_URL).status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_an_organization_owner_is_refused_and_the_cluster_is_never_asked():
    with given(
        [*_BASE_GIVEN, there_is_an_organization_with_user_and_access_token(email="env-owner@example.com")]
    ) as context:
        _quiet_cluster(context)

        response = _get(context)

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        _cluster(context).list_pods.assert_not_called()
        _prometheus(context).query.assert_not_called()


# --- the whole page ------------------------------------------------------


def test_the_page_names_agents_from_the_database_across_organizations():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("env-a@example.com", "env-b@example.com"),
            *_platform_admin("env-admin@example.com"),
        ]
    ) as context:
        _quiet_cluster(context)
        ada, cy, gone = context.ada.id, context.cy.id, uuid4()
        k8s = _cluster(context)
        k8s.list_pods.return_value = [
            _pod("agentbarn-api-1"),
            _pod(
                f"agent-{ada}-1-a",
                _agent_labels(ada, org_label=str(context.globex.id)),
                ready=False,
                waiting="CrashLoopBackOff",
            ),
        ]
        k8s.list_deployments.return_value = [_deployment("agentbarn-api", 1), _deployment("litellm", 0)]
        k8s.list_pvcs.return_value = [
            _claim(f"agent-{ada}", "1Gi", _agent_labels(ada)),
            _claim(f"agent-{cy}", "1Gi", _agent_labels(cy)),
            _claim(f"agent-{gone}", "1Gi", _agent_labels(gone)),
            _claim("data-postgres-app-0", "10Gi"),
        ]

        def answer(promql: str, at):
            if "ALERTS" in promql:
                return [PrometheusSample({"alertname": "LiteLLMDown", "severity": "critical"}, 1.0)]
            return [PrometheusSample({"__name__": "agent_healthz_ok", "app": f"agent-{ada}"}, 0.0)]

        _prometheus(context).query.side_effect = answer

        with when("the platform admin asks"):
            response = _get(context)

        with then("every part is there, and the agent is filed under its own organization"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["level"], equal_to("critical"))
            assert_that(body["namespace"], equal_to("agent-farm"))
            assert_that(set(_sources(body).values()), equal_to({"available"}))
            assert_that([s["name"] for s in body["services"]], contains_exactly("litellm", "agentbarn-api"))
            assert_that([a["name"] for a in body["alerts"]], contains_exactly("LiteLLMDown"))

            [issue] = body["workloads"]["issues"]
            assert_that(issue["agent"], has_entries(agent_name="Ada", organization_id=str(context.acme.id)))
            [unhealthy] = body["unhealthy_runtimes"]
            assert_that(unhealthy["agent"]["agent_name"], equal_to("Ada"))
            assert_that(unhealthy["pod_ready"], equal_to(False))

            groups = {g["group"]: g["claims"] for g in body["volumes"]["groups"]}
            assert_that(
                groups,
                has_entries(active_agents=1, stopped_agents=1, orphaned=1, infrastructure=1, restore_points=0),
            )
            assert_that(body["volumes"]["total_requested_bytes"], equal_to(13 * _GiB))
            [orphan] = body["volumes"]["attention"]
            assert_that(orphan["agent"], has_entries(agent_id=str(gone), agent_name=none(), organization_id=none()))


def test_a_failed_agent_shows_its_quota_detail():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("env-c@example.com", "env-d@example.com"),
            *_platform_admin("env-admin-failed@example.com"),
        ]
    ) as context:
        _quiet_cluster(context)
        repository = context.injector.get(AgentRepository)
        agent = repository.get_by_id(context.cy.id)
        assert agent is not None
        agent.status = AgentStatus.ERROR
        agent.last_error_code = "QUOTA_EXHAUSTED"
        agent.last_error_detail = "requests.storage: requested 1Gi, used 30Gi, limit 30Gi"
        agent.last_error = "raw text from the cluster with a token=abc"
        repository.delegate.save(agent)

        body = _get(context).json()

        [failed] = body["failed_agents"]
        assert_that(failed["agent"], has_entries(agent_name="Cy", organization_name=context.globex.name))
        assert_that(failed["code"], equal_to("QUOTA_EXHAUSTED"))
        assert_that(failed["detail"], equal_to("requests.storage: requested 1Gi, used 30Gi, limit 30Gi"))
        assert "token=abc" not in str(body)


def test_a_warning_event_is_explained_and_its_message_is_not_carried():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("env-e@example.com", "env-f@example.com"),
            *_platform_admin("env-admin-events@example.com"),
        ]
    ) as context:
        _quiet_cluster(context)
        _cluster(context).list_warning_events.return_value = [
            CoreV1Event(
                metadata=V1ObjectMeta(name="x.1"),
                involved_object=V1ObjectReference(kind="Pod", name=f"agent-{context.ada.id}-1-a"),
                reason="FailedMount",
                message='MountVolume.SetUp failed for volume "creds" : secret "discord-bot-token" not found',
                type="Warning",
                count=3,
                last_timestamp=datetime.now(UTC) - timedelta(minutes=2),
            )
        ]

        body = _get(context).json()

        [event] = body["events"]
        assert_that(event["reason"], equal_to("FailedMount"))
        assert_that(event["agent"]["agent_name"], equal_to("Ada"))
        assert_that(event["count"], equal_to(3))
        assert "discord-bot-token" not in str(body)


# --- capacity ------------------------------------------------------------


def test_without_the_quota_the_entered_ceilings_are_compared_with_the_claims_and_pods():
    with given([*_BASE_GIVEN, *_platform_admin("env-admin-entered@example.com")]) as context:
        _quiet_cluster(context)
        k8s = _cluster(context)
        k8s.list_resource_quotas.side_effect = _forbidden()
        k8s.list_pvcs.return_value = [_claim(f"agent-{uuid4()}", "1Gi") for _ in range(28)]
        k8s.list_pods.return_value = [_pod(f"p-{n}") for n in range(5)]
        context.client.put(
            "/api/v1/platform/resource-limits",
            json={"requests_storage_bytes": 30 * _GiB, "pods": 50},
            headers=_auth(context.access_token),
        )

        body = _get(context).json()

        assert_that(_sources(body)["resource_quotas"], equal_to("forbidden"))
        lines = {line["resource"]: line for line in body["capacity"]}
        assert_that(
            lines["requests.storage"],
            has_entries(source="entered", used=28 * _GiB, hard=30 * _GiB, level="critical"),
        )
        assert_that(lines["pods"], has_entries(used=5, hard=50, level="ok"))
        assert_that(lines["limits.memory"], has_entries(level="unknown"))
        assert_that(body["ceilings"], has_entries(requests_storage_bytes=30 * _GiB, pods=50))
        assert_that(body["level"], equal_to("critical"))


def test_a_readable_quota_takes_over_from_the_entered_ceilings():
    with given([*_BASE_GIVEN, *_platform_admin("env-admin-quota@example.com")]) as context:
        _quiet_cluster(context)
        _cluster(context).list_resource_quotas.return_value = [
            V1ResourceQuota(
                metadata=V1ObjectMeta(name="tenant-quota"),
                status=V1ResourceQuotaStatus(hard={"requests.storage": "30Gi"}, used={"requests.storage": "12Gi"}),
            )
        ]
        context.client.put(
            "/api/v1/platform/resource-limits",
            json={"requests_storage_bytes": 10 * _GiB},
            headers=_auth(context.access_token),
        )

        body = _get(context).json()

        assert_that(
            body["capacity"],
            contains_exactly(has_entries(resource="requests.storage", source="quota", used=12 * _GiB, level="ok")),
        )


# --- degrading -----------------------------------------------------------


def test_a_refused_optional_read_leaves_the_rest_of_the_page():
    with given([*_BASE_GIVEN, *_platform_admin("env-admin-refused@example.com")]) as context:
        _quiet_cluster(context)
        k8s = _cluster(context)
        k8s.list_warning_events.side_effect = _forbidden()
        k8s.list_stateful_sets.side_effect = ApiException(status=500, reason="boom")
        k8s.list_deployments.return_value = [_deployment("agentbarn-api", 1)]

        response = _get(context)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        sources = _sources(body)
        assert_that(sources["events"], equal_to("forbidden"))
        assert_that(sources["stateful_sets"], equal_to("unavailable"))
        assert_that(sources["pods"], equal_to("available"))
        assert_that(body["services"], has_item(has_entries(name="agentbarn-api", level="ok")))
        assert_that(body["level"], equal_to("ok"))


def test_with_no_cluster_to_read_the_page_says_so_instead_of_failing():
    with given(
        [*_BASE_GIVEN, prometheus_is_not_configured(), *_platform_admin("env-admin-none@example.com")]
    ) as context:
        _quiet_cluster(context)
        k8s = _cluster(context)
        for method in (
            "list_pods",
            "list_deployments",
            "list_stateful_sets",
            "list_pvcs",
            "list_resource_quotas",
            "list_warning_events",
        ):
            getattr(k8s, method).side_effect = ConfigException("No Kubernetes cluster is configured")

        response = _get(context)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(set(_sources(body).values()), equal_to({"not_configured"}))
        assert_that(body["level"], equal_to("unknown"))
        assert_that(body["capacity"][0], has_entries(resource="requests.storage", used=none()))


def test_prometheus_being_down_leaves_the_cluster_parts():
    with given([*_BASE_GIVEN, *_platform_admin("env-admin-prom@example.com")]) as context:
        _quiet_cluster(context)
        _prometheus(context).query.side_effect = PrometheusError("Prometheus request failed: ConnectError")
        _cluster(context).list_pods.return_value = [_pod("agentbarn-api-1")]

        body = _get(context).json()

        assert_that(_sources(body)["prometheus"], equal_to("unavailable"))
        assert_that(body["workloads"]["pods_total"], equal_to(1))
        assert_that(body["alerts"], equal_to([]))
