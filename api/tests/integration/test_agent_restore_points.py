import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import patch

import pytest
from fastapi import HTTPException, status
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
from kubernetes.client import V1Job, V1JobCondition, V1JobStatus
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col

from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import AgentRestorePoint, AgentStatus, RestorePointOrigin, RestorePointStatus
from api.domains.agents.repository import AgentRepository
from api.domains.agents.restore_point_job import EXIT_BACKUP_FAILED, EXIT_RESTORE_FAILED
from api.domains.agents.service import AgentService
from api.domains.events.catalog import (
    AGENT_RESTORE_POINT_CREATED,
    AGENT_RESTORE_POINT_DELETED,
    AGENT_RESTORE_POINT_RESTORED,
    AGENT_TEMPLATE_OVERRIDE_SELECTED,
    EVENT_REGISTRY,
    SECURITY_AUDIT_HANDLER,
)
from api.domains.events.dispatch import EventDeliveryDispatcher
from api.domains.events.models import ActorIdentity, ActorIdentityType, EventScope, OutboxMessage
from api.domains.restore_points.repository import RestorePointRepository
from api.domains.restore_points.service import RestorePointService
from api.domains.templates.models import AgentTemplate
from api.domains.templates.repository import TemplateRepository
from api.infrastructure.kubernetes import KubernetesClient
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    FAKE_LITELLM_KEY,
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    skill_is_assigned_to_agent,
    there_is_a_skill,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.template import there_is_a_template

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


def test_list_restore_points_reports_the_cap_and_the_manual_count():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        _seed(context)
        _seed(context, origin=RestorePointOrigin.PRE_RESTORE)
        _seed(context, status_value=RestorePointStatus.FAILED)

        with when("I list restore points"):
            response = context.client.get(_url(context), headers=_auth(context))

        with then("the count excludes what the cap excludes, unlike the page total"):
            body = response.json()
            assert_that(body["total"], equal_to(3))
            assert_that(body["cap"], equal_to(2))
            assert_that(body["manual_count"], equal_to(1))


def test_capture_records_the_template_pin_in_the_config_manifest():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        pinned = context.injector.get(TemplateRepository).get_pinned_template(context.agent)

        with when("I capture a restore point"):
            response = context.client.post(_url(context), json={}, headers=_auth(context))

        with then("the manifest names the version the Agent was pinned to"):
            manifest = response.json()["config_manifest"]
            assert_that(manifest["template_key"], equal_to(pinned.template_key))
            assert_that(manifest["template_version"], equal_to(1))
            assert_that(manifest["template_selection_type"], equal_to("organization"))
            assert_that(manifest["override_version"], none())


def test_capture_records_skill_pins_in_the_config_manifest():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.STOPPED),
            there_is_a_skill(name="Calendar"),
            skill_is_assigned_to_agent(),
        ]
    ) as context:
        with when("I capture a restore point"):
            response = context.client.post(_url(context), json={}, headers=_auth(context))

        with then("each assigned skill is recorded with the version it was pinned to"):
            skills = response.json()["config_manifest"]["skills"]
            assert_that(skills, has_length(1))
            assert_that(skills[0]["skill_id"], equal_to(str(context.skill.id)))
            assert_that(skills[0]["name"], equal_to("Calendar"))
            assert_that(skills[0]["pinned_version"], equal_to(1))


def test_config_manifest_holds_no_credentials():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        with when("I capture a restore point"):
            response = context.client.post(_url(context), json={}, headers=_auth(context))

        with then("nothing secret rides along in the display record"):
            manifest = response.json()["config_manifest"]
            serialized = json.dumps(manifest)
            assert_that(serialized, is_not(contains_string(FAKE_LITELLM_KEY)))
            assert_that(serialized, is_not(contains_string(TEST_ENCRYPTION_KEY)))


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


def _backdate(context, restore_point_id) -> None:
    engine = context.injector.get(PostgresRepositoryDelegate).engine
    with Session(engine) as session:
        session.exec(
            update(AgentRestorePoint)
            .where(col(AgentRestorePoint.id) == restore_point_id)
            .values(updated_at=datetime.now(UTC) - timedelta(hours=1))
        )
        session.commit()


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


def test_a_row_whose_job_is_not_created_yet_is_left_for_the_next_read():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        seeded = _reconcilable(context)
        context.injector.get(KubernetesClient).get_job.return_value = None

        with when("a read lands between the row being committed and its job being created"):
            body = context.client.get(f"{_url(context)}/{seeded.id}", headers=_auth(context)).json()

        with then("the row is not failed and its volume is not released"):
            assert_that(body["status"], equal_to(RestorePointStatus.PENDING.value))
            assert_that(context.injector.get(KubernetesClient).delete_pvc.called, equal_to(False))


def test_a_restoring_row_that_lost_track_of_its_job_keeps_its_archive_volume():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        target = _seed(context, status_value=RestorePointStatus.RESTORING)
        _backdate(context, target.id)
        k8s = context.injector.get(KubernetesClient)
        k8s.delete_pvc.reset_mock()

        with when("a restoring row with no job name is reconciled"):
            body = context.client.get(f"{_url(context)}/{target.id}", headers=_auth(context)).json()

        with then("it fails without deleting the archive a retry would read from"):
            assert_that(body["status"], equal_to(RestorePointStatus.FAILED.value))
            deleted = [call.args[0] for call in k8s.delete_pvc.call_args_list if call.args]
            assert_that(deleted, is_not(has_item(target.pvc_name)))


def test_the_restoring_transition_records_its_job_name_in_the_same_write():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        target = _seed(context, status_value=RestorePointStatus.READY)
        repository: RestorePointRepository = context.injector.get(RestorePointRepository)
        actor = ActorIdentity(type=ActorIdentityType.USER, id=context.user.id)
        payload = {
            "organization_id": context.organization.id,
            "agent_id": context.agent.id,
            "agent_name": context.agent.name,
            "restore_point_id": target.id,
            "origin": target.origin,
        }

        with when("the target is moved to restoring"):
            result = repository.update_status_with_event(
                target.id,
                RestorePointStatus.RESTORING,
                from_statuses=(RestorePointStatus.READY,),
                job_name="rp-res-atomic",
                event_name=AGENT_RESTORE_POINT_RESTORED,
                actor=actor,
                payload=payload,
            )

        with then("no reader can observe the row restoring without its job name"):
            assert result is not None
            assert_that(result.restore_point.status, equal_to(RestorePointStatus.RESTORING))
            assert_that(result.restore_point.job_name, equal_to("rp-res-atomic"))


def test_a_vanished_job_does_not_leave_the_row_stuck_forever():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        seeded = _reconcilable(context)
        _backdate(context, seeded.id)
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


def _restore_failed(context, *, pod=True, exit_code=None, logs=None, deadline=False):
    target = _seed(context, status_value=RestorePointStatus.READY)
    context.client.post(_restore_url(context, target.id), headers=_auth(context))
    conditions = [V1JobCondition(type="Failed", status="True", reason="DeadlineExceeded")] if deadline else None
    k8s = context.injector.get(KubernetesClient)
    k8s.get_job.return_value = V1Job(status=V1JobStatus(failed=1, conditions=conditions))
    k8s.get_pod_name_for_job.return_value = "rp-res-pod" if pod else None
    k8s.get_job_exit_code.return_value = exit_code
    k8s.read_job_logs.return_value = logs
    k8s.delete_pvc.reset_mock()
    return target, k8s


def _rows_by_origin(context) -> dict:
    items = context.client.get(_url(context), headers=_auth(context)).json()["items"]
    return {item["origin"]: item for item in items}


def test_an_unknown_restore_outcome_releases_neither_volume():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        _, k8s = _restore_failed(context, pod=False)

        with when("the job's pod is gone so the failed phase cannot be established"):
            rows = _rows_by_origin(context)

        with then("both rows fail and no volume is deleted"):
            assert_that(rows[RestorePointOrigin.MANUAL.value]["status"], equal_to(RestorePointStatus.FAILED.value))
            assert_that(rows[RestorePointOrigin.PRE_RESTORE.value]["status"], equal_to(RestorePointStatus.FAILED.value))
            assert_that(k8s.delete_pvc.called, equal_to(False))


def test_a_restore_that_hit_its_deadline_keeps_the_backup_and_names_the_timeout_setting():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        _, k8s = _restore_failed(context, pod=False, deadline=True)

        with when("the job was killed by its deadline and its pod deleted"):
            rows = _rows_by_origin(context)

        with then("the backup volume is kept and the reason points at the right setting"):
            backup = rows[RestorePointOrigin.PRE_RESTORE.value]
            assert_that(backup["status"], equal_to(RestorePointStatus.FAILED.value))
            assert_that(backup["failure_reason"], contains_string("RESTORE_POINT_RESTORE_TIMEOUT_SECONDS"))
            assert_that(k8s.delete_pvc.called, equal_to(False))


def test_a_capture_that_hit_its_deadline_names_the_capture_timeout_setting():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        seeded = _reconcilable(context)
        k8s = context.injector.get(KubernetesClient)
        k8s.get_job.return_value = V1Job(
            status=V1JobStatus(
                failed=1,
                conditions=[V1JobCondition(type="Failed", status="True", reason="DeadlineExceeded")],
            )
        )
        k8s.read_job_logs.return_value = None

        with when("the capture job was killed by its deadline"):
            body = context.client.get(f"{_url(context)}/{seeded.id}", headers=_auth(context)).json()

        with then("the reason names the capture setting rather than pointing at logs that no longer exist"):
            assert_that(body["failure_reason"], contains_string("RESTORE_POINT_CAPTURE_TIMEOUT_SECONDS"))


def test_an_unexpected_exit_after_the_safety_net_keeps_the_backup():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        _restore_failed(context, exit_code=137, logs='{"bytes": 800, "file_count": 5}\n')

        with when("the pod was killed after printing its backup manifest"):
            rows = _rows_by_origin(context)

        with then("the manifest proves the backup finished, so it is kept ready"):
            backup = rows[RestorePointOrigin.PRE_RESTORE.value]
            assert_that(backup["status"], equal_to(RestorePointStatus.READY.value))
            assert_that(backup["archive_bytes"], equal_to(800))
            assert_that(rows[RestorePointOrigin.MANUAL.value]["status"], equal_to(RestorePointStatus.FAILED.value))


def test_an_unexpected_exit_before_the_safety_net_leaves_the_target_usable():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        _, k8s = _restore_failed(context, exit_code=137, logs="")

        with when("the pod was killed before printing any manifest"):
            rows = _rows_by_origin(context)

        with then("the wipe never ran, so the target is ready again and the empty backup is released"):
            assert_that(rows[RestorePointOrigin.MANUAL.value]["status"], equal_to(RestorePointStatus.READY.value))
            assert_that(rows[RestorePointOrigin.PRE_RESTORE.value]["status"], equal_to(RestorePointStatus.FAILED.value))
            assert_that(k8s.delete_pvc.called, equal_to(True))


def test_the_failure_reason_is_the_error_even_when_stderr_is_logged_before_the_manifest():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        _restore_failed(
            context,
            exit_code=3,
            logs='restore failed: corrupt archive\n{"bytes": 800, "file_count": 5}\n',
        )

        with when("the pod log recorded the stderr line ahead of the stdout manifest"):
            rows = _rows_by_origin(context)

        with then("the reported reason is the error, not the manifest"):
            target = rows[RestorePointOrigin.MANUAL.value]
            assert_that(target["failure_reason"], equal_to("restore failed: corrupt archive"))


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
        stale = _reconcilable(context)
        _backdate(context, stale.id)
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


def _outbox(context, event_name: str) -> list[OutboxMessage]:
    messages = context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
    return [m for m in messages if m.event_name == event_name]


def test_capturing_a_restore_point_stages_an_organization_scoped_event():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        with when("I capture a restore point"):
            body = context.client.post(_url(context), json={"label": "before"}, headers=_auth(context)).json()

        with then("one organization-scoped event is staged with identifiers only"):
            messages = _outbox(context, AGENT_RESTORE_POINT_CREATED)
            assert_that(messages, has_length(1))
            message = messages[0]
            assert_that(message.event_scope, equal_to(EventScope.ORGANIZATION))
            assert_that(message.organization_id, equal_to(context.organization.id))
            assert_that(message.payload["restore_point_id"], equal_to(body["id"]))
            assert_that(message.payload["agent_id"], equal_to(str(context.agent.id)))
            assert_that(message.payload["label"], equal_to("before"))
            assert_that(message.payload["origin"], equal_to("MANUAL"))
            assert_that("config_manifest" not in message.payload, equal_to(True))


def test_a_capture_that_cannot_be_provisioned_fails_the_row_and_releases_the_volume():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        k8s = context.injector.get(KubernetesClient)
        k8s.create_job.side_effect = RuntimeError("cluster rejected the job")

        with when("the job cannot be created"):
            response = context.client.post(_url(context), json={}, headers=_auth(context))

        with then("the row is failed and its volume is reclaimed"):
            assert_that(response.status_code, equal_to(status.HTTP_500_INTERNAL_SERVER_ERROR))
            repository: RestorePointRepository = context.injector.get(RestorePointRepository)
            rows = repository.find_non_terminal_for_agent(context.agent.id)
            assert_that(rows, equal_to([]))
            assert_that(k8s.delete_pvc.called, equal_to(True))


def test_restoring_stages_an_event_and_produces_a_security_audit_record():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        target = _seed(context, status_value=RestorePointStatus.READY)

        with when("I restore it"):
            context.client.post(_restore_url(context, target.id), headers=_auth(context))

        with then("the restore is staged and projected into the audit trail"):
            messages = _outbox(context, AGENT_RESTORE_POINT_RESTORED)
            assert_that(messages, has_length(1))
            assert_that(messages[0].payload["restore_point_id"], equal_to(str(target.id)))
            definition = EVENT_REGISTRY.get(AGENT_RESTORE_POINT_RESTORED, 1)
            assert_that(definition.handler_names, has_item(SECURITY_AUDIT_HANDLER))


def test_a_dispatch_failure_does_not_fail_the_request():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        dispatcher = context.injector.get(EventDeliveryDispatcher)
        with patch.object(dispatcher, "enqueue_immediate", side_effect=RuntimeError("broker down")):
            with when("the broker is unreachable"):
                response = context.client.post(_url(context), json={}, headers=_auth(context))

        with then("the capture is still accepted and the delivery stays staged"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(_outbox(context, AGENT_RESTORE_POINT_CREATED), has_length(1))


def test_the_automatic_pre_restore_backup_does_not_emit_its_own_created_event():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        target = _seed(context, status_value=RestorePointStatus.READY)

        with when("I restore, which creates a safety net row"):
            context.client.post(_restore_url(context, target.id), headers=_auth(context))

        with then("only the restore itself is reported, not the system-created backup"):
            assert_that(_outbox(context, AGENT_RESTORE_POINT_CREATED), equal_to([]))
            assert_that(_outbox(context, AGENT_RESTORE_POINT_RESTORED), has_length(1))


def test_only_restoring_is_projected_into_the_security_audit_trail():
    for event_name in (AGENT_RESTORE_POINT_CREATED, AGENT_RESTORE_POINT_DELETED):
        definition = EVENT_REGISTRY.get(event_name, 1)
        assert_that(definition.handler_names, is_not(has_item(SECURITY_AUDIT_HANDLER)))


def test_deleting_a_restore_point_stages_an_event():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        seeded = _seed(context, status_value=RestorePointStatus.READY)

        with when("I delete it"):
            context.client.delete(f"{_url(context)}/{seeded.id}", headers=_auth(context))

        with then("the deletion is recorded even though the row is gone"):
            messages = _outbox(context, AGENT_RESTORE_POINT_DELETED)
            assert_that(messages, has_length(1))
            assert_that(messages[0].payload["restore_point_id"], equal_to(str(seeded.id)))


def test_the_read_dto_never_exposes_internal_resource_names():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        seeded = _seed(context)

        with when("I read it"):
            body = context.client.get(f"{_url(context)}/{seeded.id}", headers=_auth(context)).json()

        with then("pvc and job names stay internal"):
            assert_that(body.get("pvc_name"), none())
            assert_that(body.get("job_name"), none())
            assert_that(body.get("id"), not_none())


def _manifest_for(context, *, template_key: str, template_version: int = 1) -> dict:
    return {
        "version": 2,
        "agent_type": context.agent.agent_type,
        "template_key": template_key,
        "template_version": template_version,
        "template_selection_type": "organization",
        "override_version": None,
        "model": "",
        "effective_model": "",
        "approval_mode": "auto",
        "verbose_mode": False,
        "skills": [],
    }


def _seed_with_manifest(context, manifest: dict):
    repository: RestorePointRepository = context.injector.get(RestorePointRepository)
    return repository.save(
        AgentRestorePoint(
            agent_id=context.agent.id,
            label="recorded",
            status=RestorePointStatus.READY,
            origin=RestorePointOrigin.MANUAL,
            agent_type=context.agent.agent_type,
            pvc_name=f"restore-point-{uuid.uuid4()}",
            config_manifest=manifest,
        )
    )


def test_a_replayable_restore_starts_the_job():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        pinned = cast(AgentTemplate, context.injector.get(TemplateRepository).get_pinned_template(context.agent))
        row = _seed_with_manifest(context, _manifest_for(context, template_key=pinned.template_key))

        with when("I restore and ask for the recorded configuration back"):
            response = context.client.post(
                f"{_url(context)}/{row.id}/restore",
                json={"reapply_configuration": True},
                headers=_auth(context),
            )

        with then("it is accepted and the Job is created"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(context.injector.get(KubernetesClient).create_job.called, equal_to(True))


def test_a_configuration_that_cannot_be_applied_refuses_before_the_job_starts():
    """The files must not be replaced to discover the configuration will not apply."""
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        row = _seed_with_manifest(context, _manifest_for(context, template_key="a-template-that-was-deleted"))
        k8s = context.injector.get(KubernetesClient)
        k8s.create_job.reset_mock()

        with when("I restore and ask for a configuration that no longer resolves"):
            response = context.client.post(
                f"{_url(context)}/{row.id}/restore",
                json={"reapply_configuration": True},
                headers=_auth(context),
            )

        with then("it is refused and nothing was started"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(k8s.create_job.called, equal_to(False))
            after = context.client.get(f"{_url(context)}/{row.id}", headers=_auth(context)).json()
            assert_that(after["status"], equal_to(RestorePointStatus.READY.value))


def test_a_v1_manifest_cannot_be_replayed_and_says_so():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        row = _seed_with_manifest(context, {"version": 1, "agent_type": context.agent.agent_type})
        k8s = context.injector.get(KubernetesClient)
        k8s.create_job.reset_mock()

        with when("I ask to replay a manifest that predates the recorded pins"):
            response = context.client.post(
                f"{_url(context)}/{row.id}/restore",
                json={"reapply_configuration": True},
                headers=_auth(context),
            )

        with then("it is refused without starting anything"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("nothing to re-apply"))
            assert_that(k8s.create_job.called, equal_to(False))


def test_restoring_without_asking_for_the_configuration_skips_the_check():
    """An unreplayable manifest must not block a plain volume restore."""
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        row = _seed_with_manifest(context, {"version": 1, "agent_type": context.agent.agent_type})

        with when("I restore the volume alone"):
            response = context.client.post(f"{_url(context)}/{row.id}/restore", json={}, headers=_auth(context))

        with then("it is accepted"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))


def test_applying_the_recorded_configuration_repins_the_agent():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        template_repository: TemplateRepository = context.injector.get(TemplateRepository)
        pinned = cast(AgentTemplate, template_repository.get_pinned_template(context.agent))
        row = _seed_with_manifest(context, _manifest_for(context, template_key=pinned.template_key))

        with when("I apply the configuration the restore point recorded"):
            response = context.client.post(f"{_url(context)}/{row.id}/configuration", headers=_auth(context))

        with then("it is applied"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            agent = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            assert_that(agent["template_key"], equal_to(pinned.template_key))


def test_applying_a_configuration_that_no_longer_resolves_is_refused():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        row = _seed_with_manifest(context, _manifest_for(context, template_key="gone"))

        with when("I apply a configuration whose template no longer exists"):
            response = context.client.post(f"{_url(context)}/{row.id}/configuration", headers=_auth(context))

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_applying_the_configuration_while_the_agent_runs_is_refused():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        pinned = cast(AgentTemplate, context.injector.get(TemplateRepository).get_pinned_template(context.agent))
        row = _seed_with_manifest(context, _manifest_for(context, template_key=pinned.template_key))

        with when("I apply the configuration on a running Agent"):
            response = context.client.post(f"{_url(context)}/{row.id}/configuration", headers=_auth(context))

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def _restoring_with_replay(context, manifest: dict, job_name="rp-res-test"):
    """A restore that has been accepted and is waiting on its Job."""
    repository: RestorePointRepository = context.injector.get(RestorePointRepository)
    row = _seed_with_manifest(context, manifest)
    row.status = RestorePointStatus.RESTORING
    row.job_name = job_name
    row.reapply_configuration = True
    return repository.save(row)


def test_the_recorded_configuration_lands_only_after_the_job_succeeds():
    """The browser is not involved: reconciliation applies it on the next read."""
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        pinned = cast(AgentTemplate, context.injector.get(TemplateRepository).get_pinned_template(context.agent))
        there_is_a_template(template_key="recorded-template", name="Recorded")(context)
        row = _restoring_with_replay(context, _manifest_for(context, template_key="recorded-template"))
        assert pinned.template_key != "recorded-template"

        k8s = context.injector.get(KubernetesClient)
        k8s.get_job.return_value = _job_with({"succeeded": 1})

        with when("someone reads the list, which is what advances the restore"):
            body = context.client.get(_url(context), headers=_auth(context)).json()

        with then("the row is ready and the recorded configuration has been written"):
            entry = next(item for item in body["items"] if item["id"] == str(row.id))
            assert_that(entry["status"], equal_to(RestorePointStatus.READY.value))
            assert_that(entry["reapply_configuration"], equal_to(False))
            assert_that(entry["configuration_error"], none())
            agent = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            assert_that(agent["template_key"], equal_to("recorded-template"))


def test_a_failed_restore_job_leaves_the_configuration_alone():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        pinned = cast(AgentTemplate, context.injector.get(TemplateRepository).get_pinned_template(context.agent))
        there_is_a_template(template_key="recorded-template", name="Recorded")(context)
        _restoring_with_replay(context, _manifest_for(context, template_key="recorded-template"))

        k8s = context.injector.get(KubernetesClient)
        k8s.get_job.return_value = _job_with({"failed": 1})
        k8s.read_job_logs.return_value = "restore failed: boom"

        with when("the Job failed and somebody reads the list"):
            context.client.get(_url(context), headers=_auth(context))

        with then("the Agent is still on the template it had"):
            agent = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            assert_that(agent["template_key"], equal_to(pinned.template_key))


def test_a_configuration_that_stops_being_applicable_is_reported_on_the_row():
    """The volume is already back, so this cannot fail the restore — it is recorded."""
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        row = _restoring_with_replay(context, _manifest_for(context, template_key="deleted-between"))

        k8s = context.injector.get(KubernetesClient)
        k8s.get_job.return_value = _job_with({"succeeded": 1})

        with when("the Job succeeded but the recorded template is gone"):
            body = context.client.get(_url(context), headers=_auth(context)).json()

        with then("the restore stands and the row says the configuration did not"):
            entry = next(item for item in body["items"] if item["id"] == str(row.id))
            assert_that(entry["status"], equal_to(RestorePointStatus.READY.value))
            assert_that(entry["reapply_configuration"], equal_to(False))
            assert_that(entry["configuration_error"], not_none())


def test_asking_to_replay_without_configuration_permission_is_refused():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.STOPPED),
        ]
    ) as context:
        pinned = cast(AgentTemplate, context.injector.get(TemplateRepository).get_pinned_template(context.agent))
        row = _seed_with_manifest(context, _manifest_for(context, template_key=pinned.template_key))
        k8s = context.injector.get(KubernetesClient)
        k8s.create_job.reset_mock()

        with when("a Member without agent.update asks for the configuration back"):
            with patch.object(
                AgentAuthorization,
                "require_action_for_visible",
                side_effect=HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"),
            ):
                response = context.client.post(
                    f"{_url(context)}/{row.id}/restore",
                    json={"reapply_configuration": True},
                    headers=_auth(context),
                )

        with then("nothing is started"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(k8s.create_job.called, equal_to(False))


def test_a_replay_interrupted_before_it_was_written_is_picked_up_later():
    """The process stopped after the restore was marked done, before the write.

    The row is terminal by then, so nothing in the non-terminal sweep would find it
    again; the stored intent is what keeps the work discoverable.
    """
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        there_is_a_template(template_key="recorded-template", name="Recorded")(context)
        repository: RestorePointRepository = context.injector.get(RestorePointRepository)
        row = _seed_with_manifest(context, _manifest_for(context, template_key="recorded-template"))
        row.status = RestorePointStatus.READY
        row.job_name = None
        row.reapply_configuration = True
        row.restored_by_user_id = context.user.id
        repository.save(row)

        with when("someone reads the list well after the restore finished"):
            context.client.get(_url(context), headers=_auth(context))

        with then("the configuration is written and the intent is cleared"):
            agent = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            assert_that(agent["template_key"], equal_to("recorded-template"))
            after = context.client.get(f"{_url(context)}/{row.id}", headers=_auth(context)).json()
            assert_that(after["reapply_configuration"], equal_to(False))


def test_two_readers_cannot_both_apply_the_same_replay():
    """A stale sweep result must not replay an already committed selection."""
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        there_is_a_template(template_key="recorded-template", name="Recorded")(context)
        repository: RestorePointRepository = context.injector.get(RestorePointRepository)
        row = _seed_with_manifest(context, _manifest_for(context, template_key="recorded-template"))
        row.status = RestorePointStatus.READY
        row.job_name = None
        row.reapply_configuration = True
        repository.save(row)

        service = context.injector.get(RestorePointService)
        before = len(_outbox(context, AGENT_TEMPLATE_OVERRIDE_SELECTED))
        with when("two readers act on the same stale sweep result"):
            service._apply_recorded_configuration_after_restore(row)
            service._apply_recorded_configuration_after_restore(row)

        with then("only one selection is committed"):
            assert_that(_outbox(context, AGENT_TEMPLATE_OVERRIDE_SELECTED), has_length(before + 1))
            assert_that(repository.find_owing_replay_for_agent(context.agent.id), equal_to([]))


def test_a_replay_waits_while_the_agent_is_running():
    """The lock is what keeps a deferred write out of a lifecycle operation."""
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        there_is_a_template(template_key="recorded-template", name="Recorded")(context)
        repository: RestorePointRepository = context.injector.get(RestorePointRepository)
        row = _seed_with_manifest(context, _manifest_for(context, template_key="recorded-template"))
        row.status = RestorePointStatus.READY
        row.job_name = None
        row.reapply_configuration = True
        repository.save(row)
        before = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()

        with when("the list is read while the Agent runs"):
            context.client.get(_url(context), headers=_auth(context))

        with then("the configuration is left for later rather than written underneath it"):
            after = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            assert_that(after["template_key"], equal_to(before["template_key"]))
            still = context.client.get(f"{_url(context)}/{row.id}", headers=_auth(context)).json()
            assert_that(still["reapply_configuration"], equal_to(True))


def test_the_replay_is_attributed_to_whoever_asked_for_the_restore():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        pinned = cast(AgentTemplate, context.injector.get(TemplateRepository).get_pinned_template(context.agent))
        row = _seed_with_manifest(context, _manifest_for(context, template_key=pinned.template_key))

        with when("I ask for the restore with the configuration"):
            context.client.post(
                f"{_url(context)}/{row.id}/restore",
                json={"reapply_configuration": True},
                headers=_auth(context),
            )

        with then("the restoring Member is recorded, not the one who captured it"):
            delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
            with Session(delegate.engine) as session:
                stored = session.get(AgentRestorePoint, row.id)
                assert stored is not None
                assert_that(stored.restored_by_user_id, equal_to(context.user.id))
                assert_that(stored.restored_by_display, not_none())

        with when("the Job completes and the recorded configuration is applied"):
            context.injector.get(KubernetesClient).get_job.return_value = _job_with({"succeeded": 1})
            context.client.get(_url(context), headers=_auth(context))

        with then("the selection event identifies the restorer even without a capture author"):
            event = _outbox(context, AGENT_TEMPLATE_OVERRIDE_SELECTED)[-1]
            assert_that(event.actor["type"], equal_to(ActorIdentityType.USER.value))
            assert_that(event.actor["id"], equal_to(str(context.user.id)))
            assert_that(event.payload["actor_display"], equal_to(context.user.full_name or context.user.email))


def test_replay_completion_rolls_back_with_an_interrupted_configuration_transaction():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        there_is_a_template(template_key="recorded-template", name="Recorded")(context)
        repository = context.injector.get(RestorePointRepository)
        service = context.injector.get(RestorePointService)
        row = _seed_with_manifest(context, _manifest_for(context, template_key="recorded-template"))
        row.reapply_configuration = True
        repository.save(row)
        agent_repository = context.injector.get(AgentRepository)
        before = agent_repository.get_by_id(context.agent.id)
        assert before is not None
        events_before = len(_outbox(context, AGENT_TEMPLATE_OVERRIDE_SELECTED))
        with when("the process is interrupted while staging the replay audit event"):
            with (
                patch.object(service.override_repository.outbox_repository, "stage", side_effect=KeyboardInterrupt),
                pytest.raises(KeyboardInterrupt),
            ):
                service._apply_recorded_configuration_after_restore(row)

        with then("both configuration and completion roll back, leaving retryable work"):
            after = agent_repository.get_by_id(context.agent.id)
            assert after is not None
            assert_that(after.agent_template_id, equal_to(before.agent_template_id))
            assert_that(after.updated_at, equal_to(before.updated_at))
            assert_that(repository.find_owing_replay_for_agent(context.agent.id), has_length(1))
            assert_that(_outbox(context, AGENT_TEMPLATE_OVERRIDE_SELECTED), has_length(events_before))
            service.reconcile_agent(context.agent.id)
            assert_that(repository.find_owing_replay_for_agent(context.agent.id), equal_to([]))
            assert_that(_outbox(context, AGENT_TEMPLATE_OVERRIDE_SELECTED), has_length(events_before + 1))


def test_restore_provisioning_failure_cancels_configuration_replay():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        there_is_a_template(template_key="recorded-template", name="Recorded")(context)
        row = _seed_with_manifest(context, _manifest_for(context, template_key="recorded-template"))
        k8s = context.injector.get(KubernetesClient)
        k8s.create_job.side_effect = RuntimeError("cluster rejected the job")
        before = len(_outbox(context, AGENT_TEMPLATE_OVERRIDE_SELECTED))

        with when("provisioning fails and someone reads the list afterwards"):
            response = context.client.post(
                f"{_url(context)}/{row.id}/restore", json={"reapply_configuration": True}, headers=_auth(context)
            )
            body = context.client.get(_url(context), headers=_auth(context)).json()

        with then("the archive remains ready but its configuration is never replayed"):
            assert_that(response.status_code, equal_to(status.HTTP_500_INTERNAL_SERVER_ERROR))
            entry = next(item for item in body["items"] if item["id"] == str(row.id))
            assert_that(entry["status"], equal_to("READY"))
            assert_that(entry["reapply_configuration"], equal_to(False))
            assert_that(_outbox(context, AGENT_TEMPLATE_OVERRIDE_SELECTED), has_length(before))


def test_start_reconciles_replay_before_loading_the_configuration_to_run():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        there_is_a_template(template_key="recorded-template", name="Recorded")(context)
        _restoring_with_replay(context, _manifest_for(context, template_key="recorded-template"))
        context.injector.get(KubernetesClient).get_job.return_value = _job_with({"succeeded": 1})
        service = context.injector.get(AgentService)

        with when("start is the first request after the Job succeeds"):
            with patch.object(service, "_start_agent_unchecked", side_effect=lambda agent, actor: agent) as start:
                response = context.client.post(
                    f"{_BASE}/{context.agent.id}/start".replace("{organization_id}", str(context.organization.id)),
                    headers=_auth(context),
                )

        with then("start receives the replayed configuration"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            start.assert_called_once()
            template = context.injector.get(TemplateRepository).get_pinned_template(start.call_args.args[0])
            assert template is not None
            assert_that(template.template_key, equal_to("recorded-template"))


def test_pending_replay_blocks_lifecycle_operations_while_the_lock_is_held():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        there_is_a_template(template_key="recorded-template", name="Recorded")(context)
        _restoring_with_replay(context, _manifest_for(context, template_key="recorded-template"))
        context.injector.get(KubernetesClient).get_job.return_value = _job_with({"succeeded": 1})
        service = context.injector.get(RestorePointService)

        with when("the Job finishes while a lifecycle caller already holds the lock"):
            with context.injector.get(AgentRepository).lifecycle_lock(context.agent.id) as acquired:
                assert acquired
                blocked = service.has_blocking_operation(context.agent.id)

        with then("READY with outstanding replay still blocks the caller"):
            assert_that(blocked, equal_to(True))
            service.reconcile_agent(context.agent.id)
            assert_that(service.has_blocking_operation(context.agent.id), equal_to(False))
