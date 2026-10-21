"""AF-411: deleting an Agent removes its Tasks, Task Notes and Task Files.

Agent deletion is a soft delete, so foreign-key cascades never fire; the deletion
transaction has to remove them itself.
"""

from uuid import uuid4

import pytest
from hamcrest import assert_that, equal_to
from sqlalchemy import func
from sqlmodel import Session, col, select

from api.domains.agent_tasks.models import (
    AgentTask,
    AgentTaskCreate,
    AgentTaskFile,
    AgentTaskFileChunk,
    AgentTaskFileCreate,
    AgentTaskNote,
    AgentTaskNoteCreate,
)
from api.domains.agent_tasks.service import AgentTaskService
from api.domains.agents.repository import AgentRepository
from api.domains.events import ActorIdentity, ActorIdentityType
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.steps.agent_memory import agent_memory_api_setup, two_agents


def _record_work(context, agent) -> None:
    service: AgentTaskService = context.injector.get(AgentTaskService)
    task = service.create_task(agent.organization_id, agent.id, AgentTaskCreate(title=f"{agent.name} work"))
    service.add_note(agent.organization_id, agent.id, task.id, AgentTaskNoteCreate(body="Started"))
    service.attach_file(
        agent.organization_id,
        agent.id,
        task.id,
        AgentTaskFileCreate(filename="out.csv", content_type="text/csv"),
        [b"a,b\n"],
    )


def _counts(context, agent) -> tuple[int, ...]:
    task_ids = select(AgentTask.id).where(col(AgentTask.agent_id) == agent.id)
    file_ids = select(AgentTaskFile.id).where(col(AgentTaskFile.task_id).in_(task_ids))
    queries = (
        select(func.count()).select_from(AgentTask).where(col(AgentTask.agent_id) == agent.id),
        select(func.count()).select_from(AgentTaskNote).where(col(AgentTaskNote.task_id).in_(task_ids)),
        select(func.count()).select_from(AgentTaskFile).where(col(AgentTaskFile.task_id).in_(task_ids)),
        select(func.count()).select_from(AgentTaskFileChunk).where(col(AgentTaskFileChunk.file_id).in_(file_ids)),
    )
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return tuple(session.scalar(query) or 0 for query in queries)


def test_deleting_an_agent_removes_its_tasks_notes_and_files():
    with given(agent_memory_api_setup(two_agents())) as context:
        _record_work(context, context.billing)

        with when("the Agent is deleted"):
            response = context.client.delete(
                f"/api/v1/organizations/{{organization_id}}/agents/{context.billing.id}",
                headers={"Authorization": f"Bearer {context.access_token}"},
            )

            with then("none of its Task records remain"):
                assert_that((response.status_code, _counts(context, context.billing)), equal_to((204, (0, 0, 0, 0))))


def test_deleting_an_agent_keeps_other_agents_tasks():
    with given(agent_memory_api_setup(two_agents())) as context:
        _record_work(context, context.billing)
        _record_work(context, context.triage)

        with when("one Agent is deleted"):
            context.client.delete(
                f"/api/v1/organizations/{{organization_id}}/agents/{context.billing.id}",
                headers={"Authorization": f"Bearer {context.access_token}"},
            )

            with then("the other Agent's Task records are untouched"):
                assert_that(_counts(context, context.triage), equal_to((1, 1, 1, 1)))


def test_a_failed_deletion_keeps_the_agents_tasks(monkeypatch):
    with given(agent_memory_api_setup(two_agents())) as context:
        _record_work(context, context.billing)
        repository: AgentRepository = context.injector.get(AgentRepository)

        def unavailable(*args, **kwargs):
            raise RuntimeError("outbox unavailable")

        with when("the deletion transaction fails after the cleanup is staged"):
            monkeypatch.setattr(repository.outbox_repository, "stage", unavailable)
            with pytest.raises(RuntimeError):
                repository.soft_delete_with_event(
                    context.billing, actor=ActorIdentity(type=ActorIdentityType.USER, id=uuid4())
                )

            with then("the Agent's Task records are still there"):
                assert_that(_counts(context, context.billing), equal_to((1, 1, 1, 1)))
