from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.conversations.models import AgentChatMessage
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@dataclass(frozen=True)
class ThreadSummary:
    thread_id: str
    last_occurred_at: datetime
    last_content: str


@inject
@singleton
@dataclass
class WebChatRepository:
    delegate: PostgresRepositoryDelegate

    def list_thread_messages(
        self,
        *,
        connection_id: UUID,
        channel_id: str,
        thread_id: str,
        after_id: UUID | None = None,
        limit: int = 500,
    ) -> list[AgentChatMessage]:
        with Session(self.delegate.engine) as session:
            query = select(AgentChatMessage).where(
                col(AgentChatMessage.connection_id) == connection_id,
                col(AgentChatMessage.channel_id) == channel_id,
                col(AgentChatMessage.thread_id) == thread_id,
            )
            # agent_chat_message.id is a UUIDv7, so it sorts chronologically —
            # safe to use directly as a "new since" cursor without a second
            # timestamp comparison.
            if after_id is not None:
                query = query.where(col(AgentChatMessage.id) > after_id)
            query = query.order_by(col(AgentChatMessage.id).asc()).limit(limit)
            return list(session.exec(query))

    def list_threads(
        self,
        *,
        connection_id: UUID,
        channel_id: str,
        limit: int = 100,
    ) -> list[ThreadSummary]:
        """Return this user's distinct conversation threads, most recent first."""
        with Session(self.delegate.engine) as session:
            # Postgres DISTINCT ON picks the first row per thread_id under the
            # given ORDER BY, so ordering by (thread_id, occurred_at desc, id
            # desc) yields exactly the latest message per thread in one query
            # — no aggregate needed (max() over a uuid column isn't defined).
            rows = session.exec(
                select(AgentChatMessage)
                .distinct(col(AgentChatMessage.thread_id))
                .where(
                    col(AgentChatMessage.connection_id) == connection_id,
                    col(AgentChatMessage.channel_id) == channel_id,
                    col(AgentChatMessage.thread_id).is_not(None),
                )
                .order_by(
                    col(AgentChatMessage.thread_id),
                    col(AgentChatMessage.occurred_at).desc(),
                    col(AgentChatMessage.id).desc(),
                )
            ).all()
            summaries = [
                ThreadSummary(
                    thread_id=row.thread_id or "",
                    last_occurred_at=row.occurred_at,
                    last_content=row.content,
                )
                for row in rows
            ]
            summaries.sort(key=lambda s: s.last_occurred_at, reverse=True)
            return summaries[:limit]
