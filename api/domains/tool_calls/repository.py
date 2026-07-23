import datetime
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from injector import inject, singleton
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent
from api.domains.agents.repository import agent_scope_predicates
from api.domains.rbac.policy import AuthorizationScope
from api.domains.tool_calls.models import (
    ToolCall,
    ToolCallFilter,
    ToolCallRead,
    ToolCallStatus,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import PaginatedItems, Pagination


@inject
@singleton
@dataclass
class ToolCallRepository:
    delegate: PostgresRepositoryDelegate

    def find_by_agent(
        self,
        agent_id: UUID,
        tool_call_filter: ToolCallFilter,
        pagination: Pagination,
        authorization_scope: AuthorizationScope,
    ) -> PaginatedItems[ToolCallRead]:
        with Session(self.delegate.engine) as session:
            visibility = agent_scope_predicates(authorization_scope)
            base = (
                select(ToolCall)
                .join(Agent, col(Agent.id) == col(ToolCall.agent_id))
                .where(
                    col(ToolCall.agent_id) == agent_id,
                    col(ToolCall.organization_id) == authorization_scope.organization_id,
                    *visibility,
                )
            )
            base = self._apply_filter(base, tool_call_filter)
            base = base.order_by(col(ToolCall.occurred_at).desc())

            count_query = (
                select(func.count())
                .select_from(ToolCall)
                .join(Agent, col(Agent.id) == col(ToolCall.agent_id))
                .where(
                    col(ToolCall.agent_id) == agent_id,
                    col(ToolCall.organization_id) == authorization_scope.organization_id,
                    *visibility,
                )
            )
            count_query = self._apply_filter(count_query, tool_call_filter)
            total = session.scalar(count_query) or 0

            page_query = base.offset((pagination.page - 1) * pagination.size).limit(pagination.size)
            items = [ToolCallRead.model_validate(row) for row in session.exec(page_query).all()]

            return PaginatedItems(
                page=pagination.page,
                page_size=pagination.size,
                total=total,
                items=items,
            )

    @staticmethod
    def _apply_filter(query, tool_call_filter: ToolCallFilter):
        if tool_call_filter.tool_name:
            query = query.where(col(ToolCall.tool_name).ilike(f"%{tool_call_filter.tool_name}%"))
        if tool_call_filter.status is not None:
            query = query.where(col(ToolCall.status) == tool_call_filter.status)
        if tool_call_filter.from_date is not None:
            query = query.where(col(ToolCall.occurred_at) >= tool_call_filter.from_date)
        if tool_call_filter.to_date is not None:
            query = query.where(col(ToolCall.occurred_at) < tool_call_filter.to_date)
        return query

    def upsert_pending(
        self,
        session: Session,
        organization_id: UUID,
        agent_id: UUID,
        session_id: str,
        external_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        occurred_at: datetime.datetime,
    ) -> None:
        """Insert a tool_call row in PENDING state. No-op on conflict."""
        stmt = (
            pg_insert(ToolCall)
            .values(
                organization_id=organization_id,
                agent_id=agent_id,
                session_id=session_id,
                external_id=external_id,
                tool_name=tool_name,
                arguments=arguments,
                status=ToolCallStatus.PENDING.value,
                occurred_at=occurred_at,
            )
            .on_conflict_do_nothing(constraint="uq_tool_call_agent_external")
        )
        session.exec(stmt)  # type: ignore[arg-type]

    def complete(
        self,
        session: Session,
        agent_id: UUID,
        external_id: str,
        result: Any | None,
        is_error: bool,
        completed_at: datetime.datetime,
    ) -> bool:
        """Transition a PENDING row to SUCCESS/ERROR. Returns True if a row matched."""
        target = session.exec(
            select(ToolCall).where(col(ToolCall.agent_id) == agent_id).where(col(ToolCall.external_id) == external_id)
        ).first()
        if target is None:
            return False

        target.result = result
        target.status = ToolCallStatus.ERROR if is_error else ToolCallStatus.SUCCESS
        target.completed_at = completed_at
        if target.occurred_at is not None:
            delta = completed_at - target.occurred_at
            target.duration_ms = int(delta.total_seconds() * 1000)
        session.add(target)
        return True

    def get_session(self) -> Session:
        return Session(self.delegate.engine)
