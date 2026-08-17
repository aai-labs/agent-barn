import datetime
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentPlatform
from api.domains.agents.repository import agent_scope_predicates
from api.domains.platform_admin.models import StatsGranularity
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
    ) -> ToolCall | None:
        """Transition a PENDING row to SUCCESS/ERROR. Returns the row, or None
        if none matched."""
        target = session.exec(
            select(ToolCall).where(col(ToolCall.agent_id) == agent_id).where(col(ToolCall.external_id) == external_id)
        ).first()
        if target is None:
            return None

        target.result = result
        target.status = ToolCallStatus.ERROR if is_error else ToolCallStatus.SUCCESS
        target.completed_at = completed_at
        if target.occurred_at is not None:
            delta = completed_at - target.occurred_at
            target.duration_ms = int(delta.total_seconds() * 1000)
        session.add(target)
        return target

    def daily_active_agent_ids_since(
        self,
        window_start: datetime.datetime,
        window_end: datetime.datetime,
        *,
        unit: StatsGranularity = StatsGranularity.DAY,
        organization_id: UUID | None = None,
        agent_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
        platform: AgentPlatform | None = None,
    ) -> dict[datetime.datetime, set[UUID]]:
        """{iso_date: {agent_id}} — Agents that ran at least one tool that UTC
        day (AF-256).

        Tool calls are the half of activity that survives an Agent acting on its
        own: the runtime plugins gate outbound *messages* on a user-triggered
        turn, but never gate tool calls, so scheduled and proactive work shows up
        here and nowhere else.

        Unscoped by default and only ever reached through
        `require_platform_admin`; `organization_id` narrows it for a future
        Organization dashboard. Unlike messages, `tool_call` carries
        organization_id directly, so that filter needs no join.
        """
        occurred_at_utc = sa.func.timezone("UTC", col(ToolCall.occurred_at))
        day = sa.func.date_trunc(unit.value, occurred_at_utc).label("day")

        with self.get_session() as session:
            query = select(sa.func.timezone("UTC", day), col(ToolCall.agent_id)).where(
                col(ToolCall.occurred_at) >= window_start,
                col(ToolCall.occurred_at) < window_end,
            )
            if organization_id is not None:
                query = query.where(col(ToolCall.organization_id) == organization_id)
            if agent_id is not None:
                query = query.where(col(ToolCall.agent_id) == agent_id)
            if created_by_user_id is not None or platform is not None:
                query = query.join(Agent, col(Agent.id) == col(ToolCall.agent_id))
                if created_by_user_id is not None:
                    query = query.where(col(Agent.created_by_user_id) == created_by_user_id)
                if platform is not None:
                    query = query.where(col(Agent.platform) == platform)

            query = query.distinct()
            rows = session.exec(query).all()  # type: ignore[call-overload]

            by_bucket: dict[datetime.datetime, set[UUID]] = {}
            for bucket, active_agent_id in rows:
                by_bucket.setdefault(bucket, set()).add(active_agent_id)
            return by_bucket

    def get_session(self) -> Session:
        return Session(self.delegate.engine)
