from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy import func
from sqlmodel import Session, col, select

from api.domains.agent_tasks.file_storage import TaskFileStorage
from api.domains.agent_tasks.models import (
    AgentTask,
    AgentTaskCreate,
    AgentTaskDetail,
    AgentTaskFile,
    AgentTaskFileCreate,
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


class OrganizationTaskStorageFullError(Exception):
    """Storing the File would take the Organization's Task Files past its limit."""


@inject
@singleton
@dataclass
class AgentTaskRepository:
    delegate: PostgresRepositoryDelegate
    file_storage: TaskFileStorage

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

    def add_file(
        self,
        organization_id: UUID,
        agent_id: UUID,
        task_id: UUID,
        metadata: AgentTaskFileCreate,
        data: bytes,
        organization_limit_bytes: int,
    ) -> AgentTaskFile | None:
        """Record a File and store its bytes in one transaction, within the Organization's limit.

        A per-Organization advisory lock serialises the usage check with the insert, so
        two uploads at once cannot both fit under the limit and together exceed it.
        """
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            if not _lock_live_agent(session, organization_id, agent_id):
                return None
            if _agents_task(session, organization_id, agent_id, task_id) is None:
                return None
            session.connection().execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"agent_task_file:{organization_id}"},
            )
            used = session.scalar(
                select(func.coalesce(func.sum(AgentTaskFile.size_bytes), 0)).where(
                    col(AgentTaskFile.organization_id) == organization_id
                )
            )
            if (used or 0) + len(data) > organization_limit_bytes:
                raise OrganizationTaskStorageFullError
            stored = AgentTaskFile(
                organization_id=organization_id,
                task_id=task_id,
                size_bytes=len(data),
                **metadata.model_dump(),
            )
            session.add(stored)
            session.flush()
            self.file_storage.write(session, stored.id, data)
            session.commit()
            return stored

    def get_file(
        self,
        agent_id: UUID,
        task_id: UUID,
        file_id: UUID,
        authorization_scope: AuthorizationScope,
    ) -> AgentTaskFile | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(AgentTaskFile)
                .join(AgentTask, col(AgentTask.id) == col(AgentTaskFile.task_id))
                .join(Agent, col(Agent.id) == col(AgentTask.agent_id))
                .where(
                    col(AgentTaskFile.id) == file_id,
                    col(AgentTaskFile.task_id) == task_id,
                    col(AgentTask.agent_id) == agent_id,
                    *agent_scope_predicates(authorization_scope),
                )
            ).first()

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
