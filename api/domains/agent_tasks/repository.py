from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID, uuid7

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
    AgentTaskSummary,
)
from api.domains.agents.models import Agent
from api.domains.agents.repository import agent_scope_predicates
from api.domains.artifacts.models import ArtifactRead
from api.domains.rbac.policy import AuthorizationScope
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import PaginatedItems, Pagination

# Lists show a failed Task's latest Note in two lines; the Task's own page has all of it.
LATEST_NOTE_PREVIEW_CHARS = 300


def _lock_live_agent(session: Session, organization_id: UUID, agent_id: UUID) -> bool:
    """Hold the Agent row against a concurrent soft delete for the rest of the transaction.

    Agent deletion takes the row FOR UPDATE, so a write waiting here sees the deletion
    and stops, rather than adding a Task after the deletion removed the Agent's Tasks.
    FOR KEY SHARE is the weakest lock that conflicts with FOR UPDATE, so a long upload
    does not hold up ordinary updates to the Agent.
    """
    query = (
        select(Agent.id)
        .where(
            col(Agent.id) == agent_id,
            col(Agent.organization_id) == organization_id,
            col(Agent.deleted_at).is_(None),
        )
        .with_for_update(read=True, key_share=True)
    )
    return session.exec(query).first() is not None


def _find_agent_task(session: Session, organization_id: UUID, agent_id: UUID, task_id: UUID) -> AgentTask | None:
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
            task = _find_agent_task(session, organization_id, agent_id, task_id)
            if task is None:
                return None
            task.status = status
            session.add(task)
            session.commit()
            return task

    def add_note(self, organization_id: UUID, agent_id: UUID, task_id: UUID, body: str) -> AgentTaskNote | None:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            if not _lock_live_agent(session, organization_id, agent_id):
                return None
            if _find_agent_task(session, organization_id, agent_id, task_id) is None:
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
        artifact_id: UUID,
        pin: Callable[[Session, UUID], ArtifactRead],
    ) -> AgentTaskFile | None:
        """Attach an Artifact to a Task, pinning it in the same transaction.

        `pin` takes the Artifact's row lock, so a second attach of the same Artifact
        waits here and then finds the first one's File instead of adding another.
        """
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            if not _lock_live_agent(session, organization_id, agent_id):
                return None
            if _find_agent_task(session, organization_id, agent_id, task_id) is None:
                return None
            file_id = uuid7()
            artifact = pin(session, file_id)
            existing = session.exec(
                select(AgentTaskFile).where(
                    col(AgentTaskFile.task_id) == task_id, col(AgentTaskFile.artifact_id) == artifact_id
                )
            ).first()
            if existing is not None:
                return existing
            stored = AgentTaskFile(
                id=file_id,
                organization_id=organization_id,
                task_id=task_id,
                artifact_id=artifact_id,
                filename=artifact.filename,
                content_type=artifact.content_type,
                size_bytes=artifact.size,
            )
            session.add(stored)
            session.commit()
            return stored

    def remove_file(
        self,
        organization_id: UUID,
        agent_id: UUID,
        task_id: UUID,
        file_id: UUID,
        release: Callable[[Session, UUID], None],
    ) -> bool:
        """Delete one of the Agent's own Files, releasing its Artifact pin in the same transaction."""
        with Session(self.delegate.engine) as session:
            if not _lock_live_agent(session, organization_id, agent_id):
                return False
            if _find_agent_task(session, organization_id, agent_id, task_id) is None:
                return False
            stored = session.exec(
                select(AgentTaskFile).where(
                    col(AgentTaskFile.id) == file_id,
                    col(AgentTaskFile.task_id) == task_id,
                    col(AgentTaskFile.organization_id) == organization_id,
                )
            ).first()
            if stored is None:
                return False
            release(session, stored.id)
            session.delete(stored)
            session.commit()
            return True

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
                    col(AgentTaskFile.organization_id) == authorization_scope.organization_id,
                    col(AgentTaskFile.task_id) == task_id,
                    col(AgentTask.agent_id) == agent_id,
                    *agent_scope_predicates(authorization_scope),
                )
            ).first()

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
                    col(AgentTask.organization_id) == authorization_scope.organization_id,
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

    def find_in_organization(
        self,
        task_filter: AgentTaskFilter,
        pagination: Pagination,
        authorization_scope: AuthorizationScope,
        recently_changed_first: bool = False,
    ) -> PaginatedItems[AgentTaskRead]:
        """Tasks newest first, or most recently changed first."""
        order = col(AgentTask.updated_at) if recently_changed_first else col(AgentTask.created_at)
        where = [
            col(AgentTask.organization_id) == authorization_scope.organization_id,
            *agent_scope_predicates(authorization_scope),
        ]
        if task_filter.agent_id is not None:
            where.append(col(AgentTask.agent_id) == task_filter.agent_id)
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
                .order_by(order.desc(), col(AgentTask.id).desc())
                .offset((pagination.page - 1) * pagination.size)
                .limit(pagination.size)
            ).all()

        return PaginatedItems[AgentTaskRead](
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=[AgentTaskRead.model_validate(row) for row in rows],
        )

    def summarize(self, tasks: list[AgentTaskRead]) -> list[AgentTaskSummary]:
        """Add each Task's File and Note counts and its latest Note, in two queries for the whole page."""
        task_ids = [task.id for task in tasks]
        if not task_ids:
            return []
        with Session(self.delegate.engine) as session:
            file_counts = dict(
                session.exec(
                    select(AgentTaskFile.task_id, func.count())
                    .where(col(AgentTaskFile.task_id).in_(task_ids))
                    .group_by(col(AgentTaskFile.task_id))
                ).all()
            )
            ranked = (
                select(
                    AgentTaskNote.task_id,
                    func.left(col(AgentTaskNote.body), LATEST_NOTE_PREVIEW_CHARS).label("body"),
                    func.count().over(partition_by=col(AgentTaskNote.task_id)).label("note_count"),
                    func.row_number()
                    .over(
                        partition_by=col(AgentTaskNote.task_id),
                        order_by=(col(AgentTaskNote.created_at).desc(), col(AgentTaskNote.id).desc()),
                    )
                    .label("rank"),
                )
                .where(col(AgentTaskNote.task_id).in_(task_ids))
                .subquery()
            )
            notes = {
                task_id: (note_count, body)
                for task_id, body, note_count in session.exec(
                    select(ranked.c.task_id, ranked.c.body, ranked.c.note_count).where(ranked.c.rank == 1)
                ).all()
            }
        return [
            AgentTaskSummary(
                **task.model_dump(),
                file_count=file_counts.get(task.id, 0),
                note_count=notes.get(task.id, (0, None))[0],
                latest_note=notes.get(task.id, (0, None))[1],
            )
            for task in tasks
        ]
