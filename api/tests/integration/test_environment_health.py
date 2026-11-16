"""Integration tests for the environment health page (AF-266).

A Platform Administrator reads the namespace's health without an Active Organization, so the
scenarios seed more than one Organization. The cluster and Prometheus are mocks that answer
what each scenario says; the rules for reading their objects are covered field by field in
`tests/unit/test_environment_health_cluster.py`.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4, uuid7

import pytest
from fastapi import status
from hamcrest import assert_that, contains_exactly, equal_to, has_entries, has_item, none, not_none
from kubernetes.client import (
    CoreV1Event,
    V1ContainerState,
    V1ContainerStateWaiting,
    V1ContainerStatus,
    V1CronJob,
    V1CronJobSpec,
    V1CronJobStatus,
    V1Deployment,
    V1DeploymentCondition,
    V1DeploymentSpec,
    V1DeploymentStatus,
    V1Job,
    V1JobCondition,
    V1JobStatus,
    V1JobTemplateSpec,
    V1LabelSelector,
    V1ObjectMeta,
    V1ObjectReference,
    V1OwnerReference,
    V1PersistentVolumeClaim,
    V1PersistentVolumeClaimSpec,
    V1PersistentVolumeClaimStatus,
    V1Pod,
    V1PodCondition,
    V1PodStatus,
    V1PodTemplateSpec,
    V1ResourceQuota,
    V1ResourceQuotaStatus,
    V1Service,
    V1VolumeResourceRequirements,
)
from kubernetes.client.exceptions import ApiException
from kubernetes.config import ConfigException
from sqlmodel import Session

from api.domains.agents.models import Agent, AgentRestorePoint, AgentStatus, RestorePointOrigin, RestorePointStatus
from api.domains.agents.repository import AgentRepository
from api.domains.environment_health import cluster
from api.domains.restore_points.repository import RestorePointRepository
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.prometheus.client import PrometheusClient, PrometheusError, PrometheusSample
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.conversation import there_is_a_recorded_message
from api.tests.steps.cost import cost_records_are_clean, there_are_cost_records
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
        "list_replica_sets",
        "list_pvcs",
        "list_services",
        "list_cron_jobs",
        "list_namespace_jobs",
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


def response_text(body) -> str:
    return json.dumps(body)


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

        assert_that(body["level"], equal_to("warning"))
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


def test_volume_claims_and_services_are_counted_against_their_entered_ceilings():
    with given([*_BASE_GIVEN, *_platform_admin("env-admin-counts@example.com")]) as context:
        _quiet_cluster(context)
        k8s = _cluster(context)
        k8s.list_resource_quotas.side_effect = _forbidden()
        k8s.list_pvcs.return_value = [_claim(f"agent-{uuid4()}", "1Gi") for _ in range(60)]
        k8s.list_services.return_value = [V1Service(metadata=V1ObjectMeta(name=f"svc-{n}")) for n in range(8)]
        context.client.put(
            "/api/v1/platform/resource-limits",
            json={"persistentvolumeclaims": 60, "services": 40},
            headers=_auth(context.access_token),
        )

        body = _get(context).json()

        assert_that(_sources(body)["services"], equal_to("available"))
        lines = {line["resource"]: line for line in body["capacity"]}
        assert_that(
            lines["persistentvolumeclaims"],
            has_entries(source="entered", unit="count", used=60, hard=60, level="critical"),
        )
        assert_that(lines["services"], has_entries(used=8, hard=40, level="ok"))
        assert_that(body["ceilings"], has_entries(persistentvolumeclaims=60, services=40))


def test_a_spike_in_the_last_day_shows_beside_the_current_figure():
    with given([*_BASE_GIVEN, *_platform_admin("env-admin-peaks@example.com")]) as context:
        _quiet_cluster(context)
        k8s = _cluster(context)
        k8s.list_resource_quotas.side_effect = _forbidden()
        k8s.list_pods.return_value = [_pod(f"p-{n}") for n in range(5)]
        context.client.put(
            "/api/v1/platform/resource-limits",
            json={"limits_cpu_cores": 40, "pods": 50},
            headers=_auth(context.access_token),
        )

        def answer(promql: str, at):
            if promql.startswith("max_over_time(count("):
                return [PrometheusSample({}, 21.0)]
            if promql.startswith("max_over_time("):
                return [PrometheusSample({"kind": "limits", "resource": "cpu"}, 39.6)]
            if "kube_pod_container_resource" in promql:
                return [PrometheusSample({"kind": "limits", "resource": "cpu"}, 10.0)]
            return []

        _prometheus(context).query.side_effect = answer

        body = _get(context).json()

        lines = {line["resource"]: line for line in body["capacity"]}
        assert_that(lines["limits.cpu"], has_entries(used=10.0, peak=39.6, peak_ratio=0.99, level="warning"))
        assert_that(lines["pods"], has_entries(used=5, peak=21, level="ok"))
        assert_that(lines["requests.storage"], has_entries(peak=none()))
        assert_that(body["peak_window_hours"], equal_to(24))
        assert_that(body["level"], equal_to("warning"))


def test_peaks_that_cannot_be_read_leave_the_current_figures():
    with given([*_BASE_GIVEN, *_platform_admin("env-admin-peaks-down@example.com")]) as context:
        _quiet_cluster(context)
        _cluster(context).list_resource_quotas.side_effect = _forbidden()
        context.client.put(
            "/api/v1/platform/resource-limits", json={"limits_cpu_cores": 40}, headers=_auth(context.access_token)
        )

        def answer(promql: str, at):
            if promql.startswith("max_over_time("):
                raise PrometheusError("Prometheus request failed: ReadTimeout")
            if "kube_pod_container_resource" in promql:
                return [PrometheusSample({"kind": "limits", "resource": "cpu"}, 10.0)]
            return []

        _prometheus(context).query.side_effect = answer

        response = _get(context)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        lines = {line["resource"]: line for line in response.json()["capacity"]}
        assert_that(lines["limits.cpu"], has_entries(used=10.0, peak=none(), level="ok"))


def test_a_pod_oom_killed_through_the_week_is_listed_from_its_restart_history():
    with given([*_BASE_GIVEN, *_platform_admin("env-admin-restarts@example.com")]) as context:
        _quiet_cluster(context)
        _cluster(context).list_pods.return_value = [_pod("rabbitmq-0"), _pod("agentbarn-api-1")]

        def answer(promql: str, at):
            if "kube_pod_container_status_restarts_total" in promql:
                return [
                    PrometheusSample({"pod": "rabbitmq-0", "signal": "restarts"}, 15.0),
                    PrometheusSample({"pod": "rabbitmq-0", "signal": "oom_killed"}, 1.0),
                    PrometheusSample({"pod": "agentbarn-api-1", "signal": "restarts"}, 1.0),
                ]
            return []

        _prometheus(context).query.side_effect = answer

        body = _get(context).json()

        assert_that(body["restart_window_days"], equal_to(7))
        assert_that(
            body["workloads"]["issues"],
            contains_exactly(
                has_entries(pod_name="rabbitmq-0", restarts_in_window=15, oom_killed=True, repeatedly_restarting=True)
            ),
        )
        assert_that(body["level"], equal_to("warning"))


def test_without_restart_history_the_pods_are_still_judged_by_themselves():
    with given([*_BASE_GIVEN, *_platform_admin("env-admin-restarts-down@example.com")]) as context:
        _quiet_cluster(context)
        _cluster(context).list_pods.return_value = [_pod("worker-1", ready=False, waiting="CrashLoopBackOff")]

        def answer(promql: str, at):
            if "kube_pod_container_status_restarts_total" in promql:
                raise PrometheusError("Prometheus request failed: ReadTimeout")
            return []

        _prometheus(context).query.side_effect = answer

        body = _get(context).json()

        assert_that(_sources(body)["prometheus"], equal_to("unavailable"))
        assert_that(
            body["workloads"]["issues"],
            contains_exactly(has_entries(pod_name="worker-1", restarts_in_window=none(), oom_killed=False)),
        )


def _released(name: str, sha: str, rolled_out_at: datetime) -> V1Deployment:
    return V1Deployment(
        metadata=V1ObjectMeta(name=name),
        spec=V1DeploymentSpec(
            replicas=1,
            selector=V1LabelSelector(),
            template=V1PodTemplateSpec(metadata=V1ObjectMeta(annotations={"build-sha": sha})),
        ),
        status=V1DeploymentStatus(
            ready_replicas=1,
            conditions=[
                V1DeploymentCondition(
                    type="Progressing", status="True", reason="NewReplicaSetAvailable", last_update_time=rolled_out_at
                )
            ],
        ),
    )


def test_the_deployed_build_and_when_it_rolled_out_are_shown():
    with given([*_BASE_GIVEN, *_platform_admin("env-admin-deployed@example.com")]) as context:
        _quiet_cluster(context)
        six_days_ago = datetime(2026, 11, 6, 9, 30, tzinfo=UTC)
        sha = "7f306e1b4c2d9a8e5f60718293a4b5c6d7e8f901"
        _cluster(context).list_deployments.return_value = [
            _released("agentbarn-api", sha, six_days_ago),
            _released("agentbarn-ui", sha, six_days_ago),
        ]

        body = _get(context).json()

        assert_that(
            body["deployed"],
            has_entries(build_sha=sha, rolled_out_at="2026-11-06T09:30:00Z", mixed=False, behind=[]),
        )
        assert_that(body["services"], has_item(has_entries(name="agentbarn-ui", build_sha=sha, rollout="complete")))
        assert_that(body["level"], equal_to("ok"))


def test_services_left_on_an_older_build_are_a_warning():
    with given([*_BASE_GIVEN, *_platform_admin("env-admin-mixed@example.com")]) as context:
        _quiet_cluster(context)
        now = datetime.now(UTC)
        _cluster(context).list_deployments.return_value = [
            _released("agentbarn-api", "7f306e1b", now - timedelta(hours=1)),
            _released("agentbarn-gateway", "0123abcd", now - timedelta(days=20)),
        ]

        body = _get(context).json()

        assert_that(body["deployed"], has_entries(build_sha="7f306e1b", mixed=True, behind=["agentbarn-gateway"]))
        assert_that(body["level"], equal_to("warning"))


def test_a_cron_job_whose_last_run_failed_is_listed_first_and_warns():
    with given([*_BASE_GIVEN, *_platform_admin("env-admin-cron@example.com")]) as context:
        _quiet_cluster(context)
        now = datetime.now(UTC)
        k8s = _cluster(context)
        k8s.list_cron_jobs.return_value = [
            V1CronJob(
                metadata=V1ObjectMeta(name=name, creation_timestamp=now - timedelta(days=30)),
                spec=V1CronJobSpec(schedule="2-59/5 * * * *", job_template=V1JobTemplateSpec()),
                status=V1CronJobStatus(
                    last_schedule_time=now - timedelta(minutes=1),
                    last_successful_time=now - timedelta(minutes=6),
                ),
            )
            for name in ("agentbarn-event-reconciler", "agentbarn-restore-point-schedule")
        ]
        k8s.list_namespace_jobs.return_value = [
            V1Job(
                metadata=V1ObjectMeta(
                    name="agentbarn-restore-point-schedule-29001",
                    creation_timestamp=now - timedelta(minutes=1),
                    owner_references=[
                        V1OwnerReference(
                            api_version="batch/v1", kind="CronJob", name="agentbarn-restore-point-schedule", uid="1"
                        )
                    ],
                ),
                status=V1JobStatus(conditions=[V1JobCondition(type="Failed", status="True", last_transition_time=now)]),
            )
        ]

        body = _get(context).json()

        assert_that(_sources(body), has_entries(cron_jobs="available", jobs="available"))
        assert_that(
            body["cron_jobs"],
            contains_exactly(
                has_entries(name="agentbarn-restore-point-schedule", state="failing", schedule="2-59/5 * * * *"),
                has_entries(name="agentbarn-event-reconciler", state="ok"),
            ),
        )
        assert_that(body["level"], equal_to("warning"))


def test_refused_cron_jobs_say_so_and_leave_the_rest():
    with given([*_BASE_GIVEN, *_platform_admin("env-admin-cron-refused@example.com")]) as context:
        _quiet_cluster(context)
        _cluster(context).list_cron_jobs.side_effect = _forbidden()

        body = _get(context).json()

        assert_that(_sources(body)["cron_jobs"], equal_to("forbidden"))
        assert_that(body["cron_jobs"], equal_to([]))
        assert_that(body["level"], equal_to("ok"))


def _backdate(context, agent, age: timedelta) -> None:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        row = session.get(Agent, agent.id)
        assert row is not None
        row.created_at = datetime.now(UTC) - age
        session.add(row)
        session.commit()


def _scheduled(context, agent, status: RestorePointStatus, age: timedelta, origin=RestorePointOrigin.SCHEDULED):
    context.injector.get(RestorePointRepository).save(
        AgentRestorePoint(
            agent_id=agent.id,
            status=status,
            origin=origin,
            agent_type=agent.agent_type,
            pvc_name=f"restore-point-{uuid4()}",
            config_manifest={},
            failure_reason="Job failed: token=abc" if status == RestorePointStatus.FAILED else None,
            created_at=datetime.now(UTC) - age,
        )
    )


def test_failing_and_overdue_scheduled_backups_are_counted_and_named_by_agent():
    with given(
        [
            *_BASE_GIVEN,
            _two_organizations("env-backups-1@example.com", "env-backups-2@example.com"),
            *_platform_admin("env-admin-backups@example.com"),
        ]
    ) as context:
        _quiet_cluster(context)
        ada, cy = context.ada, context.cy
        there_is_an_agent(name="Bo", status=AgentStatus.RUNNING)(context)
        bo = context.agent
        there_is_an_agent(name="Dee", status=AgentStatus.RUNNING)(context)
        there_is_an_agent(name="Eve", status=AgentStatus.RUNNING)(context)
        eve = context.agent
        for agent in (ada, bo, cy, eve):
            _backdate(context, agent, timedelta(days=3))
        # Ada's last good backup is two days old and the two tries since failed.
        _scheduled(context, ada, RestorePointStatus.READY, timedelta(days=2))
        _scheduled(context, ada, RestorePointStatus.FAILED, timedelta(hours=7))
        _scheduled(context, ada, RestorePointStatus.FAILED, timedelta(hours=1))
        # A failure from last week, and a manual capture, are not scheduled backups failing now.
        _scheduled(context, ada, RestorePointStatus.FAILED, timedelta(days=6))
        _scheduled(context, bo, RestorePointStatus.FAILED, timedelta(hours=2), origin=RestorePointOrigin.MANUAL)
        _scheduled(context, bo, RestorePointStatus.READY, timedelta(hours=1))
        # Eve's last good backup is two days old and nothing has been tried since.
        _scheduled(context, eve, RestorePointStatus.READY, timedelta(days=2))
        # Cy is stopped, so it is not backed up on a schedule; Dee is new and has not had its turn.

        body = _get(context).json()

        backups = body["backups"]
        # Ada is overdue too, but is counted and named once, as failing.
        assert_that(backups, has_entries(enabled=True, interval_minutes=360, failed_total=1, overdue_total=1))
        assert_that(
            backups["failed"],
            contains_exactly(
                has_entries(agent=has_entries(agent_name="Ada", organization_name=context.acme.name), failures=2)
            ),
        )
        assert_that(
            backups["overdue"],
            contains_exactly(has_entries(agent=has_entries(agent_name="Eve"), last_backup_at=not_none())),
        )
        assert_that("token=abc" not in response_text(body), equal_to(True))
        assert_that(body["level"], equal_to("warning"))


def test_with_scheduled_backups_switched_off_none_are_overdue():
    with given(
        [
            set_env_variable({"RESTORE_POINT_SCHEDULE_INTERVAL_MINUTES": "0"}),
            *_BASE_GIVEN,
            _two_organizations("env-backups-off-1@example.com", "env-backups-off-2@example.com"),
            *_platform_admin("env-admin-backups-off@example.com"),
        ]
    ) as context:
        _quiet_cluster(context)
        _backdate(context, context.ada, timedelta(days=3))

        body = _get(context).json()

        assert_that(body["backups"], has_entries(enabled=False, failed=[], overdue=[]))
        assert_that(body["level"], equal_to("ok"))


def test_agents_no_one_wrote_to_for_two_weeks_are_listed_with_what_they_hold():
    with given(
        [
            # Off, so the overdue backups of these month-old Agents do not decide the level.
            set_env_variable({"RESTORE_POINT_SCHEDULE_INTERVAL_MINUTES": "0"}),
            *_BASE_GIVEN,
            cost_records_are_clean(),
            _two_organizations("env-idle-1@example.com", "env-idle-2@example.com"),
            *_platform_admin("env-admin-idle@example.com"),
        ]
    ) as context:
        _quiet_cluster(context)
        ada, cy = context.ada, context.cy
        there_is_an_agent(name="Bo", status=AgentStatus.RUNNING)(context)
        bo = context.agent
        for agent in (ada, bo, cy):
            _backdate(context, agent, timedelta(days=30))
        now = datetime.now(UTC)
        # Ada was last written to three weeks ago, but the platform woke it an hour ago.
        context.agent = ada
        there_is_a_recorded_message(occurred_at=now - timedelta(days=21))(context)
        there_are_cost_records(agent_id=ada.id, occurred_at=now - timedelta(hours=1))(context)
        _scheduled(context, ada, RestorePointStatus.READY, timedelta(hours=2))
        # Bo was written to yesterday; Cy, stopped, never.
        context.agent = bo
        there_is_a_recorded_message(occurred_at=now - timedelta(days=1))(context)
        _cluster(context).list_pvcs.return_value = [_claim(f"agent-{ada.id}", "2Gi", _agent_labels(ada.id))]
        _cluster(context).list_pods.return_value = [_pod(f"agent-{ada.id}-1-a", _agent_labels(ada.id))]

        body = _get(context).json()

        assert_that(body["idle_after_days"], equal_to(14))
        assert_that(
            body["idle_agents"],
            contains_exactly(
                has_entries(agent=has_entries(agent_name="Cy"), last_user_message_at=none(), holds_pod=False),
                has_entries(
                    agent=has_entries(agent_name="Ada", organization_name=context.acme.name),
                    last_user_message_at=not_none(),
                    last_call_at=not_none(),
                    holds_pod=True,
                    volume_claims=1,
                    requested_bytes=2 * _GiB,
                    restore_points=1,
                ),
            ),
        )
        # A cleanup candidate is not a fault.
        assert_that(body["level"], equal_to("ok"))


def test_a_long_list_carries_the_worst_rows_and_says_how_many_there_are(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cluster, "LIST_LIMIT", 1)
    with given(
        [
            set_env_variable({"RESTORE_POINT_SCHEDULE_INTERVAL_MINUTES": "0"}),
            *_BASE_GIVEN,
            _two_organizations("env-limit-1@example.com", "env-limit-2@example.com"),
            *_platform_admin("env-admin-limit@example.com"),
        ]
    ) as context:
        _quiet_cluster(context)
        for agent in (context.ada, context.cy):
            _backdate(context, agent, timedelta(days=30))
        _cluster(context).list_pods.return_value = [
            _pod("agentbarn-api-1-a", {"app": "agentbarn-api"}, ready=False),
            _pod("agentbarn-ui-1-a", {"app": "agentbarn-ui"}, ready=False),
        ]

        body = _get(context).json()

        assert_that(len(body["idle_agents"]), equal_to(1))
        assert_that(len(body["workloads"]["issues"]), equal_to(1))
        assert_that(body["totals"], has_entries(idle_agents=2, pod_issues=2))
        # The level is worked out from every row, not only those carried.
        assert_that(body["level"], equal_to("warning"))


def test_refused_services_leave_their_line_unknown():
    with given([*_BASE_GIVEN, *_platform_admin("env-admin-services-refused@example.com")]) as context:
        _quiet_cluster(context)
        k8s = _cluster(context)
        k8s.list_resource_quotas.side_effect = _forbidden()
        k8s.list_services.side_effect = _forbidden()

        body = _get(context).json()

        assert_that(_sources(body)["services"], equal_to("forbidden"))
        lines = {line["resource"]: line for line in body["capacity"]}
        assert_that(lines["services"], has_entries(used=none(), level="unknown"))


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
            "list_replica_sets",
            "list_pvcs",
            "list_services",
            "list_cron_jobs",
            "list_namespace_jobs",
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
        assert_that(body["level"], equal_to("warning"))


def test_a_failed_runtime_query_keeps_the_firing_alerts():
    with given([*_BASE_GIVEN, *_platform_admin("env-admin-prom-half@example.com")]) as context:
        _quiet_cluster(context)
        _cluster(context).list_pods.return_value = [_pod("agentbarn-api-1")]

        def answer(promql: str, at):
            if "ALERTS" in promql:
                return [PrometheusSample({"alertname": "APIDown", "severity": "critical"}, 1.0)]
            raise PrometheusError("Prometheus request failed: ReadTimeout")

        _prometheus(context).query.side_effect = answer

        body = _get(context).json()

        assert_that(_sources(body)["prometheus"], equal_to("unavailable"))
        assert_that([a["name"] for a in body["alerts"]], contains_exactly("APIDown"))
        assert_that(body["level"], equal_to("critical"))


def test_a_lost_volume_makes_the_overall_health_a_warning():
    with given([*_BASE_GIVEN, *_platform_admin("env-admin-lost@example.com")]) as context:
        _quiet_cluster(context)
        claim = _claim("lost-volume", "1Gi")
        claim.status.phase = "Lost"
        _cluster(context).list_pvcs.return_value = [claim]

        body = _get(context).json()

        assert_that(body["volumes"]["attention"], contains_exactly(has_entries(name="lost-volume", phase="Lost")))
        assert_that(body["level"], equal_to("warning"))
