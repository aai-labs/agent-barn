from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from injector import inject, singleton
from sqlalchemy import func, update
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentRestorePoint, RestorePointOrigin, RestorePointStatus
from api.domains.agents.repository import agent_scope_predicates
from api.domains.rbac.policy import AuthorizationScope
from api.domains.restore_points.models import (
    ACTIVE_CAPTURE_STATUSES,
    NON_TERMINAL_STATUSES,
    AgentRestorePointRead,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import PaginatedItems, Pagination


@inject
@singleton
@dataclass
class RestorePointRepository:
    delegate: PostgresRepositoryDelegate

    def find_by_agent(
        self,
        agent_id: UUID,
        pagination: Pagination,
        authorization_scope: AuthorizationScope,
    ) -> PaginatedItems[AgentRestorePointRead]:
        with Session(self.delegate.engine) as session:
            visibility = agent_scope_predicates(authorization_scope)
            predicates = (col(AgentRestorePoint.agent_id) == agent_id, *visibility)

            count_query = (
                select(func.count())
                .select_from(AgentRestorePoint)
                .join(Agent, col(Agent.id) == col(AgentRestorePoint.agent_id))
                .where(*predicates)
            )
            total = session.scalar(count_query) or 0

            query = (
                select(AgentRestorePoint)
                .join(Agent, col(Agent.id) == col(AgentRestorePoint.agent_id))
                .where(*predicates)
                .order_by(col(AgentRestorePoint.created_at).desc())
                .offset((pagination.page - 1) * pagination.size)
                .limit(pagination.size)
            )
            rows = list(session.exec(query).all())

        return PaginatedItems[AgentRestorePointRead](
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=[AgentRestorePointRead.model_validate(row) for row in rows],
        )

    def get_in_scope(
        self,
        restore_point_id: UUID,
        agent_id: UUID,
        authorization_scope: AuthorizationScope,
    ) -> AgentRestorePoint | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentRestorePoint)
                .join(Agent, col(Agent.id) == col(AgentRestorePoint.agent_id))
                .where(
                    col(AgentRestorePoint.id) == restore_point_id,
                    col(AgentRestorePoint.agent_id) == agent_id,
                    *agent_scope_predicates(authorization_scope),
                )
            )
            return session.exec(query).first()

    def count_manual_for_agent(self, agent_id: UUID) -> int:
        """Manual restore points that still hold a volume.

        FAILED captures release their volume when they fail, so counting them
        would let a run of failures block an Agent from ever capturing again.
        """
        with Session(self.delegate.engine) as session:
            query = (
                select(func.count())
                .select_from(AgentRestorePoint)
                .where(
                    col(AgentRestorePoint.agent_id) == agent_id,
                    col(AgentRestorePoint.origin) == RestorePointOrigin.MANUAL,
                    col(AgentRestorePoint.status) != RestorePointStatus.FAILED,
                )
            )
            return session.scalar(query) or 0

    def has_active_capture(self, agent_id: UUID) -> bool:
        return self._exists_with_status(agent_id, ACTIVE_CAPTURE_STATUSES)

    def has_non_terminal_operation(self, agent_id: UUID) -> bool:
        return self._exists_with_status(agent_id, NON_TERMINAL_STATUSES)

    def find_non_terminal_for_agent(self, agent_id: UUID) -> list[AgentRestorePoint]:
        with Session(self.delegate.engine) as session:
            query = select(AgentRestorePoint).where(
                col(AgentRestorePoint.agent_id) == agent_id,
                col(AgentRestorePoint.status).in_(NON_TERMINAL_STATUSES),
            )
            return list(session.exec(query).all())

    def update_status(
        self,
        restore_point_id: UUID,
        new_status: RestorePointStatus,
        *,
        from_statuses: tuple[RestorePointStatus, ...],
    ) -> bool:
        return self._conditional_update(restore_point_id, from_statuses, {"status": new_status})

    def mark_ready(
        self,
        restore_point_id: UUID,
        *,
        archive_bytes: int | None,
        file_count: int | None,
    ) -> bool:
        return self._conditional_update(
            restore_point_id,
            NON_TERMINAL_STATUSES,
            {
                "status": RestorePointStatus.READY,
                "archive_bytes": archive_bytes,
                "file_count": file_count,
                "captured_at": datetime.now(UTC),
                "failure_reason": None,
                "job_name": None,
            },
        )

    def set_job_name(self, restore_point_id: UUID, job_name: str) -> bool:
        return self._conditional_update(restore_point_id, NON_TERMINAL_STATUSES, {"job_name": job_name})

    def mark_restored(self, restore_point_id: UUID) -> bool:
        return self._conditional_update(
            restore_point_id,
            (RestorePointStatus.RESTORING,),
            {
                "status": RestorePointStatus.READY,
                "failure_reason": None,
                "job_name": None,
            },
        )

    def mark_failed(self, restore_point_id: UUID, reason: str) -> bool:
        return self._conditional_update(
            restore_point_id,
            NON_TERMINAL_STATUSES,
            {
                "status": RestorePointStatus.FAILED,
                "failure_reason": reason,
                "job_name": None,
            },
        )

    def _conditional_update(
        self,
        restore_point_id: UUID,
        from_statuses: tuple[RestorePointStatus, ...],
        values: dict,
    ) -> bool:
        with Session(self.delegate.engine) as session:
            result = session.exec(
                update(AgentRestorePoint)
                .where(
                    col(AgentRestorePoint.id) == restore_point_id,
                    col(AgentRestorePoint.status).in_(from_statuses),
                )
                .values(**values, updated_at=datetime.now(UTC))
            )
            session.commit()
            return bool(result.rowcount)

    def delete(self, restore_point_id: UUID) -> bool:
        return self.delegate.delete_one(AgentRestorePoint, restore_point_id)

    def delete_for_agent(self, agent_id: UUID) -> None:
        with Session(self.delegate.engine) as session:
            query = select(AgentRestorePoint).where(col(AgentRestorePoint.agent_id) == agent_id)
            rows = list(session.exec(query).all())
        if rows:
            self.delegate.delete_many(rows)

    def save(self, restore_point: AgentRestorePoint) -> AgentRestorePoint:
        self.delegate.save(restore_point)
        return restore_point

    def _exists_with_status(self, agent_id: UUID, statuses: tuple[RestorePointStatus, ...]) -> bool:
        with Session(self.delegate.engine) as session:
            query = (
                select(col(AgentRestorePoint.id))
                .where(
                    col(AgentRestorePoint.agent_id) == agent_id,
                    col(AgentRestorePoint.status).in_(statuses),
                )
                .limit(1)
            )
            return session.exec(query).first() is not None
