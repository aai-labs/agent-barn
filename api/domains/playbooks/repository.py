from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlalchemy import exists, func, or_, update
from sqlalchemy import select as sql_select
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent
from api.domains.agents.repository import agent_scope_predicates
from api.domains.conversations.models import AgentChatMessage
from api.domains.events.catalog import EVENT_REGISTRY, PLAYBOOK_EXTRACTION_REQUESTED
from api.domains.events.models import ActorIdentity, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.repository import OutboxMessageRepository
from api.domains.playbooks.constants import (
    PLAYBOOK_EXTRACTION_QUEUED_STALE_AFTER_SECONDS,
    PLAYBOOK_EXTRACTION_STALE_AFTER_SECONDS,
)
from api.domains.playbooks.models import (
    ACTIVE_AGENT_INDEX,
    ACTIVE_STATUSES,
    PlaybookExtraction,
    PlaybookExtractionError,
    PlaybookExtractionFilter,
    PlaybookExtractionRead,
    PlaybookExtractionStatus,
)
from api.domains.playbooks.transcripts import (
    MAX_MESSAGES_PER_SESSION,
    MAX_TOOL_CALLS_PER_SESSION,
    ConversationSpan,
    MessageRow,
    ToolCallRow,
    ToolSessionSpan,
)
from api.domains.rbac.policy import AuthorizationScope
from api.domains.skills.models import SkillDraft
from api.domains.tool_calls.models import ToolCall
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import PaginatedItems, Pagination

# Bounds the pairing scan; a window busier than this pairs only its latest sessions.
MAX_TOOL_SESSIONS = 2_000


class ActiveExtractionExists(Exception):
    """The source Agent already has a queued or running extraction."""


@dataclass
class CreatedExtraction:
    extraction: PlaybookExtraction
    delivery_ids: list[UUID]


@inject
@singleton
@dataclass
class PlaybookExtractionRepository:
    delegate: PostgresRepositoryDelegate
    outbox_repository: OutboxMessageRepository

    def create_with_event(
        self,
        extraction: PlaybookExtraction,
        *,
        window_days: int,
        actor: ActorIdentity,
        actor_display: str,
        subject_display: str,
    ) -> CreatedExtraction:
        """Persist the queued run and its audit event, or raise ActiveExtractionExists."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            session.add(extraction)
            try:
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == ACTIVE_AGENT_INDEX:
                    raise ActiveExtractionExists() from None
                raise
            event = EVENT_REGISTRY.build_event(
                event_name=PLAYBOOK_EXTRACTION_REQUESTED,
                schema_version=1,
                occurred_at=extraction.created_at,
                organization_id=extraction.organization_id,
                actor=actor,
                subject=SubjectIdentity(
                    type=SubjectIdentityType.AGENT,
                    id=extraction.source_agent_id,
                    organization_id=extraction.organization_id,
                ),
                correlation_id=uuid4(),
                payload={
                    "organization_id": extraction.organization_id,
                    "extraction_id": extraction.id,
                    "agent_id": extraction.source_agent_id,
                    "skill_id": extraction.skill_id,
                    "skill_name": extraction.skill_name,
                    "window_days": window_days,
                    "max_sessions": extraction.max_sessions,
                    "actor_display": actor_display,
                    "subject_display": subject_display,
                },
            )
            self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
            delivery_ids = list(
                session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)).all()
            )
            session.commit()
            return CreatedExtraction(extraction=extraction, delivery_ids=delivery_ids)

    def find_for_agent(
        self,
        agent_id: UUID,
        pagination: Pagination,
        authorization_scope: AuthorizationScope,
    ) -> PaginatedItems[PlaybookExtractionRead]:
        return self._page((col(PlaybookExtraction.source_agent_id) == agent_id,), pagination, authorization_scope)

    def find_in_organization(
        self,
        extraction_filter: PlaybookExtractionFilter,
        pagination: Pagination,
        authorization_scope: AuthorizationScope,
    ) -> PaginatedItems[PlaybookExtractionRead]:
        predicates: list[Any] = []
        if extraction_filter.skill_id is not None:
            predicates.append(col(PlaybookExtraction.skill_id) == extraction_filter.skill_id)
        return self._page(tuple(predicates), pagination, authorization_scope)

    def _page(
        self,
        predicates: tuple[Any, ...],
        pagination: Pagination,
        authorization_scope: AuthorizationScope,
    ) -> PaginatedItems[PlaybookExtractionRead]:
        # Runs of Agents the caller cannot see, including deleted ones, stay hidden.
        scoped = (
            *predicates,
            col(PlaybookExtraction.organization_id) == authorization_scope.organization_id,
            *agent_scope_predicates(authorization_scope),
        )
        with Session(self.delegate.engine) as session:
            total = (
                session.scalar(
                    select(func.count())
                    .select_from(PlaybookExtraction)
                    .join(Agent, col(Agent.id) == col(PlaybookExtraction.source_agent_id))
                    .where(*scoped)
                )
                or 0
            )
            rows = session.exec(
                select(
                    PlaybookExtraction,
                    Agent.name,
                    exists().where(col(SkillDraft.skill_id) == col(PlaybookExtraction.skill_id)),
                )
                .join(Agent, col(Agent.id) == col(PlaybookExtraction.source_agent_id))
                .where(*scoped)
                .order_by(col(PlaybookExtraction.created_at).desc(), col(PlaybookExtraction.id).desc())
                .offset((pagination.page - 1) * pagination.size)
                .limit(pagination.size)
            ).all()
        return PaginatedItems[PlaybookExtractionRead](
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=[
                PlaybookExtractionRead.from_row(row, agent_name, bool(has_draft)) for row, agent_name, has_draft in rows
            ],
        )

    def get_in_scope(
        self,
        extraction_id: UUID,
        agent_id: UUID,
        authorization_scope: AuthorizationScope,
    ) -> PlaybookExtraction | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(PlaybookExtraction)
                .join(Agent, col(Agent.id) == col(PlaybookExtraction.source_agent_id))
                .where(
                    col(PlaybookExtraction.id) == extraction_id,
                    col(PlaybookExtraction.source_agent_id) == agent_id,
                    col(PlaybookExtraction.organization_id) == authorization_scope.organization_id,
                    *agent_scope_predicates(authorization_scope),
                )
            ).first()

    def get(self, extraction_id: UUID) -> PlaybookExtraction | None:
        """The row with no authorization scope, for the worker that already holds its ID."""
        with Session(self.delegate.engine) as session:
            return session.get(PlaybookExtraction, extraction_id)

    def cancel(self, extraction_id: UUID) -> PlaybookExtraction | None:
        """Cancel a queued or running run; None if it had already finished."""
        now = datetime.now(UTC)
        return self._transition(
            extraction_id,
            col(PlaybookExtraction.status).in_(ACTIVE_STATUSES),
            status=PlaybookExtractionStatus.CANCELLED,
            finished_at=now,
        )

    def claim(self, extraction_id: UUID) -> PlaybookExtraction | None:
        """Move a queued run to RUNNING.

        Returns None for any other state. A redelivered message for a run that already
        started never runs it again, because its model calls were billed.
        """
        return self._transition(
            extraction_id,
            col(PlaybookExtraction.status) == PlaybookExtractionStatus.QUEUED,
            status=PlaybookExtractionStatus.RUNNING,
            started_at=datetime.now(UTC),
        )

    def expire_abandoned(self, *, source_agent_id: UUID | None = None, extraction_id: UUID | None = None) -> int:
        """Fail runs no worker will finish, so they stop blocking their Agent's next run.

        A RUNNING run older than the stale window outlived the time limit, so its worker
        died; a QUEUED run older than its window lost its message. Returns how many failed.
        """
        if source_agent_id is None and extraction_id is None:
            raise ValueError("Name a source Agent or a run")
        now = datetime.now(UTC)
        target = (
            col(PlaybookExtraction.id) == extraction_id
            if extraction_id is not None
            else col(PlaybookExtraction.source_agent_id) == source_agent_id
        )
        abandoned = or_(
            (col(PlaybookExtraction.status) == PlaybookExtractionStatus.RUNNING)
            & (col(PlaybookExtraction.started_at) < now - timedelta(seconds=PLAYBOOK_EXTRACTION_STALE_AFTER_SECONDS)),
            (col(PlaybookExtraction.status) == PlaybookExtractionStatus.QUEUED)
            & (
                col(PlaybookExtraction.created_at)
                < now - timedelta(seconds=PLAYBOOK_EXTRACTION_QUEUED_STALE_AFTER_SECONDS)
            ),
        )
        with Session(self.delegate.engine) as session:
            expired = session.scalars(
                update(PlaybookExtraction)
                .where(target, abandoned)
                .values(
                    status=PlaybookExtractionStatus.FAILED,
                    error_code=PlaybookExtractionError.INTERRUPTED.value,
                    finished_at=now,
                    updated_at=now,
                )
                .returning(col(PlaybookExtraction.id))
            ).all()
            session.commit()
            return len(expired)

    def record_progress(self, extraction_id: UUID, **values: Any) -> bool:
        """Store intermediate figures while the run is still RUNNING; False once cancelled."""
        return (
            self._transition(
                extraction_id, col(PlaybookExtraction.status) == PlaybookExtractionStatus.RUNNING, **values
            )
            is not None
        )

    def succeed(self, extraction_id: UUID, **values: Any) -> PlaybookExtraction | None:
        return self._transition(
            extraction_id,
            col(PlaybookExtraction.status) == PlaybookExtractionStatus.RUNNING,
            status=PlaybookExtractionStatus.SUCCEEDED,
            error_code=None,
            finished_at=datetime.now(UTC),
            **values,
        )

    def fail(self, extraction_id: UUID, error: PlaybookExtractionError, **values: Any) -> PlaybookExtraction | None:
        """Fail an unfinished run. A run already cancelled or finished keeps its outcome."""
        return self._transition(
            extraction_id,
            col(PlaybookExtraction.status).in_(ACTIVE_STATUSES),
            status=PlaybookExtractionStatus.FAILED,
            error_code=error.value,
            finished_at=datetime.now(UTC),
            **values,
        )

    def _transition(self, extraction_id: UUID, condition: Any, **values: Any) -> PlaybookExtraction | None:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            updated_id = session.scalar(
                update(PlaybookExtraction)
                .where(col(PlaybookExtraction.id) == extraction_id, condition)
                .values(updated_at=datetime.now(UTC), **values)
                .returning(col(PlaybookExtraction.id))
            )
            session.commit()
            if updated_id is None:
                return None
            return session.get(PlaybookExtraction, updated_id)


@inject
@singleton
@dataclass
class PlaybookSessionRepository:
    """Bounded reads of one visible Agent's conversations and Tool Calls in a time window."""

    delegate: PostgresRepositoryDelegate

    def conversation_spans(
        self,
        agent_id: UUID,
        authorization_scope: AuthorizationScope,
        window_start: datetime,
        window_end: datetime,
        limit: int,
    ) -> list[ConversationSpan]:
        """The most recently active conversations in the window, newest first."""
        last_activity = func.max(AgentChatMessage.occurred_at)
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(AgentChatMessage.session_key, func.min(AgentChatMessage.occurred_at), last_activity)
                .join(Agent, col(Agent.id) == col(AgentChatMessage.agent_id))
                .where(
                    col(AgentChatMessage.agent_id) == agent_id,
                    col(AgentChatMessage.occurred_at) >= window_start,
                    col(AgentChatMessage.occurred_at) < window_end,
                    *agent_scope_predicates(authorization_scope),
                )
                .group_by(col(AgentChatMessage.session_key))
                .order_by(last_activity.desc(), col(AgentChatMessage.session_key))
                .limit(limit)
            ).all()
        return [ConversationSpan(session_key=key, started_at=start, ended_at=end) for key, start, end in rows]

    def messages(
        self,
        agent_id: UUID,
        authorization_scope: AuthorizationScope,
        session_keys: list[str],
        window_start: datetime,
        window_end: datetime,
    ) -> list[MessageRow]:
        """Each conversation's latest messages in the window, oldest first."""
        if not session_keys:
            return []
        position = (
            func.row_number()
            .over(
                partition_by=col(AgentChatMessage.session_key),
                order_by=(col(AgentChatMessage.occurred_at).desc(), col(AgentChatMessage.id).desc()),
            )
            .label("position")
        )
        with Session(self.delegate.engine) as session:
            ranked = (
                sql_select(
                    col(AgentChatMessage.session_key),
                    col(AgentChatMessage.direction),
                    col(AgentChatMessage.sender_name),
                    col(AgentChatMessage.content),
                    col(AgentChatMessage.occurred_at),
                    position,
                )
                .join(Agent, col(Agent.id) == col(AgentChatMessage.agent_id))
                .where(
                    col(AgentChatMessage.agent_id) == agent_id,
                    col(AgentChatMessage.session_key).in_(session_keys),
                    col(AgentChatMessage.occurred_at) >= window_start,
                    col(AgentChatMessage.occurred_at) < window_end,
                    *agent_scope_predicates(authorization_scope),
                )
                .subquery()
            )
            # Core execution: the per-session cap needs more columns than SQLModel's select types.
            rows = (
                session.connection()
                .execute(
                    sql_select(ranked)
                    .where(ranked.c.position <= MAX_MESSAGES_PER_SESSION)
                    .order_by(ranked.c.occurred_at)
                )
                .all()
            )
        return [
            MessageRow(
                session_key=key, direction=direction, sender_name=sender, content=content, occurred_at=occurred_at
            )
            for key, direction, sender, content, occurred_at, _position in rows
        ]

    def tool_session_spans(
        self,
        agent_id: UUID,
        authorization_scope: AuthorizationScope,
        window_start: datetime,
        window_end: datetime,
    ) -> list[ToolSessionSpan]:
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(ToolCall.session_id, func.min(ToolCall.occurred_at), func.max(ToolCall.occurred_at))
                .join(Agent, col(Agent.id) == col(ToolCall.agent_id))
                .where(
                    col(ToolCall.agent_id) == agent_id,
                    col(ToolCall.occurred_at) >= window_start,
                    col(ToolCall.occurred_at) < window_end,
                    *agent_scope_predicates(authorization_scope),
                )
                .group_by(col(ToolCall.session_id))
                .order_by(func.max(ToolCall.occurred_at).desc())
                .limit(MAX_TOOL_SESSIONS)
            ).all()
        return [ToolSessionSpan(session_id=key, started_at=start, ended_at=end) for key, start, end in rows]

    def tool_calls(
        self,
        agent_id: UUID,
        authorization_scope: AuthorizationScope,
        session_ids: list[str],
        window_start: datetime,
        window_end: datetime,
    ) -> list[ToolCallRow]:
        """Each runtime session's first Tool Calls in the window, oldest first."""
        if not session_ids:
            return []
        position = (
            func.row_number()
            .over(
                partition_by=col(ToolCall.session_id),
                order_by=(col(ToolCall.occurred_at), col(ToolCall.id)),
            )
            .label("position")
        )
        with Session(self.delegate.engine) as session:
            ranked = (
                sql_select(
                    col(ToolCall.session_id),
                    col(ToolCall.tool_name),
                    col(ToolCall.arguments),
                    col(ToolCall.result),
                    col(ToolCall.status),
                    col(ToolCall.occurred_at),
                    position,
                )
                .join(Agent, col(Agent.id) == col(ToolCall.agent_id))
                .where(
                    col(ToolCall.agent_id) == agent_id,
                    col(ToolCall.session_id).in_(session_ids),
                    col(ToolCall.occurred_at) >= window_start,
                    col(ToolCall.occurred_at) < window_end,
                    *agent_scope_predicates(authorization_scope),
                )
                .subquery()
            )
            rows = (
                session.connection()
                .execute(
                    sql_select(ranked)
                    .where(ranked.c.position <= MAX_TOOL_CALLS_PER_SESSION)
                    .order_by(ranked.c.occurred_at)
                )
                .all()
            )
        return [
            ToolCallRow(
                session_id=session_id,
                tool_name=tool_name,
                arguments=arguments,
                result=result,
                status=getattr(call_status, "value", str(call_status)),
                occurred_at=occurred_at,
            )
            for session_id, tool_name, arguments, result, call_status, occurred_at, _position in rows
        ]
