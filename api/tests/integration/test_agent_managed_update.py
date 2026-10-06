import uuid
from unittest.mock import patch

from fastapi import status
from hamcrest import assert_that, contains_string, equal_to, has_item, has_length, none, not_

from api.core.config import Config
from api.domains.agents.models import AgentRestorePoint, AgentStatus, RestorePointOrigin, RestorePointStatus
from api.domains.agents.service import AgentService
from api.domains.auth.models import CurrentUserContext
from api.domains.restore_points.repository import RestorePointRepository
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
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)

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
            "HERMES_IMAGE": "registry.example.com/agentbarn-hermes:v2",
            "OPENCLAW_IMAGE": "registry.example.com/agentbarn-openclaw:v2",
            "RESTORE_POINT_MAX_PER_AGENT": "2",
            "AGENT_UPDATE_READY_POLL_SECONDS": "0",
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


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _managed_url(context) -> str:
    return f"{_BASE}/{context.agent.id}/managed-update"


def test_wait_for_ready_returns_true_when_the_pod_reports_ready():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        service = context.injector.get(AgentService)
        k8s = context.injector.get(KubernetesClient)
        k8s.get_pod_readiness.return_value = ("ready", None)

        with when("the newest pod is ready"):
            healthy = service._wait_for_ready(context.agent.id, 10, poll_seconds=0)

        with then("the update may proceed, after a single read"):
            assert_that(healthy, equal_to(True))
            assert_that(k8s.get_pod_readiness.call_count, equal_to(1))


def test_wait_for_ready_returns_false_immediately_when_the_pod_crashed():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        service = context.injector.get(AgentService)
        k8s = context.injector.get(KubernetesClient)
        k8s.get_pod_readiness.return_value = ("crashed", "BackOff")

        with when("the new pod crash-loops"):
            healthy = service._wait_for_ready(context.agent.id, 60, poll_seconds=0)

        with then("the wait gives up at once rather than burning the timeout"):
            assert_that(healthy, equal_to(False))
            assert_that(k8s.get_pod_readiness.call_count, equal_to(1))


def test_wait_for_ready_gives_up_after_the_timeout():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        service = context.injector.get(AgentService)
        k8s = context.injector.get(KubernetesClient)
        k8s.get_pod_readiness.return_value = ("initializing", None)

        with when("the pod stays initializing past the timeout"):
            healthy = service._wait_for_ready(context.agent.id, 1, poll_seconds=0)

        with then("the wait reports the update as unhealthy"):
            assert_that(healthy, equal_to(False))
            assert_that(k8s.get_pod_readiness.call_count > 1, equal_to(True))


def test_teardown_workload_deletes_only_the_deployment():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        service = context.injector.get(AgentService)
        k8s = context.injector.get(KubernetesClient)
        namespace = context.injector.get(Config).k8s_namespace

        with when("the failed update's workload is torn down"):
            service._teardown_workload(context.agent.id)

        with then("the PVC is freed, and nothing else is touched"):
            k8s.delete_deployment.assert_called_once_with(f"agent-{context.agent.id}", namespace)
            assert_that(k8s.delete_config_map.called, equal_to(False))
            assert_that(k8s.delete_secret.called, equal_to(False))


# --- The managed-update orchestration -----------------------------------------


def _job_with(status_kwargs):
    from kubernetes.client import V1Job, V1JobStatus

    return V1Job(status=V1JobStatus(**status_kwargs))


def _user_context(context) -> CurrentUserContext:
    return CurrentUserContext(
        user=context.user,
        organization_ids=[context.organization.id],
        user_organization_map={context.organization.id: context.organization_user},
        current_user_organization=context.organization_user,
    )


def _succeed_capture_job(context) -> None:
    k8s = context.injector.get(KubernetesClient)
    k8s.get_job.return_value = _job_with({"succeeded": 1})
    k8s.read_job_logs.return_value = '{"bytes": 4096, "file_count": 12}\n'
    # A bare MagicMock log body would reach the DB insert in
    # _capture_logs_before_stop (swallowed, but noisy) — an empty read is a clean no-op.
    k8s.read_pod_logs.return_value = ""


def _restore_points(context) -> list[dict]:
    response = context.client.get(
        f"{_BASE}/{context.agent.id}/restore-points",
        headers=_auth(context),
    )
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    return response.json()["items"]


def test_a_successful_managed_update_pins_the_agent_to_the_new_image():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        k8s = context.injector.get(KubernetesClient)
        k8s.get_pod_image.return_value = None  # no live pod to read in this mock
        k8s.get_pod_readiness.return_value = ("ready", None)
        service = context.injector.get(AgentService)

        with when("the managed update runs end to end"):
            service._run_managed_update(context.agent.id, _user_context(context))

        with then("the agent is pinned to the platform's current image and is not stale"):
            body = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            assert_that(body["status"], equal_to(AgentStatus.RUNNING.value))
            assert_that(body["update_available"], equal_to(False))
            pinned = service.repository.get_by_id(context.agent.id).pinned_runtime_image
            assert_that(pinned, equal_to(service.config.openclaw_image))


def test_a_pinned_agent_running_an_older_image_reports_update_available():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        k8s = context.injector.get(KubernetesClient)
        k8s.get_pod_image.return_value = None  # no live pod to read in this mock
        k8s.get_pod_readiness.return_value = ("ready", None)
        service = context.injector.get(AgentService)
        service._run_managed_update(context.agent.id, _user_context(context))  # pins to v2, digest current

        with when("the agent's pin is moved back to an older image"):
            agent = service.repository.get_by_id(context.agent.id)
            agent.pinned_runtime_image = "registry.example.com/agentbarn-openclaw:v1"
            service.repository.save(agent)

            body = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()

        with then("the stale pin is advertised as an available update"):
            assert_that(body["update_available"], equal_to(True))


def test_a_managed_update_captures_then_starts_on_the_new_image():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        context.injector.get(KubernetesClient).get_pod_readiness.return_value = ("ready", None)
        service = context.injector.get(AgentService)

        with when("the managed update runs end to end"):
            service._run_managed_update(context.agent.id, _user_context(context))

        with then("the agent runs again, backed by a PRE_UPGRADE restore point"):
            body = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            assert_that(body["status"], equal_to(AgentStatus.RUNNING.value))
            assert_that(body["update_available"], equal_to(False))
            assert_that(body["last_error"], none())

            points = _restore_points(context)
            assert_that(points, has_length(1))
            assert_that(points[0]["origin"], equal_to(RestorePointOrigin.PRE_UPGRADE.value))
            assert_that(points[0]["status"], equal_to(RestorePointStatus.READY.value))


def test_a_managed_update_rolls_back_when_the_new_version_never_becomes_ready():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        context.injector.get(KubernetesClient).get_pod_readiness.side_effect = [
            ("initializing", None),
            ("initializing", None),
            ("crashed", "BackOff"),
            ("ready", None),
        ]
        service = context.injector.get(AgentService)

        with when("the new version crashes and the rollback runs"):
            service._run_managed_update(context.agent.id, _user_context(context))

        with then("the agent is back, running its previous state"):
            body = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            assert_that(body["status"], equal_to(AgentStatus.RUNNING.value))
            assert_that(body["last_error"], none())

            points = _restore_points(context)
            origins = sorted(point["origin"] for point in points)
            assert_that(origins, equal_to(["PRE_UPGRADE"]))


def test_a_rollback_restarts_the_agent_on_its_previous_image():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        k8s = context.injector.get(KubernetesClient)
        k8s.get_pod_image.return_value = None  # the pre-set pin is the ground truth here
        k8s.get_pod_readiness.side_effect = [
            ("crashed", "BackOff"),  # the updated pod never comes up
            ("ready", None),  # the rolled-back pod does
        ]
        service = context.injector.get(AgentService)

        with when("the update is rolled back"):
            agent = service.repository.get_by_id(context.agent.id)
            agent.pinned_runtime_image = "registry.example.com/agentbarn-openclaw:v1"
            service.repository.save(agent)
            service._run_managed_update(context.agent.id, _user_context(context))

        with then("the agent runs again, pinned to its previous image"):
            body = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            assert_that(body["status"], equal_to(AgentStatus.RUNNING.value))
            assert_that(body["last_error"], none())
            assert_that(body["update_available"], equal_to(True))  # pin (v1) behind the platform pin (v2)

            pinned = service.repository.get_by_id(context.agent.id).pinned_runtime_image
            assert_that(pinned, equal_to("registry.example.com/agentbarn-openclaw:v1"))
            starts = k8s.create_deployment.call_args_list
            assert_that(len(starts), equal_to(2))  # failed update start + rollback start
            rolled_back = starts[1].args[1]
            assert_that(
                rolled_back.spec.template.spec.containers[0].image,
                equal_to("registry.example.com/agentbarn-openclaw:v1"),
            )


def test_a_managed_update_that_cannot_capture_leaves_the_agent_stopped():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        k8s = context.injector.get(KubernetesClient)
        k8s.get_job.return_value = _job_with({"failed": 1})
        k8s.read_job_logs.return_value = "capture failed"
        k8s.read_pod_logs.return_value = ""
        service = context.injector.get(AgentService)

        with when("the capture fails before any start"):
            service._run_managed_update(context.agent.id, _user_context(context))

        with then("the agent is stopped, and no new pod was ever built"):
            body = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            assert_that(body["status"], equal_to(AgentStatus.STOPPED.value))
            assert_that(k8s.create_deployment.called, equal_to(False))

            points = _restore_points(context)
            assert_that(points, has_length(1))
            assert_that(points[0]["status"], equal_to(RestorePointStatus.FAILED.value))


def test_a_managed_update_rolls_back_when_the_start_itself_fails():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        context.injector.get(KubernetesClient).get_pod_readiness.return_value = ("ready", None)
        service = context.injector.get(AgentService)

        real_provision = service._provision_and_start
        starts = {"count": 0}

        def flaky_provision(agent):
            starts["count"] += 1
            if starts["count"] == 1:
                raise RuntimeError("cluster rejected the new image")
            return real_provision(agent)

        with when("the first start fails and the rollback starts again"):
            with patch.object(service, "_provision_and_start", side_effect=flaky_provision):
                service._run_managed_update(context.agent.id, _user_context(context))

        with then("the agent ends up running on the rolled-back state"):
            body = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            assert_that(body["status"], equal_to(AgentStatus.RUNNING.value))
            assert_that(starts["count"], equal_to(2))


# --- The HTTP route -----------------------------------------------------------


def test_a_first_update_rolls_back_to_the_image_the_pod_actually_ran():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        k8s = context.injector.get(KubernetesClient)
        # The pod is still on v1 even though the platform pin moved to v2 —
        # a long-running Agent that never pinned itself.
        k8s.get_pod_image.return_value = "registry.example.com/agentbarn-openclaw:v1"
        k8s.get_pod_readiness.side_effect = [
            ("crashed", "BackOff"),  # the updated pod never comes up
            ("ready", None),  # the rolled-back pod does
        ]
        service = context.injector.get(AgentService)

        with when("the first managed update runs against the moved platform pin"):
            service._run_managed_update(context.agent.id, _user_context(context))

        with then("the rollback restarts the runtime the pod was actually running"):
            pinned = service.repository.get_by_id(context.agent.id).pinned_runtime_image
            assert_that(pinned, equal_to("registry.example.com/agentbarn-openclaw:v1"))


def test_a_rollback_takes_no_extra_safety_backup():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        k8s = context.injector.get(KubernetesClient)
        k8s.get_pod_readiness.side_effect = [
            ("crashed", "BackOff"),  # the updated pod never comes up
            ("ready", None),  # the rolled-back pod does
        ]
        service = context.injector.get(AgentService)

        with when("the managed update is rolled back"):
            service._run_managed_update(context.agent.id, _user_context(context))

        with then("the rollback restores the pre-upgrade archive without a second safety copy"):
            origins = [point["origin"] for point in _restore_points(context)]
            assert_that(origins, not_(has_item(RestorePointOrigin.PRE_RESTORE.value)))
            assert_that(origins, has_item(RestorePointOrigin.PRE_UPGRADE.value))


def test_a_rollback_whose_restore_fails_does_not_restart_the_agent():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        k8s = context.injector.get(KubernetesClient)
        # Job reads, in order: PRE_UPGRADE capture, then the restore itself.
        _reads = []

        def _tracked_get_job(name, ns):
            # Reads, in order: PRE_UPGRADE capture, then the restore itself.
            _reads.append(name)
            i = len(_reads) - 1
            statuses = [{"succeeded": 1}, {"failed": 1}, {"failed": 1}, {"failed": 1}, {"failed": 1}]
            return _job_with(statuses[min(i, 4)])

        k8s.get_job.side_effect = _tracked_get_job
        k8s.read_job_logs.return_value = "restore failed"
        # Extraction-phase failure: the Job wiped the volume but could not put
        # the archive back, so the row must FAIL — a backup-phase failure would
        # leave the volume untouched and mark the row READY (restart is safe).
        from api.domains.agents.restore_point_job import EXIT_RESTORE_FAILED

        k8s.get_job_exit_code.return_value = EXIT_RESTORE_FAILED
        k8s.get_pod_name_for_job.return_value = "some-pod"
        k8s.get_pod_readiness.return_value = ("crashed", "BackOff")
        service = context.injector.get(AgentService)

        with when("the rollback's restore cannot complete"):
            service._run_managed_update(context.agent.id, _user_context(context))

        with then("the agent is marked failed and nothing restarts it"):
            body = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            assert_that(body["status"], equal_to(AgentStatus.ERROR.value))
            assert_that(k8s.create_deployment.call_count, equal_to(1))  # only the failed update start


def test_managed_update_is_accepted_and_runs_through_the_background_task():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        context.injector.get(KubernetesClient).get_pod_readiness.return_value = ("ready", None)

        with when("I ask for a managed update"):
            response = context.client.post(_managed_url(context), headers=_auth(context))

        with then("it is accepted, and the scheduled task has carried the update through"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            body = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            assert_that(body["status"], equal_to(AgentStatus.RUNNING.value))


def test_managed_update_on_a_stopped_agent_returns_409():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        with when("I ask for a managed update on a stopped Agent"):
            response = context.client.post(_managed_url(context), headers=_auth(context))

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(response.json()["detail"], contains_string("running"))


def test_managed_update_while_a_restore_point_is_in_flight_returns_409():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        repository = context.injector.get(RestorePointRepository)
        row = AgentRestorePoint(
            agent_id=context.agent.id,
            label="someone is restoring",
            status=RestorePointStatus.RESTORING,
            origin=RestorePointOrigin.MANUAL,
            agent_type=context.agent.agent_type,
            pvc_name=f"restore-point-{uuid.uuid4()}",
            config_manifest={},
        )
        repository.save(row)

        with when("I ask for a managed update while that runs"):
            response = context.client.post(_managed_url(context), headers=_auth(context))

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_managed_update_without_auth_returns_401():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        with when("I ask for a managed update without auth"):
            response = context.client.post(_managed_url(context))

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
