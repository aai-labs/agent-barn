from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from injector import inject, singleton
from sqlalchemy import func
from sqlmodel import Session, col, select

from api.domains.agent_tasks.models import (
    AgentTask,
    AgentTaskCreate,
    AgentTaskDetail,
    AgentTaskFile,
    AgentTaskFileRead,
    AgentTaskFilter,
    AgentTaskNote,
    AgentTaskNoteRead,
    AgentTaskRead,
    AgentTaskStatus,
)
from api.domains.agents.models import Agent
from api.domains.agents.repository import agent_scope_predicates
from api.domains.rbac.policy import AuthorizationScope
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import PaginatedItems, Pagination


def _lock_live_agent(session: Session, organization_id: UUID, agent_id: UUID) -> bool:
    """Hold the Agent row against a concurrent soft delete for the rest of the transaction.

    Agent deletion takes the row FOR UPDATE, so a write waiting here sees the deletion
    and stops, rather than adding a Task after the deletion removed the Agent's Tasks.
    """
    query = (
        select(Agent.id)
        .where(
            col(Agent.id) == agent_id,
            col(Agent.organization_id) == organization_id,
            col(Agent.deleted_at).is_(None),
        )
        .with_for_update(read=True)
    )
    return session.exec(query).first() is not None


def _agents_task(session: Session, organization_id: UUID, agent_id: UUID, task_id: UUID) -> AgentTask | None:
    query = select(AgentTask).where(
        col(AgentTask.id) == task_id,
        col(AgentTask.agent_id) == agent_id,
        col(AgentTask.organization_id) == organization_id,
    )
    return session.exec(query).first()


@inject
@singleton
@dataclass
class AgentTaskRepository:
    delegate: PostgresRepositoryDelegate

    def create_for_live_agent(self, organization_id: UUID, agent_id: UUID, data: AgentTaskCreate) -> AgentTask | None:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            if not _lock_live_agent(session, organization_id, agent_id):
                return None
            task = AgentTask(organization_id=organization_id, agent_id=agent_id, **data.model_dump())
            session.add(task)
            session.commit()
            return task

    def update_status(
        self, organization_id: UUID, agent_id: UUID, task_id: UUID, status: AgentTaskStatus
    ) -> AgentTask | None:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            if not _lock_live_agent(session, organization_id, agent_id):
                return None
            task = _agents_task(session, organization_id, agent_id, task_id)
            if task is None:
                return None
            task.status = status
            task.updated_at = datetime.now(UTC)
            session.add(task)
            session.commit()
            return task

    def add_note(self, organization_id: UUID, agent_id: UUID, task_id: UUID, body: str) -> AgentTaskNote | None:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            if not _lock_live_agent(session, organization_id, agent_id):
                return None
            if _agents_task(session, organization_id, agent_id, task_id) is None:
                return None
            note = AgentTaskNote(task_id=task_id, body=body)
            session.add(note)
            session.commit()
            return note

    def find_by_agent(
        self,
        agent_id: UUID,
        task_filter: AgentTaskFilter,
        pagination: Pagination,
        authorization_scope: AuthorizationScope,
    ) -> PaginatedItems[AgentTaskRead]:
        return self._find(
            (col(AgentTask.agent_id) == agent_id,),
            task_filter,
            pagination,
            authorization_scope,
        )

    def find_in_organization(
        self,
        task_filter: AgentTaskFilter,
        pagination: Pagination,
        authorization_scope: AuthorizationScope,
    ) -> PaginatedItems[AgentTaskRead]:
        return self._find((), task_filter, pagination, authorization_scope)

    def get_detail(
        self,
        agent_id: UUID,
        task_id: UUID,
        authorization_scope: AuthorizationScope,
    ) -> AgentTaskDetail | None:
        with Session(self.delegate.engine) as session:
            task = session.exec(
                select(AgentTask)
                .join(Agent, col(Agent.id) == col(AgentTask.agent_id))
                .where(
                    col(AgentTask.id) == task_id,
                    col(AgentTask.agent_id) == agent_id,
                    *agent_scope_predicates(authorization_scope),
                )
            ).first()
            if task is None:
                return None
            notes = session.exec(
                select(AgentTaskNote)
                .where(col(AgentTaskNote.task_id) == task.id)
                .order_by(col(AgentTaskNote.created_at), col(AgentTaskNote.id))
            ).all()
            files = session.exec(
                select(AgentTaskFile)
                .where(col(AgentTaskFile.task_id) == task.id)
                .order_by(col(AgentTaskFile.created_at), col(AgentTaskFile.id))
            ).all()
            return AgentTaskDetail(
                **AgentTaskRead.model_validate(task).model_dump(),
                notes=[AgentTaskNoteRead.model_validate(note) for note in notes],
                files=[AgentTaskFileRead.model_validate(stored) for stored in files],
            )

    def _find(
        self,
        predicates: tuple,
        task_filter: AgentTaskFilter,
        pagination: Pagination,
        authorization_scope: AuthorizationScope,
    ) -> PaginatedItems[AgentTaskRead]:
        where = [*predicates, *agent_scope_predicates(authorization_scope)]
        if task_filter.status is not None:
            where.append(col(AgentTask.status) == task_filter.status)

        with Session(self.delegate.engine) as session:
            total = (
                session.scalar(
                    select(func.count())
                    .select_from(AgentTask)
                    .join(Agent, col(Agent.id) == col(AgentTask.agent_id))
                    .where(*where)
                )
                or 0
            )
            rows = session.exec(
                select(AgentTask)
                .join(Agent, col(Agent.id) == col(AgentTask.agent_id))
                .where(*where)
                .order_by(col(AgentTask.created_at).desc(), col(AgentTask.id).desc())
                .offset((pagination.page - 1) * pagination.size)
                .limit(pagination.size)
            ).all()

        return PaginatedItems[AgentTaskRead](
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=[AgentTaskRead.model_validate(row) for row in rows],
        )
