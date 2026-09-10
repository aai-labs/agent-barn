import uuid

from fastapi import status
from hamcrest import (
    assert_that,
    calling,
    contains_string,
    equal_to,
    has_item,
    has_length,
    is_not,
    none,
    not_none,
    raises,
)
from kubernetes.client import V1Job, V1JobStatus
from sqlalchemy.exc import IntegrityError

from api.domains.agents.models import AgentRestorePoint, AgentStatus, RestorePointOrigin, RestorePointStatus
from api.domains.agents.restore_point_job import EXIT_BACKUP_FAILED, EXIT_RESTORE_FAILED
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
            "RESTORE_POINT_MAX_PER_AGENT": "2",
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


def _url(context) -> str:
    return f"{_BASE}/{context.agent.id}/restore-points"


def _seed(context, *, status_value=RestorePointStatus.READY, origin=RestorePointOrigin.MANUAL, label=None):
    repository: RestorePointRepository = context.injector.get(RestorePointRepository)
    return repository.save(
        AgentRestorePoint(
            agent_id=context.agent.id,
            label=label,
            status=status_value,
            origin=origin,
            agent_type=context.agent.agent_type,
            pvc_name=f"restore-point-{uuid.uuid4()}",
            config_manifest={},
        )
    )


def test_create_restore_point_without_auth_returns_401():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        with when("I capture without auth"):
            response = context.client.post(_url(context), json={})

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_create_restore_point_on_a_stopped_agent_returns_202_pending():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        with when("I capture a restore point"):
            response = context.client.post(_url(context), json={"label": "before change"}, headers=_auth(context))

        with then("it is accepted and starts pending"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            body = response.json()
            assert_that(body["status"], equal_to(RestorePointStatus.PENDING.value))
            assert_that(body["origin"], equal_to(RestorePointOrigin.MANUAL.value))
            assert_that(body["label"], equal_to("before change"))
            assert_that(body["captured_at"], none())


def test_create_restore_point_provisions_a_volume_and_a_job():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        with when("I capture a restore point"):
            context.client.post(_url(context), json={}, headers=_auth(context))

        with then("a destination volume and a capture job are created"):
            k8s = context.injector.get(KubernetesClient)
            assert_that(k8s.create_pvc.called, equal_to(True))
            assert_that(k8s.create_job.called, equal_to(True))


def test_create_restore_point_on_a_running_agent_returns_409():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        with when("I capture while the agent runs"):
            response = context.client.post(_url(context), json={}, headers=_auth(context))

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_create_restore_point_on_a_never_started_agent_returns_409():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        context.injector.get(KubernetesClient).get_pvc.return_value = None

        with when("I capture an agent that has never run"):
            response = context.client.post(_url(context), json={}, headers=_auth(context))

        with then("it is refused with a distinct message"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(response.json()["detail"], contains_string("never run"))


def test_create_restore_point_while_one_is_in_flight_returns_409():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        _seed(context, status_value=RestorePointStatus.CAPTURING)

        with when("I capture again"):
            response = context.client.post(_url(context), json={}, headers=_auth(context))

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_create_restore_point_at_the_cap_returns_409_naming_the_count():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        _seed(context)
        _seed(context)

        with when("I capture beyond the cap"):
            response = context.client.post(_url(context), json={}, headers=_auth(context))

        with then("the message names the cap and the count"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(response.json()["detail"], contains_string("2 of 2"))


def test_pre_restore_rows_do_not_count_against_the_cap():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        _seed(context, origin=RestorePointOrigin.PRE_RESTORE)
        _seed(context, origin=RestorePointOrigin.PRE_RESTORE)

        with when("I capture with only system-created rows present"):
            response = context.client.post(_url(context), json={}, headers=_auth(context))

        with then("it is accepted"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))


def test_list_restore_points_returns_newest_first():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        _seed(context, label="older")
        newer = _seed(context, label="newer")

        with when("I list restore points"):
            response = context.client.get(_url(context), headers=_auth(context))

        with then("the newest is first"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["items"], has_length(2))
            assert_that(body["items"][0]["id"], equal_to(str(newer.id)))


def test_list_restore_points_for_an_unknown_agent_returns_404():
    with given(_GIVEN) as context:
        with when("I list for an unknown agent"):
            response = context.client.get(f"{_BASE}/{uuid.uuid4()}/restore-points", headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_get_restore_point_returns_the_row():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        seeded = _seed(context, label="named")

        with when("I read it"):
            response = context.client.get(f"{_url(context)}/{seeded.id}", headers=_auth(context))

        with then("it returns the restore point"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["label"], equal_to("named"))


def test_get_unknown_restore_point_returns_404():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        with when("I read an unknown restore point"):
            response = context.client.get(f"{_url(context)}/{uuid.uuid4()}", headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_a_second_active_capture_is_refused_by_the_database_not_only_the_service():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        _seed(context, status_value=RestorePointStatus.PENDING)

        with when("a second active capture row is written directly through the repository"):

            def _write_second():
                _seed(context, status_value=RestorePointStatus.CAPTURING)

        with then("the partial unique index rejects it"):
            assert_that(calling(_write_second), raises(IntegrityError))


def test_a_restoring_row_may_coexist_with_an_active_capture():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        _seed(context, status_value=RestorePointStatus.RESTORING)

        with when("a pre-restore capture is written alongside it"):
            second = _seed(context, status_value=RestorePointStatus.PENDING, origin=RestorePointOrigin.PRE_RESTORE)

        with then("the index permits it, because restore holds both rows at once"):
            assert_that(second.id, not_none())


def _job_with(status_kwargs) -> V1Job:
    return V1Job(status=V1JobStatus(**status_kwargs))


def _reconcilable(context, job_name="rp-cap-test"):
    repository: RestorePointRepository = context.injector.get(RestorePointRepository)
    row = _seed(context, status_value=RestorePointStatus.PENDING)
    row.job_name = job_name
    return repository.save(row)


def test_a_succeeded_job_moves_the_row_to_ready_with_its_manifest():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        seeded = _reconcilable(context)
        k8s = context.injector.get(KubernetesClient)
        k8s.get_job.return_value = _job_with({"succeeded": 1})
        k8s.read_job_logs.return_value = '{"bytes": 4096, "file_count": 12}\n'

        with when("I read the restore point"):
            body = context.client.get(f"{_url(context)}/{seeded.id}", headers=_auth(context)).json()

        with then("it is ready and carries the archive measurements"):
            assert_that(body["status"], equal_to(RestorePointStatus.READY.value))
            assert_that(body["archive_bytes"], equal_to(4096))
            assert_that(body["file_count"], equal_to(12))
            assert_that(body["captured_at"], not_none())


def test_an_empty_archive_is_ready_not_failed():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        seeded = _reconcilable(context)
        k8s = context.injector.get(KubernetesClient)
        k8s.get_job.return_value = _job_with({"succeeded": 1})
        k8s.read_job_logs.return_value = '{"bytes": 120, "file_count": 0}'

        with when("I read a capture whose volume held only excluded state"):
            body = context.client.get(f"{_url(context)}/{seeded.id}", headers=_auth(context)).json()

        with then("it is ready with a zero file count"):
            assert_that(body["status"], equal_to(RestorePointStatus.READY.value))
            assert_that(body["file_count"], equal_to(0))


def test_a_failed_job_moves_the_row_to_failed_with_a_bounded_reason():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        seeded = _reconcilable(context)
        k8s = context.injector.get(KubernetesClient)
        k8s.get_job.return_value = _job_with({"failed": 1})
        k8s.read_job_logs.return_value = "x" * 5000

        with when("I read the restore point"):
            body = context.client.get(f"{_url(context)}/{seeded.id}", headers=_auth(context)).json()

        with then("it is failed and the reason fits the column"):
            assert_that(body["status"], equal_to(RestorePointStatus.FAILED.value))
            assert_that(len(body["failure_reason"]), equal_to(500))


def test_a_failed_capture_releases_its_destination_volume():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        seeded = _reconcilable(context)
        k8s = context.injector.get(KubernetesClient)
        k8s.get_job.return_value = _job_with({"failed": 1})
        k8s.read_job_logs.return_value = "capture failed"
        k8s.delete_pvc.reset_mock()

        with when("the capture job failed"):
            context.client.get(f"{_url(context)}/{seeded.id}", headers=_auth(context))

        with then("the volume it was writing into is reclaimed"):
            deleted = [call.args[0] for call in k8s.delete_pvc.call_args_list if call.args]
            assert_that(deleted, has_item(seeded.pvc_name))


def test_failed_captures_do_not_consume_the_per_agent_cap():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        _seed(context, status_value=RestorePointStatus.FAILED)
        _seed(context, status_value=RestorePointStatus.FAILED)

        with when("I capture after two failures at a cap of two"):
            response = context.client.post(_url(context), json={}, headers=_auth(context))

        with then("failures do not lock the Agent out of capturing"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))


def test_a_vanished_job_does_not_leave_the_row_stuck_forever():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        seeded = _reconcilable(context)
        context.injector.get(KubernetesClient).get_job.return_value = None

        with when("the job has been ttl-reaped before anyone looked"):
            body = context.client.get(f"{_url(context)}/{seeded.id}", headers=_auth(context)).json()

        with then("the row becomes terminal instead of blocking the agent forever"):
            assert_that(body["status"], equal_to(RestorePointStatus.FAILED.value))


def test_an_active_job_moves_pending_to_capturing():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        seeded = _reconcilable(context)
        context.injector.get(KubernetesClient).get_job.return_value = _job_with({"active": 1})

        with when("I read while the job runs"):
            body = context.client.get(f"{_url(context)}/{seeded.id}", headers=_auth(context)).json()

        with then("it reports capturing"):
            assert_that(body["status"], equal_to(RestorePointStatus.CAPTURING.value))


def test_a_reconciliation_failure_never_fails_the_read():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        seeded = _reconcilable(context)
        context.injector.get(KubernetesClient).get_job.side_effect = RuntimeError("cluster unreachable")

        with when("the cluster cannot be reached"):
            response = context.client.get(f"{_url(context)}/{seeded.id}", headers=_auth(context))

        with then("the last known status is still served"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["status"], equal_to(RestorePointStatus.PENDING.value))


def _restore_url(context, restore_point_id) -> str:
    return f"{_url(context)}/{restore_point_id}/restore"


def test_restore_creates_a_pre_restore_backup_and_marks_the_target_restoring():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        target = _seed(context, status_value=RestorePointStatus.READY)

        with when("I restore it"):
            response = context.client.post(_restore_url(context, target.id), headers=_auth(context))

        with then("a safety net is created and the target is marked restoring"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(response.json()["status"], equal_to(RestorePointStatus.RESTORING.value))

            listed = context.client.get(_url(context), headers=_auth(context)).json()["items"]
            origins = [item["origin"] for item in listed]
            assert_that(origins, has_item(RestorePointOrigin.PRE_RESTORE.value))


def test_restore_runs_a_single_job_serving_both_rows():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        target = _seed(context, status_value=RestorePointStatus.READY)
        k8s = context.injector.get(KubernetesClient)
        k8s.create_job.reset_mock()

        with when("I restore it"):
            context.client.post(_restore_url(context, target.id), headers=_auth(context))

        with then("exactly one job is created"):
            assert_that(k8s.create_job.call_count, equal_to(1))


def test_restore_on_a_running_agent_returns_409():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        target = _seed(context, status_value=RestorePointStatus.READY)

        with when("I restore while the agent runs"):
            response = context.client.post(_restore_url(context, target.id), headers=_auth(context))

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_restoring_a_non_ready_restore_point_returns_409():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        target = _seed(context, status_value=RestorePointStatus.FAILED)

        with when("I restore a failed restore point"):
            response = context.client.post(_restore_url(context, target.id), headers=_auth(context))

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_restoring_an_unknown_restore_point_returns_404():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        with when("I restore an unknown restore point"):
            response = context.client.post(_restore_url(context, uuid.uuid4()), headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_a_successful_restore_returns_the_target_to_ready_without_altering_its_archive():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        target = _seed(context, status_value=RestorePointStatus.READY)
        context.client.post(_restore_url(context, target.id), headers=_auth(context))

        k8s = context.injector.get(KubernetesClient)
        k8s.get_job.return_value = _job_with({"succeeded": 1})
        k8s.read_job_logs.return_value = '{"bytes": 999, "file_count": 3}'

        with when("the job succeeds and I read the rows"):
            items = context.client.get(_url(context), headers=_auth(context)).json()["items"]

        with then("the target is ready again and the backup carries the manifest"):
            by_origin = {item["origin"]: item for item in items}
            restored = by_origin[RestorePointOrigin.MANUAL.value]
            backup = by_origin[RestorePointOrigin.PRE_RESTORE.value]
            assert_that(restored["status"], equal_to(RestorePointStatus.READY.value))
            assert_that(restored["archive_bytes"], none())
            assert_that(backup["status"], equal_to(RestorePointStatus.READY.value))
            assert_that(backup["archive_bytes"], equal_to(999))


def test_a_failed_safety_net_leaves_the_target_intact():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        target = _seed(context, status_value=RestorePointStatus.READY)
        context.client.post(_restore_url(context, target.id), headers=_auth(context))

        k8s = context.injector.get(KubernetesClient)
        k8s.get_job.return_value = _job_with({"failed": 1})
        k8s.get_job_exit_code.return_value = EXIT_BACKUP_FAILED
        k8s.read_job_logs.return_value = "pre-restore capture failed: disk full"

        with when("the safety net could not be taken"):
            items = context.client.get(_url(context), headers=_auth(context)).json()["items"]

        with then("the volume was never touched, so the target stays usable"):
            by_origin = {item["origin"]: item for item in items}
            assert_that(by_origin[RestorePointOrigin.MANUAL.value]["status"], equal_to(RestorePointStatus.READY.value))
            assert_that(
                by_origin[RestorePointOrigin.PRE_RESTORE.value]["status"], equal_to(RestorePointStatus.FAILED.value)
            )


def test_a_failed_extraction_keeps_the_safety_net_usable():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        target = _seed(context, status_value=RestorePointStatus.READY)
        context.client.post(_restore_url(context, target.id), headers=_auth(context))

        k8s = context.injector.get(KubernetesClient)
        k8s.get_job.return_value = _job_with({"failed": 1})
        k8s.get_job_exit_code.return_value = EXIT_RESTORE_FAILED
        k8s.read_job_logs.return_value = '{"bytes": 500, "file_count": 2}\nrestore failed: corrupt archive'

        with when("the extraction failed after the safety net was taken"):
            items = context.client.get(_url(context), headers=_auth(context)).json()["items"]

        with then("the safety net is ready to roll back to and the failure is reported"):
            by_origin = {item["origin"]: item for item in items}
            assert_that(
                by_origin[RestorePointOrigin.PRE_RESTORE.value]["status"], equal_to(RestorePointStatus.READY.value)
            )
            assert_that(by_origin[RestorePointOrigin.MANUAL.value]["status"], equal_to(RestorePointStatus.FAILED.value))


def test_delete_restore_point_removes_the_row_its_volume_and_its_job():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        seeded = _seed(context, status_value=RestorePointStatus.READY)
        repository: RestorePointRepository = context.injector.get(RestorePointRepository)
        seeded.job_name = "rp-cap-done"
        repository.save(seeded)
        k8s = context.injector.get(KubernetesClient)

        with when("I delete it"):
            response = context.client.delete(f"{_url(context)}/{seeded.id}", headers=_auth(context))

        with then("it returns 204 and the cluster resources go with it"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            assert_that(k8s.delete_pvc.called, equal_to(True))
            assert_that(k8s.delete_job.called, equal_to(True))
            follow_up = context.client.get(f"{_url(context)}/{seeded.id}", headers=_auth(context))
            assert_that(follow_up.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_deleting_an_in_flight_restore_point_returns_409():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        seeded = _reconcilable(context)
        context.injector.get(KubernetesClient).get_job.return_value = _job_with({"active": 1})

        with when("I delete while it is still capturing"):
            response = context.client.delete(f"{_url(context)}/{seeded.id}", headers=_auth(context))

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_start_agent_is_refused_while_a_capture_is_running():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        _reconcilable(context)
        context.injector.get(KubernetesClient).get_job.return_value = _job_with({"active": 1})

        with when("I start the agent"):
            response = context.client.post(
                f"{_BASE}/{context.agent.id}/start".replace("{organization_id}", str(context.organization.id)),
                headers=_auth(context),
            )

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_start_agent_is_allowed_once_a_stale_job_has_been_reconciled():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        _reconcilable(context)
        context.injector.get(KubernetesClient).get_job.return_value = None

        with when("I start the agent after the job was ttl-reaped"):
            response = context.client.post(
                f"{_BASE}/{context.agent.id}/start".replace("{organization_id}", str(context.organization.id)),
                headers=_auth(context),
            )

        with then("the stale row does not block the agent forever"):
            assert_that(response.status_code, is_not(equal_to(status.HTTP_409_CONFLICT)))


def test_delete_agent_is_refused_while_a_capture_is_running():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        _reconcilable(context)
        context.injector.get(KubernetesClient).get_job.return_value = _job_with({"active": 1})

        with when("I delete the agent"):
            response = context.client.delete(
                f"{_BASE}/{context.agent.id}".replace("{organization_id}", str(context.organization.id)),
                headers=_auth(context),
            )

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_delete_agent_purges_restore_point_rows_and_resources_by_label():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        _seed(context, status_value=RestorePointStatus.READY)
        _seed(context, status_value=RestorePointStatus.READY)
        k8s = context.injector.get(KubernetesClient)

        with when("I delete the agent"):
            response = context.client.delete(
                f"{_BASE}/{context.agent.id}".replace("{organization_id}", str(context.organization.id)),
                headers=_auth(context),
            )

        with then("the rows are gone and cleanup looked them up by label"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            repository: RestorePointRepository = context.injector.get(RestorePointRepository)
            assert_that(repository.find_non_terminal_for_agent(context.agent.id), equal_to([]))
            selectors = [call.args[1] for call in k8s.list_pvcs.call_args_list if len(call.args) > 1]
            assert_that(selectors, has_item(f"agentbarn.io/agent-id={context.agent.id}"))


def test_the_read_dto_never_exposes_internal_resource_names():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        seeded = _seed(context)

        with when("I read it"):
            body = context.client.get(f"{_url(context)}/{seeded.id}", headers=_auth(context)).json()

        with then("pvc and job names stay internal"):
            assert_that(body.get("pvc_name"), none())
            assert_that(body.get("job_name"), none())
            assert_that(body.get("id"), not_none())
