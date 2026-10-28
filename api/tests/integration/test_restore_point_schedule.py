import uuid
from datetime import UTC, datetime, timedelta

from fastapi import status
from hamcrest import assert_that, contains_inanyorder, equal_to, has_length, none
from kubernetes.client import V1Job, V1JobStatus

from api.domains.agents.models import AgentRestorePoint, AgentStatus, RestorePointOrigin, RestorePointStatus
from api.domains.restore_points.repository import RestorePointRepository
from api.domains.restore_points.scheduling import ScheduledSnapshotRunner
from api.domains.restore_points.service import RestorePointService
from api.infrastructure.kubernetes import KubernetesClient
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
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

_BASE = "/api/v1/organizations/{organization_id}/agents"

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "API_IMAGE": "registry.example.com/agentbarn-api:test",
            "RESTORE_POINT_MAX_PER_AGENT": "2",
            "RESTORE_POINT_SCHEDULED_MAX_PER_AGENT": "2",
            "RESTORE_POINT_SCHEDULE_INTERVAL_MINUTES": "360",
            "RESTORE_POINT_SCHEDULE_MAX_CONCURRENT": "1",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
]


def _seed(context, agent, origin, *, status_value=RestorePointStatus.READY, age_minutes=0, job_name=None):
    repository: RestorePointRepository = context.injector.get(RestorePointRepository)
    return repository.save(
        AgentRestorePoint(
            agent_id=agent.id,
            status=status_value,
            origin=origin,
            agent_type=agent.agent_type,
            pvc_name=f"restore-point-{uuid.uuid4()}",
            job_name=job_name,
            config_manifest={},
            created_at=datetime.now(UTC) - timedelta(minutes=age_minutes),
        )
    )


def _remaining_ids(context, agent) -> list[uuid.UUID]:
    repository: RestorePointRepository = context.injector.get(RestorePointRepository)
    return [
        row.id
        for row in repository.find_for_agent_by_origin(
            agent.id, tuple(RestorePointOrigin), (RestorePointStatus.READY, RestorePointStatus.FAILED)
        )
    ]


def _agent(context, name, status_value):
    there_is_an_agent(name=name, status=status_value)(context)
    return context.agent


def test_the_schedule_snapshots_a_due_running_agent_beside_its_pod():
    with given(_GIVEN) as context:
        _agent(context, "Stopped", AgentStatus.STOPPED)
        recent = _agent(context, "Recently snapshotted", AgentStatus.RUNNING)
        _seed(context, recent, RestorePointOrigin.SCHEDULED, age_minutes=30)
        due = _agent(context, "Due", AgentStatus.RUNNING)
        _seed(context, due, RestorePointOrigin.SCHEDULED, age_minutes=400)
        k8s = context.injector.get(KubernetesClient)
        k8s.get_pod_name_for_deployment.return_value = "agent-pod"

        with when("the schedule runs"):
            result = context.injector.get(ScheduledSnapshotRunner).run_once()

        with then("only the due running Agent gets a snapshot, placed on its pod's node"):
            assert_that(result.started, equal_to(1))
            job = k8s.create_job.call_args.args[1]
            assert_that(job.metadata.labels["agentbarn.io/agent-id"], equal_to(str(due.id)))
            [term] = job.spec.template.spec.affinity.pod_affinity.required_during_scheduling_ignored_during_execution
            assert_that(term.label_selector.match_labels, equal_to({"app": f"agent-{due.id}"}))
            in_flight = context.injector.get(RestorePointRepository).find_in_flight_scheduled()
            assert_that([row.agent_id for row in in_flight], equal_to([due.id]))


def test_the_schedule_starts_no_more_snapshots_than_it_may_run_at_once():
    with given(_GIVEN) as context:
        busy = _agent(context, "Busy", AgentStatus.RUNNING)
        _seed(context, busy, RestorePointOrigin.SCHEDULED, status_value=RestorePointStatus.CAPTURING, job_name="rp-x")
        _agent(context, "Waiting", AgentStatus.RUNNING)
        k8s = context.injector.get(KubernetesClient)
        k8s.get_job.return_value = V1Job(status=V1JobStatus(active=1))

        with when("the schedule runs with its one slot taken"):
            result = context.injector.get(ScheduledSnapshotRunner).run_once()

        with then("the waiting Agent is left for a later run"):
            assert_that(result.in_flight, equal_to(1))
            assert_that(result.started, equal_to(0))
            k8s.create_job.assert_not_called()


def test_scheduled_snapshots_keep_the_newest_and_only_the_latest_failure():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        agent = context.agent
        oldest = _seed(context, agent, RestorePointOrigin.SCHEDULED, age_minutes=900)
        middle = _seed(context, agent, RestorePointOrigin.SCHEDULED, age_minutes=600)
        newest = _seed(context, agent, RestorePointOrigin.SCHEDULED, age_minutes=300)
        _seed(context, agent, RestorePointOrigin.SCHEDULED, status_value=RestorePointStatus.FAILED, age_minutes=800)
        last_failure = _seed(
            context, agent, RestorePointOrigin.SCHEDULED, status_value=RestorePointStatus.FAILED, age_minutes=100
        )
        k8s = context.injector.get(KubernetesClient)

        with when("retention runs"):
            context.injector.get(RestorePointService).enforce_retention(agent.id)

        with then("the oldest snapshot and the older failure are gone, with the snapshot's volume"):
            assert_that(_remaining_ids(context, agent), contains_inanyorder(middle.id, newest.id, last_failure.id))
            k8s.delete_pvc.assert_any_call(oldest.pvc_name, "agent-farm")


def test_past_the_manual_limit_the_oldest_automatic_backup_goes_but_never_the_users_or_the_newest():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        agent = context.agent
        first_manual = _seed(context, agent, RestorePointOrigin.MANUAL, age_minutes=900)
        second_manual = _seed(context, agent, RestorePointOrigin.MANUAL, age_minutes=800)
        _seed(context, agent, RestorePointOrigin.PRE_UPGRADE, age_minutes=700)
        newest_backup = _seed(context, agent, RestorePointOrigin.PRE_RESTORE, age_minutes=10)

        with when("retention runs with the manual limit of 2 passed by two backups"):
            context.injector.get(RestorePointService).enforce_retention(agent.id)

        with then("only the older backup goes"):
            assert_that(
                _remaining_ids(context, agent),
                contains_inanyorder(first_manual.id, second_manual.id, newest_backup.id),
            )


def test_a_manual_capture_replaces_a_scheduled_snapshot_in_progress():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        scheduled = _seed(
            context,
            context.agent,
            RestorePointOrigin.SCHEDULED,
            status_value=RestorePointStatus.CAPTURING,
            job_name="rp-cap-scheduled",
        )
        k8s = context.injector.get(KubernetesClient)
        k8s.get_job.return_value = V1Job(status=V1JobStatus(active=1))
        service = context.injector.get(RestorePointService)

        with when("a scheduled snapshot is running"):
            blocking = service.has_blocking_operation(context.agent.id)

        with then("it blocks nothing else on the Agent"):
            assert_that(blocking, equal_to(False))

        with when("the user captures a restore point"):
            response = context.client.post(
                f"{_BASE}/{context.agent.id}/restore-points".replace("{organization_id}", str(context.organization.id)),
                json={},
                headers={"Authorization": f"Bearer {context.access_token}"},
            )

        with then("the scheduled snapshot is stopped and removed, not failed, and the user's capture starts"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            k8s.delete_job.assert_any_call("rp-cap-scheduled", "agent-farm")
            k8s.delete_pvc.assert_any_call(scheduled.pvc_name, "agent-farm")
            assert_that(context.injector.get(RestorePointRepository).get_by_id(scheduled.id), none())
            assert_that(
                context.injector.get(RestorePointRepository).find_in_flight_scheduled(),
                has_length(0),
            )


def test_a_refused_capture_leaves_the_scheduled_snapshot_running():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        for _ in range(2):  # RESTORE_POINT_MAX_PER_AGENT
            _seed(context, context.agent, RestorePointOrigin.MANUAL)
        scheduled = _seed(
            context,
            context.agent,
            RestorePointOrigin.SCHEDULED,
            status_value=RestorePointStatus.CAPTURING,
            job_name="rp-cap-scheduled",
        )
        k8s = context.injector.get(KubernetesClient)
        k8s.get_job.return_value = V1Job(status=V1JobStatus(active=1))

        with when("the user captures with their restore points at the limit"):
            response = context.client.post(
                f"{_BASE}/{context.agent.id}/restore-points".replace("{organization_id}", str(context.organization.id)),
                json={},
                headers={"Authorization": f"Bearer {context.access_token}"},
            )

        with then("the capture is refused and the scheduled snapshot keeps running"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            k8s.delete_job.assert_not_called()
            kept = context.injector.get(RestorePointRepository).get_by_id(scheduled.id)
            assert_that(kept.status, equal_to(RestorePointStatus.CAPTURING))


def test_an_agent_with_no_running_pod_is_skipped_without_holding_back_the_next():
    with given(_GIVEN) as context:
        stuck = _agent(context, "Stuck on quota", AgentStatus.RUNNING)
        due = _agent(context, "Due", AgentStatus.RUNNING)
        _seed(context, due, RestorePointOrigin.SCHEDULED, age_minutes=400)
        k8s = context.injector.get(KubernetesClient)
        k8s.get_pod_name_for_deployment.side_effect = lambda name, _namespace: (
            None if name == f"agent-{stuck.id}" else "agent-pod"
        )

        with when("the schedule runs with one slot, the never-snapshotted Agent first in line"):
            result = context.injector.get(ScheduledSnapshotRunner).run_once()

        with then("the Agent with no running pod is passed over and the next one gets the slot"):
            assert_that(result.started, equal_to(1))
            job = k8s.create_job.call_args.args[1]
            assert_that(job.metadata.labels["agentbarn.io/agent-id"], equal_to(str(due.id)))


def test_an_agent_over_the_limit_only_by_what_retention_keeps_is_not_picked_for_trimming():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        for _ in range(2):  # RESTORE_POINT_MAX_PER_AGENT
            _seed(context, context.agent, RestorePointOrigin.MANUAL, age_minutes=900)
        _seed(context, context.agent, RestorePointOrigin.PRE_UPGRADE, age_minutes=10)

        with when("retention looks for Agents to trim"):
            over = context.injector.get(RestorePointRepository).find_agent_ids_over_retention(
                scheduled_cap=2, manual_cap=2
            )
            trimmed = context.injector.get(RestorePointService).trim_over_retention()

        with then("the Agent is not picked, since its user's captures and newest backup are kept"):
            assert_that(over, equal_to([]))
            assert_that(trimmed, equal_to(0))
            assert_that(_remaining_ids(context, context.agent), has_length(3))
