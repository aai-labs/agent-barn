"""AF-411 Task Files: stored in Postgres in chunks, limited per file and per Organization,
and readable only by people who may read the Agent's Tasks."""

import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from uuid import UUID, uuid7

import pytest
from fastapi import HTTPException, status
from hamcrest import assert_that, calling, contains_inanyorder, equal_to, has_properties, raises
from sqlmodel import Session

from api.domains.agent_tasks.file_storage import CHUNK_BYTES, TaskFileStorage
from api.domains.agent_tasks.models import AgentTaskCreate, AgentTaskFileCreate
from api.domains.agent_tasks.repository import AgentTaskRepository
from api.domains.agent_tasks.service import AgentTaskService
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


def _given(**env: str):
    return [
        set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY, **env}),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
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


def _attach(context, task, data: bytes, agent=None, filename: str = "report.csv"):
    agent = agent or context.agent
    return _service(context).attach_file(
        agent.organization_id,
        agent.id,
        task.id,
        AgentTaskFileCreate(filename=filename, content_type="text/csv"),
        data,
    )


def _status_code(call) -> int:
    with pytest.raises(HTTPException) as raised:
        call()
    return raised.value.status_code


def test_a_file_larger_than_one_chunk_reads_back_unchanged():
    with given([*_given(), there_is_an_agent(), _signed_in(OrganizationRole.ADMIN)]) as context:
        task = _task(context)
        data = bytes(range(256)) * ((2 * CHUNK_BYTES + 1000) // 256)

        with when("the Agent attaches it"):
            stored = _attach(context, task, data)

            with then("its size is recorded and the same bytes come back"):
                metadata, chunks = _service(context).read_file(
                    context.agent.id, task.id, stored.id, context.current_user_context
                )
                assert_that(
                    (metadata, b"".join(chunks)),
                    equal_to((stored, data)),
                )
                assert_that(stored, has_properties(filename="report.csv", size_bytes=len(data)))


def test_attached_files_are_listed_on_the_task():
    with given([*_given(), there_is_an_agent(), _signed_in(OrganizationRole.ADMIN)]) as context:
        task = _task(context)
        stored = _attach(context, task, b"a,b\n1,2\n")

        detail = _service(context).get_task(context.agent.id, task.id, context.current_user_context)

        assert_that(detail.files, equal_to([stored]))


def test_an_empty_file_is_rejected():
    with given([*_given(), there_is_an_agent()]) as context:
        task = _task(context)

        assert_that(_status_code(lambda: _attach(context, task, b"")), equal_to(status.HTTP_400_BAD_REQUEST))


def test_a_file_over_the_per_file_limit_is_rejected():
    with given([*_given(TASK_FILE_MAX_BYTES="10"), there_is_an_agent(), _signed_in(OrganizationRole.ADMIN)]) as context:
        task = _task(context)

        with when("the Agent attaches 11 bytes"):
            code = _status_code(lambda: _attach(context, task, b"x" * 11))

            with then("it is rejected and nothing is stored"):
                detail = _service(context).get_task(context.agent.id, task.id, context.current_user_context)
                assert_that((code, detail.files), equal_to((status.HTTP_400_BAD_REQUEST, [])))


def test_a_file_that_would_take_the_organization_over_its_limit_is_rejected():
    with given([*_given(TASK_ORGANIZATION_STORAGE_MAX_BYTES="10"), there_is_an_agent()]) as context:
        task = _task(context)
        _attach(context, task, b"x" * 6)

        assert_that(
            _status_code(lambda: _attach(context, task, b"x" * 5, filename="second.csv")),
            equal_to(status.HTTP_400_BAD_REQUEST),
        )


def test_a_file_that_exactly_fills_the_organization_limit_is_accepted():
    with given([*_given(TASK_ORGANIZATION_STORAGE_MAX_BYTES="10"), there_is_an_agent()]) as context:
        task = _task(context)
        _attach(context, task, b"x" * 6)

        stored = _attach(context, task, b"x" * 4, filename="second.csv")

        assert_that(stored.size_bytes, equal_to(4))


def test_another_organizations_files_do_not_count_towards_the_limit():
    with given(
        [*_given(TASK_ORGANIZATION_STORAGE_MAX_BYTES="10"), there_is_an_agent_in_another_org(), there_is_an_agent()]
    ) as context:
        other_task = _task(context, context.other_org_agent)
        _attach(context, other_task, b"x" * 10, agent=context.other_org_agent)
        task = _task(context)

        stored = _attach(context, task, b"x" * 10)

        assert_that(stored.size_bytes, equal_to(10))


def test_a_file_cannot_be_attached_to_another_agents_task():
    with given([*_given(), there_is_an_agent()]) as context:
        task = _task(context)
        there_is_an_agent(name="Second")(context)

        assert_that(
            _status_code(lambda: _attach(context, task, b"data", agent=context.agent)),
            equal_to(status.HTTP_404_NOT_FOUND),
        )


def test_a_member_without_access_cannot_read_a_file():
    with given([*_given(), there_is_an_agent(), _signed_in(OrganizationRole.MEMBER)]) as context:
        task = _task(context)
        stored = _attach(context, task, b"secret figures")

        assert_that(
            _status_code(
                lambda: _service(context).read_file(context.agent.id, task.id, stored.id, context.current_user_context)
            ),
            equal_to(status.HTTP_404_NOT_FOUND),
        )


def test_a_file_is_not_found_through_a_different_task():
    with given([*_given(), there_is_an_agent(), _signed_in(OrganizationRole.ADMIN)]) as context:
        task = _task(context)
        other_task = _task(context)
        stored = _attach(context, task, b"data")

        assert_that(
            _status_code(
                lambda: _service(context).read_file(
                    context.agent.id, other_task.id, stored.id, context.current_user_context
                )
            ),
            equal_to(status.HTTP_404_NOT_FOUND),
        )


@pytest.mark.parametrize("filename", ["../secrets.txt", "dir\\file.txt", "line\nbreak.txt"])
def test_a_filename_with_a_path_or_control_character_is_rejected(filename: str):
    assert_that(
        calling(AgentTaskFileCreate).with_args(filename=filename, content_type="text/plain"),
        raises(ValueError),
    )


@dataclass
class _SlowStorage:
    """Holds each write open long enough for a second upload to overlap it."""

    inner: TaskFileStorage

    def write(self, session: Session, file_id: UUID, data: bytes) -> None:
        time.sleep(0.5)
        self.inner.write(session, file_id, data)

    def read(self, file_id: UUID) -> Iterator[bytes]:
        return self.inner.read(file_id)


def test_two_uploads_at_once_cannot_together_exceed_the_organization_limit():
    with given([*_given(TASK_ORGANIZATION_STORAGE_MAX_BYTES="10"), there_is_an_agent()]) as context:
        task = _task(context)
        repository = context.injector.get(AgentTaskRepository)
        repository.file_storage = _SlowStorage(repository.file_storage)

        def upload(name: str) -> int:
            try:
                _attach(context, task, b"x" * 6, filename=name)
                return status.HTTP_201_CREATED
            except HTTPException as error:
                return error.status_code

        with when("two 6-byte files are attached at the same time"):
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(upload, ["a.csv", "b.csv"]))

            with then("only one fits"):
                assert_that(outcomes, contains_inanyorder(status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST))
