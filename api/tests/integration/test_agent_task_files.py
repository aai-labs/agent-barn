"""AF-411 Task Files: an Agent attaches files it has already published as Artifacts, and
each attachment keeps its Artifact from expiring for as long as the Task has it."""

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

import pytest
from fastapi import HTTPException, status
from hamcrest import assert_that, equal_to, has_item, has_properties, is_not
from injector import Module, provider, singleton
from sqlalchemy import text
from sqlmodel import Session, col, select

from api.domains.agent_tasks import service as task_service
from api.domains.agent_tasks.models import AgentTaskCreate, AgentTaskFileCreate, AgentTaskStatus
from api.domains.agent_tasks.service import AgentTaskService
from api.domains.agents.models import Agent
from api.domains.artifacts.models import Artifact, ArtifactReference
from api.domains.artifacts.repository import ArtifactRepository
from api.domains.artifacts.service import ArtifactService
from api.domains.artifacts.storage import ArtifactDownload, ArtifactStorage
from api.domains.users.organization_users.models import OrganizationRole
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    there_is_an_agent_in_another_org,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization
from api.tests.steps.user import there_is_a_user


class _FakeArtifactStorage(ArtifactStorage):
    """Signs a download without a bucket behind it; Tasks never touch the bytes."""

    def put(self, artifact: Artifact, content: bytes) -> None:
        raise AssertionError("Tasks never upload bytes")

    def issue_download(self, artifact: Artifact, seconds: int) -> str:
        return f"signed-{artifact.id}"

    def download(self, artifact: Artifact, access: str) -> ArtifactDownload:
        raise AssertionError("Tasks never stream bytes")

    def delete(self, artifact: Artifact) -> None:
        raise AssertionError("Tasks never delete bytes")


class _FakeArtifactStorageModule(Module):
    @provider
    @singleton
    def provide_artifact_storage(self) -> ArtifactStorage:
        return _FakeArtifactStorage()


_GIVEN = [
    set_env_variable(
        {"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY, "ARTIFACT_S3_ENDPOINT_URL": "http://garage.invalid"}
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), _FakeArtifactStorageModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization(),
]


def _signed_in(role: OrganizationRole):
    def step(context):
        there_is_a_user(email=f"user-{uuid7()}@example.com", role=role, organization_id=context.organization.id)(
            context
        )

    return step


def _service(context) -> AgentTaskService:
    return context.injector.get(AgentTaskService)


def _task(context, agent=None):
    agent = agent or context.agent
    return _service(context).create_task(agent.organization_id, agent.id, AgentTaskCreate(title="Report"))


def _artifact(context, agent=None, *, state: str = "READY", filename: str = "report.csv") -> Artifact:
    """An Artifact the Agent has published, recorded the way the Artifacts domain records one."""
    agent = agent or context.agent
    content = f"bytes of {filename}".encode()
    row = Artifact(
        organization_id=agent.organization_id,
        agent_id=agent.id,
        filename=filename,
        content_type="text/csv",
        size=len(content),
        checksum=hashlib.sha256(content).hexdigest(),
        state=state,
        bucket=f"bucket-{agent.id}",
        object_key=f"objects/{uuid7()}",
        published_at=datetime.now(UTC) if state == "READY" else None,
        expires_at=datetime.now(UTC) + timedelta(days=30),
        source="chat",
    )
    with Session(context.postgres_delegate.engine, expire_on_commit=False) as session:
        session.add(row)
        session.commit()
    return row


def _attach(context, task, artifact: Artifact, agent=None):
    agent = agent or context.agent
    return _service(context).attach_file(
        agent.organization_id, agent.id, task.id, AgentTaskFileCreate(artifact_id=artifact.id)
    )


def _set_status(context, task, task_status: AgentTaskStatus, agent=None):
    agent = agent or context.agent
    return _service(context).update_status(agent.organization_id, agent.id, task.id, task_status)


def _pinned(context, artifact_id: UUID) -> bool:
    return any(ref.released_at is None for ref in _references(context, artifact_id))


def _expires_at(context, artifact_id: UUID) -> datetime:
    with Session(context.postgres_delegate.engine) as session:
        return session.get_one(Artifact, artifact_id).expires_at


def _references(context, artifact_id: UUID) -> list[ArtifactReference]:
    with Session(context.postgres_delegate.engine) as session:
        return list(
            session.exec(select(ArtifactReference).where(col(ArtifactReference.artifact_id) == artifact_id)).all()
        )


def _waits_for_a_row_lock(context) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with Session(context.postgres_delegate.engine) as session:
            if session.connection().execute(text("SELECT count(*) FROM pg_locks WHERE NOT granted")).scalar():
                return
        time.sleep(0.05)
    raise AssertionError("nothing waited for the row lock")


def _status_code(call) -> int:
    with pytest.raises(HTTPException) as raised:
        call()
    return raised.value.status_code


def test_an_attached_artifact_is_listed_on_the_task_with_its_name_type_and_size():
    with given([*_GIVEN, there_is_an_agent(), _signed_in(OrganizationRole.ADMIN)]) as context:
        task = _task(context)
        artifact = _artifact(context)

        stored = _attach(context, task, artifact)

        detail = _service(context).get_task(context.agent.id, task.id, context.current_user_context)
        assert_that(detail.files, equal_to([stored]))
        assert_that(
            stored,
            has_properties(
                artifact_id=artifact.id, filename="report.csv", content_type="text/csv", size_bytes=artifact.size
            ),
        )


def test_attaching_pins_the_artifact_to_that_task_file():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        task = _task(context)
        artifact = _artifact(context)

        stored = _attach(context, task, artifact)

        assert_that(
            [(ref.kind, ref.owner_id, ref.released_at) for ref in _references(context, artifact.id)],
            equal_to([("task", stored.id, None)]),
        )


def test_a_pinned_artifact_outlives_its_expiry():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        task = _task(context)
        artifact = _artifact(context)
        _attach(context, task, artifact)

        with when("the Artifact's retention has run out"):
            with Session(context.postgres_delegate.engine) as session:
                row = session.get_one(Artifact, artifact.id)
                row.expires_at = datetime.now(UTC) - timedelta(days=1)
                session.add(row)
                session.commit()
            candidates = context.injector.get(ArtifactRepository).cleanup_candidates()

            with then("cleanup leaves it alone"):
                assert_that(candidates, is_not(has_item(artifact.id)))


def test_attaching_the_same_artifact_twice_keeps_one_file_and_one_pin():
    with given([*_GIVEN, there_is_an_agent(), _signed_in(OrganizationRole.ADMIN)]) as context:
        task = _task(context)
        artifact = _artifact(context)

        first = _attach(context, task, artifact)
        second = _attach(context, task, artifact)

        detail = _service(context).get_task(context.agent.id, task.id, context.current_user_context)
        assert_that(
            (second, detail.files, len(_references(context, artifact.id))),
            equal_to((first, [first], 1)),
        )


def test_one_artifact_can_be_attached_to_two_tasks():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        artifact = _artifact(context)

        first = _attach(context, _task(context), artifact)
        second = _attach(context, _task(context), artifact)

        assert_that(
            {ref.owner_id for ref in _references(context, artifact.id)},
            equal_to({first.id, second.id}),
        )


def test_an_artifact_that_starts_deleting_during_the_attach_is_not_attached():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        task = _task(context)
        artifact = _artifact(context)

        with when("a deletion holds the Artifact while the Agent attaches it"):
            with Session(context.postgres_delegate.engine) as deleting:
                row = deleting.exec(select(Artifact).where(col(Artifact.id) == artifact.id).with_for_update()).one()
                row.state = "DELETING"
                deleting.add(row)
                deleting.flush()
                with ThreadPoolExecutor(max_workers=1) as pool:
                    attempt = pool.submit(_status_code, lambda: _attach(context, task, artifact))
                    _waits_for_a_row_lock(context)
                    deleting.commit()
                    code = attempt.result(timeout=10)

            with then("the attach sees the deletion: not found, and nothing is pinned"):
                assert_that((code, _references(context, artifact.id)), equal_to((status.HTTP_404_NOT_FOUND, [])))


def test_an_attach_that_waits_on_the_agents_deletion_is_refused():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        task = _task(context)
        artifact = _artifact(context)

        with when("the Agent's deletion holds its row while the Agent attaches a file"):
            with Session(context.postgres_delegate.engine) as deleting:
                agent = deleting.exec(select(Agent).where(col(Agent.id) == context.agent.id).with_for_update()).one()
                agent.deleted_at = datetime.now(UTC)
                deleting.add(agent)
                deleting.flush()
                with ThreadPoolExecutor(max_workers=1) as pool:
                    attempt = pool.submit(_status_code, lambda: _attach(context, task, artifact))
                    _waits_for_a_row_lock(context)
                    deleting.commit()
                    code = attempt.result(timeout=10)

            with then("the attach finds no Agent, and nothing is pinned"):
                assert_that((code, _references(context, artifact.id)), equal_to((status.HTTP_404_NOT_FOUND, [])))


def test_an_artifact_that_is_still_uploading_cannot_be_attached():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        task = _task(context)
        artifact = _artifact(context, state="UPLOADING")

        assert_that(_status_code(lambda: _attach(context, task, artifact)), equal_to(status.HTTP_404_NOT_FOUND))


def test_another_agents_artifact_cannot_be_attached():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        task = _task(context)
        owner = context.agent
        there_is_an_agent(name="Second")(context)
        artifact = _artifact(context)

        assert_that(
            _status_code(lambda: _attach(context, task, artifact, agent=owner)),
            equal_to(status.HTTP_404_NOT_FOUND),
        )


def test_another_organizations_artifact_cannot_be_attached():
    with given([*_GIVEN, there_is_an_agent_in_another_org(), there_is_an_agent()]) as context:
        task = _task(context)
        artifact = _artifact(context, context.other_org_agent)

        assert_that(_status_code(lambda: _attach(context, task, artifact)), equal_to(status.HTTP_404_NOT_FOUND))


def test_a_file_cannot_be_attached_to_another_agents_task():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        task = _task(context)
        there_is_an_agent(name="Second")(context)
        artifact = _artifact(context)

        with when("the second Agent attaches its own Artifact to the first Agent's Task"):
            code = _status_code(lambda: _attach(context, task, artifact))

            with then("the Task is not found and nothing is pinned"):
                assert_that((code, _references(context, artifact.id)), equal_to((status.HTTP_404_NOT_FOUND, [])))


def test_a_reader_gets_a_download_link_for_the_files_artifact():
    with given([*_GIVEN, there_is_an_agent(), _signed_in(OrganizationRole.ADMIN)]) as context:
        task = _task(context)
        artifact = _artifact(context)
        stored = _attach(context, task, artifact)

        link = _service(context).file_link(context.agent.id, task.id, stored.id, context.current_user_context)

        assert_that(
            (link.artifact.id, f"/{artifact.id}?" in link.url, f"signed-{artifact.id}" in link.url),
            equal_to((artifact.id, True, True)),
        )


@pytest.mark.parametrize("state", ["DELETING", "DELETED"])
def test_a_file_whose_artifact_expired_says_so(state: str):
    with given([*_GIVEN, there_is_an_agent(), _signed_in(OrganizationRole.ADMIN)]) as context:
        task = _task(context)
        artifact = _artifact(context)
        stored = _attach(context, task, artifact)
        with Session(context.postgres_delegate.engine) as session:
            row = session.get_one(Artifact, artifact.id)
            row.state = state
            session.add(row)
            session.commit()

        with pytest.raises(HTTPException) as raised:
            _service(context).file_link(context.agent.id, task.id, stored.id, context.current_user_context)

        assert_that(
            (raised.value.status_code, raised.value.detail),
            equal_to((status.HTTP_410_GONE, "This file has expired and can no longer be downloaded.")),
        )


def test_a_member_without_access_cannot_get_a_download_link():
    with given([*_GIVEN, there_is_an_agent(), _signed_in(OrganizationRole.MEMBER)]) as context:
        task = _task(context)
        stored = _attach(context, task, _artifact(context))

        assert_that(
            _status_code(
                lambda: _service(context).file_link(context.agent.id, task.id, stored.id, context.current_user_context)
            ),
            equal_to(status.HTTP_404_NOT_FOUND),
        )


def test_a_file_is_not_found_through_a_different_task():
    with given([*_GIVEN, there_is_an_agent(), _signed_in(OrganizationRole.ADMIN)]) as context:
        task = _task(context)
        other_task = _task(context)
        stored = _attach(context, task, _artifact(context))

        assert_that(
            _status_code(
                lambda: _service(context).file_link(
                    context.agent.id, other_task.id, stored.id, context.current_user_context
                )
            ),
            equal_to(status.HTTP_404_NOT_FOUND),
        )


def test_an_artifact_attached_to_a_task_cannot_be_deleted():
    with given([*_GIVEN, there_is_an_agent(), _signed_in(OrganizationRole.ADMIN)]) as context:
        artifact = _artifact(context)
        _attach(context, _task(context), artifact)

        with pytest.raises(HTTPException) as raised:
            context.injector.get(ArtifactService).delete(artifact.id, context.agent.id, context.current_user_context)

        assert_that(
            (raised.value.status_code, raised.value.detail),
            equal_to(
                (status.HTTP_409_CONFLICT, "This file is in use by a run, review or Task, so it cannot be deleted")
            ),
        )


@pytest.mark.parametrize("finished", [AgentTaskStatus.DONE, AgentTaskStatus.FAILED])
def test_finishing_a_task_lets_its_files_expire_a_full_retention_later(finished):
    with given([*_GIVEN, there_is_an_agent()]) as context:
        task = _task(context)
        artifact = _artifact(context)
        _attach(context, task, artifact)

        with when(f"the Task is marked {finished.value}"):
            _set_status(context, task, finished)

            with then("the pin is released and the file expires a full retention from now"):
                assert_that(_pinned(context, artifact.id), equal_to(False))
                assert_that(
                    _expires_at(context, artifact.id) > datetime.now(UTC) + timedelta(days=29),
                    equal_to(True),
                )


def test_a_task_still_in_progress_keeps_its_files_pinned():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        task = _task(context)
        artifact = _artifact(context)
        _attach(context, task, artifact)

        _set_status(context, task, AgentTaskStatus.IN_PROGRESS)

        assert_that(_pinned(context, artifact.id), equal_to(True))


def test_a_file_attached_to_a_finished_task_gets_the_usual_retention():
    with given([*_GIVEN, there_is_an_agent(), _signed_in(OrganizationRole.ADMIN)]) as context:
        task = _task(context)
        _set_status(context, task, AgentTaskStatus.DONE)
        artifact = _artifact(context)

        stored = _attach(context, task, artifact)

        detail = _service(context).get_task(context.agent.id, task.id, context.current_user_context)
        assert_that((detail.files, _pinned(context, artifact.id)), equal_to(([stored], False)))


def test_reopening_a_task_keeps_its_files_expiry():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        task = _task(context)
        artifact = _artifact(context)
        _attach(context, task, artifact)
        _set_status(context, task, AgentTaskStatus.DONE)

        _set_status(context, task, AgentTaskStatus.OPEN)

        assert_that(_pinned(context, artifact.id), equal_to(False))


def test_past_the_pinned_file_limit_the_agents_oldest_file_is_released(monkeypatch):
    monkeypatch.setattr(task_service, "MAX_PINNED_FILES_PER_AGENT", 2)
    with given([*_GIVEN, there_is_an_agent()]) as context:
        oldest, middle, newest = (_artifact(context, filename=f"{name}.csv") for name in ("a", "b", "c"))
        _attach(context, _task(context), oldest)
        _attach(context, _task(context), middle)

        with when("the Agent attaches one file more than the limit"):
            stored = _attach(context, _task(context), newest)

            with then("the attach succeeds and only the oldest file is released"):
                assert_that(
                    (stored.artifact_id, [_pinned(context, a.id) for a in (oldest, middle, newest)]),
                    equal_to((newest.id, [False, True, True])),
                )


def test_the_pinned_file_limit_counts_each_agent_separately(monkeypatch):
    monkeypatch.setattr(task_service, "MAX_PINNED_FILES_PER_AGENT", 1)
    with given([*_GIVEN, there_is_an_agent()]) as context:
        first = _artifact(context)
        _attach(context, _task(context), first)
        there_is_an_agent(name="Second")(context)

        _attach(context, _task(context), _artifact(context))

        assert_that(_pinned(context, first.id), equal_to(True))
