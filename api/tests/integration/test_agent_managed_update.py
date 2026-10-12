import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi import status
from hamcrest import assert_that, contains_string, equal_to, has_item, has_length, none, not_
from kubernetes.client.exceptions import ApiException

from api.core.config import Config
from api.domains.agents.models import (
    MANAGED_UPDATE_STALE_SECONDS,
    AgentRestorePoint,
    AgentStatus,
    ManagedUpdateOutcome,
    RestorePointOrigin,
    RestorePointStatus,
)
from api.domains.agents.repository import AgentRepository
from api.domains.agents.restore_point_job import EXIT_RESTORE_FAILED
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
    there_is_an_organization,
    there_is_an_organization_with_user_and_access_token,
)

_BASE = "/api/v1/organizations/{organization_id}/agents"
_OLD_IMAGE = "registry.example.com/agentbarn-openclaw:v1"
_NEW_IMAGE = "registry.example.com/agentbarn-openclaw:v2"

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
            "OPENCLAW_IMAGE": _NEW_IMAGE,
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

# What get_pod_readiness reports for a pod that crashed and is backing off. With
# the restart count at 2 (see _new_version_crash_loops) the update gives up on it.
_CRASH_LOOP = ("crashed", "CrashLoopBackOff")
_READY = ("ready", None)


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _managed_url(context) -> str:
    return f"{_BASE}/{context.agent.id}/managed-update"


def _agent_url(context) -> str:
    return f"{_BASE}/{context.agent.id}"


def _read_agent(context) -> dict:
    return context.client.get(_agent_url(context), headers=_auth(context)).json()


def _stored_agent(context):
    return context.injector.get(AgentRepository).get_by_id(context.agent.id)


def _k8s(context):
    return context.injector.get(KubernetesClient)


def _new_version_crash_loops(context) -> None:
    _k8s(context).get_pod_restart_count.return_value = 2


# --- Waiting for the new pod ---------------------------------------------------


def test_wait_for_ready_returns_true_when_the_pod_reports_ready():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        service = context.injector.get(AgentService)
        _k8s(context).get_pod_readiness.return_value = _READY

        with when("the newest pod is ready"):
            healthy = service._wait_for_ready(context.agent.id, 10, poll_seconds=0)

        with then("the update may proceed, after a single read"):
            assert_that(healthy, equal_to(True))
            assert_that(_k8s(context).get_pod_readiness.call_count, equal_to(1))


def test_wait_for_ready_gives_up_at_once_on_a_pod_that_has_crashed_twice():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        service = context.injector.get(AgentService)
        _k8s(context).get_pod_readiness.return_value = _CRASH_LOOP
        _new_version_crash_loops(context)

        with when("the new pod is crash-looping"):
            healthy = service._wait_for_ready(context.agent.id, 60, poll_seconds=0)

        with then("the wait gives up at once rather than burning the timeout"):
            assert_that(healthy, equal_to(False))
            assert_that(_k8s(context).get_pod_readiness.call_count, equal_to(1))


def test_wait_for_ready_keeps_waiting_after_a_single_crash():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        service = context.injector.get(AgentService)
        _k8s(context).get_pod_readiness.side_effect = [_CRASH_LOOP, _READY]
        _k8s(context).get_pod_restart_count.return_value = 1

        with when("the new pod crashes once, then comes up"):
            healthy = service._wait_for_ready(context.agent.id, 60, poll_seconds=0)

        with then("one crash is not treated as a failed update"):
            assert_that(healthy, equal_to(True))


def test_wait_for_ready_keeps_waiting_through_image_pull_errors():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        service = context.injector.get(AgentService)
        _k8s(context).get_pod_readiness.side_effect = [
            ("crashed", "ErrImagePull"),
            ("crashed", "ImagePullBackOff"),
            _READY,
        ]

        with when("the registry fails a pull, then the kubelet's retry succeeds"):
            healthy = service._wait_for_ready(context.agent.id, 60, poll_seconds=0)

        with then("a pull error does not roll the update back"):
            assert_that(healthy, equal_to(True))


def test_wait_for_ready_gives_up_after_the_timeout():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        service = context.injector.get(AgentService)
        _k8s(context).get_pod_readiness.return_value = ("initializing", None)

        with when("the pod stays initializing past the timeout"):
            healthy = service._wait_for_ready(context.agent.id, 1, poll_seconds=0)

        with then("the wait reports the update as unhealthy"):
            assert_that(healthy, equal_to(False))
            assert_that(_k8s(context).get_pod_readiness.call_count > 1, equal_to(True))


def test_teardown_workload_deletes_only_the_deployment():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        service = context.injector.get(AgentService)
        k8s = _k8s(context)
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
    k8s = _k8s(context)
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


def _pin(context, image: str) -> None:
    repository = context.injector.get(AgentRepository)
    agent = repository.get_by_id(context.agent.id)
    agent.pinned_runtime_image = image
    repository.save(agent)


def _run(context) -> None:
    """Run the orchestration the way the route does: claimed first."""
    context.injector.get(AgentRepository).claim_managed_update(context.agent.id)
    context.injector.get(AgentService)._run_managed_update(context.agent.id, _user_context(context))


def test_a_successful_managed_update_leaves_the_agent_following_the_platform():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        _k8s(context).get_pod_readiness.return_value = _READY

        with when("the managed update runs end to end"):
            _run(context)

        with then("the agent runs the platform image with no pin of its own, backed by a PRE_UPGRADE point"):
            body = _read_agent(context)
            assert_that(body["status"], equal_to(AgentStatus.RUNNING.value))
            assert_that(body["update_available"], equal_to(False))
            assert_that(body["update_in_progress"], equal_to(False))
            assert_that(body["last_error"], none())
            assert_that(_stored_agent(context).pinned_runtime_image, equal_to(""))

            points = _restore_points(context)
            assert_that(points, has_length(1))
            assert_that(points[0]["origin"], equal_to(RestorePointOrigin.PRE_UPGRADE.value))
            assert_that(points[0]["status"], equal_to(RestorePointStatus.READY.value))
            assert_that(body["last_managed_update"]["outcome"], equal_to(ManagedUpdateOutcome.SUCCEEDED.value))
            assert_that(body["last_managed_update"]["restore_point_id"], equal_to(points[0]["id"]))


def test_a_successful_update_clears_the_pin_a_rollback_left():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        _pin(context, _OLD_IMAGE)
        _k8s(context).get_pod_readiness.return_value = _READY

        with when("an Agent pinned back by an earlier rollback updates successfully"):
            _run(context)

        with then("it follows the platform again, and the new pod runs the platform image"):
            assert_that(_stored_agent(context).pinned_runtime_image, equal_to(""))
            started = _k8s(context).create_deployment.call_args.args[1]
            assert_that(started.spec.template.spec.containers[0].image, equal_to(_NEW_IMAGE))


def test_an_agent_started_on_a_pin_behind_the_platform_reports_update_available():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        _pin(context, _OLD_IMAGE)

        with when("the pinned Agent starts"):
            response = context.client.post(f"{_agent_url(context)}/start", headers=_auth(context))

        with then("the pod it started is behind the platform, so an update is offered"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["update_available"], equal_to(True))


def test_a_managed_update_rolls_back_when_the_new_version_never_becomes_ready():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        _k8s(context).get_pod_readiness.side_effect = [("initializing", None), _CRASH_LOOP, _READY]
        _new_version_crash_loops(context)

        with when("the new version crashes and the rollback runs"):
            _run(context)

        with then("the agent is back, running its previous state, and says it was rolled back"):
            body = _read_agent(context)
            assert_that(body["status"], equal_to(AgentStatus.RUNNING.value))
            assert_that(body["last_error"], none())
            assert_that(body["last_managed_update"]["outcome"], equal_to(ManagedUpdateOutcome.ROLLED_BACK.value))

            origins = sorted(point["origin"] for point in _restore_points(context))
            assert_that(origins, equal_to(["PRE_UPGRADE"]))


def test_a_rollback_restarts_the_agent_on_its_previous_image_and_offers_the_update_again():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        k8s = _k8s(context)
        k8s.get_pod_image.return_value = _OLD_IMAGE
        k8s.get_pod_readiness.side_effect = [_CRASH_LOOP, _READY]
        _new_version_crash_loops(context)

        with when("the update is rolled back"):
            _run(context)

        with then("the agent runs again, pinned to its previous image, with the update still offered"):
            body = _read_agent(context)
            assert_that(body["status"], equal_to(AgentStatus.RUNNING.value))
            assert_that(body["update_available"], equal_to(True))
            assert_that(_stored_agent(context).pinned_runtime_image, equal_to(_OLD_IMAGE))

            starts = k8s.create_deployment.call_args_list
            assert_that(len(starts), equal_to(2))  # failed update start + rollback start
            assert_that(starts[0].args[1].spec.template.spec.containers[0].image, equal_to(_NEW_IMAGE))
            assert_that(starts[1].args[1].spec.template.spec.containers[0].image, equal_to(_OLD_IMAGE))


def test_a_rollback_with_no_pod_image_to_read_falls_back_to_the_effective_image():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        _pin(context, _OLD_IMAGE)
        _k8s(context).get_pod_readiness.side_effect = [_CRASH_LOOP, _READY]
        _new_version_crash_loops(context)

        with when("the update is rolled back and the old pod could not be read"):
            _run(context)

        with then("the pin the Agent started on is the previous image"):
            assert_that(_stored_agent(context).pinned_runtime_image, equal_to(_OLD_IMAGE))


def test_a_managed_update_that_cannot_capture_leaves_the_agent_stopped_and_unchanged():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        k8s = _k8s(context)
        k8s.get_job.return_value = _job_with({"failed": 1})
        k8s.read_job_logs.return_value = "capture failed: disk full"
        k8s.read_pod_logs.return_value = ""
        _pin(context, _OLD_IMAGE)

        with when("the capture fails before any start"):
            _run(context)

        with then("the agent is stopped, its pin untouched, and the reason recorded"):
            body = _read_agent(context)
            assert_that(body["status"], equal_to(AgentStatus.STOPPED.value))
            assert_that(k8s.create_deployment.called, equal_to(False))
            assert_that(_stored_agent(context).pinned_runtime_image, equal_to(_OLD_IMAGE))

            points = _restore_points(context)
            assert_that(points, has_length(1))
            assert_that(points[0]["status"], equal_to(RestorePointStatus.FAILED.value))
            outcome = body["last_managed_update"]
            assert_that(outcome["outcome"], equal_to(ManagedUpdateOutcome.BACKUP_FAILED.value))
            assert_that(outcome["restore_point_id"], equal_to(points[0]["id"]))
            assert_that(outcome["failure_reason"], contains_string("disk full"))


def test_a_pod_slow_to_shut_down_is_waited_for_before_the_capture():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        k8s = _k8s(context)
        k8s.get_pod_readiness.return_value = _READY
        # Longer than capture's own wait would tolerate, shorter than the update's.
        k8s.has_pods_for_deployment.side_effect = [True, True, True, False, False, False]

        with when("the old pod lingers through its grace period"):
            with patch("api.domains.agents.service.RESTORE_POINT_POD_TERMINATION_POLL_SECONDS", 0):
                _run(context)

        with then("the update waits it out instead of failing the capture"):
            assert_that(_read_agent(context)["last_managed_update"]["outcome"], equal_to("SUCCEEDED"))


def test_a_pod_that_never_shuts_down_ends_the_update_with_a_reason():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _k8s(context).read_pod_logs.return_value = ""
        _k8s(context).has_pods_for_deployment.return_value = True

        with when("the old pod never lets go of the volume"):
            with (
                patch("api.domains.agents.service.MANAGED_UPDATE_VOLUME_RELEASE_TIMEOUT_SECONDS", 0),
                patch("api.domains.agents.service.RESTORE_POINT_POD_TERMINATION_POLL_SECONDS", 0),
            ):
                _run(context)

        with then("the agent is stopped with no backup row, and the reason says why"):
            body = _read_agent(context)
            assert_that(body["status"], equal_to(AgentStatus.STOPPED.value))
            assert_that(_restore_points(context), has_length(0))
            outcome = body["last_managed_update"]
            assert_that(outcome["outcome"], equal_to(ManagedUpdateOutcome.BACKUP_FAILED.value))
            assert_that(outcome["restore_point_id"], none())
            assert_that(outcome["failure_reason"], contains_string("still shutting down"))


def test_a_capture_refused_by_the_cap_ends_the_update_with_a_reason():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _k8s(context).read_pod_logs.return_value = ""
        repository = context.injector.get(RestorePointRepository)
        for _ in range(2):  # RESTORE_POINT_MAX_PER_AGENT
            repository.save(
                AgentRestorePoint(
                    agent_id=context.agent.id,
                    status=RestorePointStatus.READY,
                    origin=RestorePointOrigin.MANUAL,
                    agent_type=context.agent.agent_type,
                    pvc_name=f"restore-point-{uuid.uuid4()}",
                    config_manifest={},
                )
            )

        with when("the update's capture is refused before its row exists"):
            _run(context)

        with then("the reason is recorded on the Agent"):
            outcome = _read_agent(context)["last_managed_update"]
            assert_that(outcome["outcome"], equal_to(ManagedUpdateOutcome.BACKUP_FAILED.value))
            assert_that(outcome["failure_reason"], contains_string("limit"))


def test_a_managed_update_rolls_back_when_the_start_itself_fails():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        _k8s(context).get_pod_readiness.return_value = _READY
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
                _run(context)

        with then("the agent ends up running on the rolled-back state"):
            body = _read_agent(context)
            assert_that(body["status"], equal_to(AgentStatus.RUNNING.value))
            assert_that(body["last_managed_update"]["outcome"], equal_to(ManagedUpdateOutcome.ROLLED_BACK.value))
            assert_that(starts["count"], equal_to(2))


def test_a_cluster_error_while_watching_the_new_pod_rolls_back():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        _k8s(context).get_pod_readiness.side_effect = [ApiException(status=503), _READY]

        with when("the apiserver fails mid-watch"):
            _run(context)

        with then("the update is not left half-done: it rolls back"):
            body = _read_agent(context)
            assert_that(body["status"], equal_to(AgentStatus.RUNNING.value))
            assert_that(body["last_managed_update"]["outcome"], equal_to(ManagedUpdateOutcome.ROLLED_BACK.value))


def test_a_cluster_error_inside_the_rollback_leaves_the_agent_in_error():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        k8s = _k8s(context)
        k8s.get_pod_image.return_value = _OLD_IMAGE
        k8s.get_pod_readiness.return_value = _CRASH_LOOP
        _new_version_crash_loops(context)
        deletes = []

        def delete_deployment(name, namespace):
            # The update's own stop goes through; every delete after it fails.
            deletes.append(name)
            if len(deletes) > 1:
                raise ApiException(status=500)

        k8s.delete_deployment.side_effect = delete_deployment

        with when("the rollback cannot free the volume"):
            _run(context)

        with then("the agent is in ERROR, pinned back, pointing at its intact backup"):
            body = _read_agent(context)
            assert_that(body["status"], equal_to(AgentStatus.ERROR.value))
            assert_that(body["update_in_progress"], equal_to(False))
            assert_that(_stored_agent(context).pinned_runtime_image, equal_to(_OLD_IMAGE))
            backup = _restore_points(context)[0]
            assert_that(backup["status"], equal_to(RestorePointStatus.READY.value))
            outcome = body["last_managed_update"]
            assert_that(outcome["outcome"], equal_to(ManagedUpdateOutcome.ROLLBACK_FAILED.value))
            assert_that(outcome["restore_point_id"], equal_to(backup["id"]))


def test_a_first_update_rolls_back_to_the_image_the_pod_actually_ran():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        k8s = _k8s(context)
        # The pod is still on v1 even though the platform pin moved to v2 —
        # a long-running Agent that never pinned itself.
        k8s.get_pod_image.return_value = _OLD_IMAGE
        k8s.get_pod_readiness.side_effect = [_CRASH_LOOP, _READY]
        _new_version_crash_loops(context)

        with when("the first managed update runs against the moved platform pin"):
            _run(context)

        with then("the rollback restarts the runtime the pod was actually running"):
            assert_that(_stored_agent(context).pinned_runtime_image, equal_to(_OLD_IMAGE))


def test_a_rollback_takes_no_extra_safety_backup():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        _k8s(context).get_pod_readiness.side_effect = [_CRASH_LOOP, _READY]
        _new_version_crash_loops(context)

        with when("the managed update is rolled back"):
            _run(context)

        with then("the rollback restores the pre-upgrade archive without a second safety copy"):
            origins = [point["origin"] for point in _restore_points(context)]
            assert_that(origins, not_(has_item(RestorePointOrigin.PRE_RESTORE.value)))
            assert_that(origins, has_item(RestorePointOrigin.PRE_UPGRADE.value))


def _capture_succeeds_then_restore_fails(context, *, exit_code, logs):
    k8s = _k8s(context)
    jobs = iter([_job_with({"succeeded": 1})])

    def get_job(name, namespace):
        # The capture Job, then the restore Job — the real spec the service built,
        # so the reconciler can see the restore ran without a safety copy.
        captured = next(jobs, None)
        if captured is not None:
            return captured
        created = k8s.create_job.call_args.args[1]
        created.status = _job_with({"failed": 1}).status
        return created

    k8s.get_job.side_effect = get_job
    k8s.read_job_logs.return_value = logs
    k8s.read_pod_logs.return_value = ""
    k8s.get_job_exit_code.return_value = exit_code
    k8s.get_pod_name_for_job.return_value = "some-pod"
    k8s.get_pod_readiness.return_value = _CRASH_LOOP
    _new_version_crash_loops(context)


def test_a_rollback_whose_restore_fails_does_not_restart_the_agent():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _capture_succeeds_then_restore_fails(context, exit_code=EXIT_RESTORE_FAILED, logs="restore failed")
        _k8s(context).get_pod_image.return_value = _OLD_IMAGE

        with when("the rollback's restore cannot complete"):
            _run(context)

        with then("the agent is in ERROR, nothing restarts it, and the backup can still be restored"):
            body = _read_agent(context)
            assert_that(body["status"], equal_to(AgentStatus.ERROR.value))
            assert_that(_k8s(context).create_deployment.call_count, equal_to(1))  # only the failed update start
            assert_that(_stored_agent(context).pinned_runtime_image, equal_to(_OLD_IMAGE))
            backup = _restore_points(context)[0]
            assert_that(backup["status"], equal_to(RestorePointStatus.READY.value))
            assert_that(body["last_managed_update"]["outcome"], equal_to(ManagedUpdateOutcome.ROLLBACK_FAILED.value))


def test_a_rollback_restore_killed_mid_extraction_is_not_mistaken_for_success():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        # OOM-killed with nothing printed: with no safety copy, nothing proves the
        # volume was left alone.
        _capture_succeeds_then_restore_fails(context, exit_code=137, logs="")

        with when("the rollback's restore Job is killed"):
            _run(context)

        with then("the rollback fails rather than starting the Agent on a half-written volume"):
            body = _read_agent(context)
            assert_that(body["status"], equal_to(AgentStatus.ERROR.value))
            assert_that(_k8s(context).create_deployment.call_count, equal_to(1))
            assert_that(body["last_managed_update"]["outcome"], equal_to(ManagedUpdateOutcome.ROLLBACK_FAILED.value))


# --- Guards while an update runs ----------------------------------------------


def test_stopping_during_the_readiness_wait_is_refused():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        attempts = []

        def readiness(name, namespace):
            attempts.append(context.client.post(f"{_agent_url(context)}/stop", headers=_auth(context)).status_code)
            return _READY

        _k8s(context).get_pod_readiness.side_effect = readiness

        with when("someone stops the Agent while the update watches the new pod"):
            response = context.client.post(_managed_url(context), headers=_auth(context))

        with then("the stop is refused and the update finishes"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(attempts, equal_to([status.HTTP_409_CONFLICT]))
            assert_that(_read_agent(context)["status"], equal_to(AgentStatus.RUNNING.value))


def test_a_second_managed_update_during_the_first_is_refused():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        attempts = []

        def readiness(name, namespace):
            attempts.append(context.client.post(_managed_url(context), headers=_auth(context)).status_code)
            return _READY

        _k8s(context).get_pod_readiness.side_effect = readiness

        with when("the update is requested again while it runs"):
            context.client.post(_managed_url(context), headers=_auth(context))

        with then("the second request is refused"):
            assert_that(attempts, equal_to([status.HTTP_409_CONFLICT]))


def test_deleting_the_update_backup_during_the_readiness_wait_is_refused():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        attempts = []

        def readiness(name, namespace):
            backup = _restore_points(context)[0]
            url = f"{_BASE}/{context.agent.id}/restore-points/{backup['id']}"
            attempts.append(context.client.delete(url, headers=_auth(context)).status_code)
            return _READY

        _k8s(context).get_pod_readiness.side_effect = readiness

        with when("someone deletes the update's own backup while it runs"):
            context.client.post(_managed_url(context), headers=_auth(context))

        with then("the delete is refused, so a rollback would still have it"):
            assert_that(attempts, equal_to([status.HTTP_409_CONFLICT]))
            assert_that(_restore_points(context), has_length(1))


def _claimed(context, *, age_seconds: int = 0) -> None:
    repository = context.injector.get(AgentRepository)
    agent = repository.get_by_id(context.agent.id)
    agent.managed_update_heartbeat_at = datetime.now(UTC) - timedelta(seconds=age_seconds)
    repository.save(agent)


def test_lifecycle_and_restore_point_actions_are_refused_while_an_update_runs():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        _claimed(context)
        restore_points = f"{_BASE}/{context.agent.id}/restore-points"

        with when("lifecycle and restore point actions arrive mid-update"):
            responses = {
                "start": context.client.post(f"{_agent_url(context)}/start", headers=_auth(context)),
                "capture": context.client.post(restore_points, json={}, headers=_auth(context)),
                "delete": context.client.delete(_agent_url(context), headers=_auth(context)),
            }

        with then("each is refused, and the read says an update is in progress"):
            for name, response in responses.items():
                assert_that((name, response.status_code), equal_to((name, status.HTTP_409_CONFLICT)))
                assert_that(response.json()["detail"], contains_string("managed update"))
            assert_that(_read_agent(context)["update_in_progress"], equal_to(True))


def test_an_update_whose_process_died_no_longer_blocks_the_agent():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        _claimed(context, age_seconds=MANAGED_UPDATE_STALE_SECONDS + 1)

        with when("the Agent is started after the update's heartbeat went stale"):
            response = context.client.post(f"{_agent_url(context)}/start", headers=_auth(context))

        with then("the start goes through"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["update_in_progress"], equal_to(False))


def test_the_marker_is_released_even_when_the_update_fails_unexpectedly():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        service = context.injector.get(AgentService)

        with when("something outside every step's handling fails"):
            with patch.object(service, "_update_or_roll_back", side_effect=RuntimeError("bug")):
                _run(context)

        with then("the Agent is not left blocked"):
            assert_that(_read_agent(context)["update_in_progress"], equal_to(False))


# --- The HTTP route -----------------------------------------------------------


def test_managed_update_is_accepted_and_runs_through_the_background_task():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _succeed_capture_job(context)
        _k8s(context).get_pod_readiness.return_value = _READY

        with when("I ask for a managed update"):
            response = context.client.post(_managed_url(context), headers=_auth(context))

        with then("the 202 says it is running, and the task has carried it through and let go"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(response.json()["update_in_progress"], equal_to(True))
            body = _read_agent(context)
            assert_that(body["status"], equal_to(AgentStatus.RUNNING.value))
            assert_that(body["update_in_progress"], equal_to(False))


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


def test_managed_update_on_a_deleted_agent_returns_404():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING, deleted=True)]) as context:
        with when("I ask for a managed update on a deleted Agent"):
            response = context.client.post(_managed_url(context), headers=_auth(context))

        with then("it is not found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_managed_update_on_another_organizations_agent_returns_404():
    with given(_GIVEN) as context:
        own_organization = context.organization
        there_is_an_organization(name="Other Org")(context)
        there_is_an_agent(status=AgentStatus.RUNNING, organization_id=context.organization.id)(context)
        context.organization = own_organization

        with when("I ask for a managed update on an Agent outside my Organization"):
            response = context.client.post(_managed_url(context), headers=_auth(context))

        with then("it is not found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
