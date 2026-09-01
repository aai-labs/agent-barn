from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.communications.models import CommunicationDelivery, CommunicationDeliveryStatus
from api.domains.conversations.models import AgentChatMessage, MessageDirection
from api.domains.web_chat.models import WebChatThread
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@dataclass(frozen=True)
class ThreadSummary:
    thread_id: str
    last_occurred_at: datetime | None
    last_content: str | None
    first_content: str | None


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

    def delivery_statuses_for_messages(
        self,
        message_ids: list[UUID],
    ) -> dict[UUID, CommunicationDeliveryStatus]:
        if not message_ids:
            return {}
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(CommunicationDelivery.message_id, CommunicationDelivery.status).where(
                    col(CommunicationDelivery.message_id).in_(message_ids)
                )
            ).all()
            return {message_id: CommunicationDeliveryStatus(status) for message_id, status in rows}

    def list_threads(
        self,
        *,
        connection_id: UUID,
        channel_id: str,
        limit: int = 100,
    ) -> list[ThreadSummary]:
        """Return this user's distinct conversation threads, most recent first.

        Threads soft-deleted via WebChatThread.deleted_at are excluded.
        """
        with Session(self.delegate.engine) as session:
            deleted_ids = set(
                session.exec(
                    select(WebChatThread.thread_id).where(
                        col(WebChatThread.connection_id) == connection_id,
                        col(WebChatThread.channel_id) == channel_id,
                        col(WebChatThread.deleted_at).is_not(None),
                    )
                ).all()
            )

            # Postgres DISTINCT ON picks the first row per thread_id under the
            # given ORDER BY, so ordering by (thread_id, occurred_at desc, id
            # desc) yields exactly the latest message per thread in one query
            # — no aggregate needed (max() over a uuid column isn't defined).
            last_rows = session.exec(
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

            # Same DISTINCT ON trick, ascending, restricted to the user's own
            # messages — the opening line, used as a fallback title.
            first_rows = session.exec(
                select(AgentChatMessage)
                .distinct(col(AgentChatMessage.thread_id))
                .where(
                    col(AgentChatMessage.connection_id) == connection_id,
                    col(AgentChatMessage.channel_id) == channel_id,
                    col(AgentChatMessage.thread_id).is_not(None),
                    col(AgentChatMessage.direction) == MessageDirection.INBOUND,
                )
                .order_by(
                    col(AgentChatMessage.thread_id),
                    col(AgentChatMessage.occurred_at).asc(),
                    col(AgentChatMessage.id).asc(),
                )
            ).all()
            first_content_by_thread = {row.thread_id: row.content for row in first_rows}

            summaries = [
                ThreadSummary(
                    thread_id=row.thread_id or "",
                    last_occurred_at=row.occurred_at,
                    last_content=row.content,
                    first_content=first_content_by_thread.get(row.thread_id),
                )
                for row in last_rows
                if row.thread_id not in deleted_ids
            ]
            summaries.sort(
                key=lambda s: s.last_occurred_at or datetime.min.replace(tzinfo=UTC),
                reverse=True,
            )
            return summaries[:limit]

    def get_thread_metadata(
        self,
        *,
        connection_id: UUID,
        channel_id: str,
        thread_id: str,
    ) -> WebChatThread | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(WebChatThread).where(
                    col(WebChatThread.connection_id) == connection_id,
                    col(WebChatThread.channel_id) == channel_id,
                    col(WebChatThread.thread_id) == thread_id,
                )
            ).one_or_none()

    def list_thread_metadata(
        self,
        *,
        connection_id: UUID,
        channel_id: str,
    ) -> dict[str, WebChatThread]:
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(WebChatThread).where(
                    col(WebChatThread.connection_id) == connection_id,
                    col(WebChatThread.channel_id) == channel_id,
                )
            ).all()
            return {row.thread_id: row for row in rows}

    def rename_thread(
        self,
        *,
        connection_id: UUID,
        channel_id: str,
        thread_id: str,
        display_name: str,
    ) -> WebChatThread:
        with Session(self.delegate.engine) as session:
            row = session.exec(
                select(WebChatThread).where(
                    col(WebChatThread.connection_id) == connection_id,
                    col(WebChatThread.channel_id) == channel_id,
                    col(WebChatThread.thread_id) == thread_id,
                )
            ).one_or_none()
            if row is None:
                row = WebChatThread(
                    connection_id=connection_id,
                    channel_id=channel_id,
                    thread_id=thread_id,
                )
            row.display_name = display_name
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def soft_delete_thread(
        self,
        *,
        connection_id: UUID,
        channel_id: str,
        thread_id: str,
    ) -> None:
        with Session(self.delegate.engine) as session:
            row = session.exec(
                select(WebChatThread).where(
                    col(WebChatThread.connection_id) == connection_id,
                    col(WebChatThread.channel_id) == channel_id,
                    col(WebChatThread.thread_id) == thread_id,
                )
            ).one_or_none()
            if row is None:
                row = WebChatThread(
                    connection_id=connection_id,
                    channel_id=channel_id,
                    thread_id=thread_id,
                )
            row.deleted_at = datetime.now(UTC)
            session.add(row)
            session.commit()

    def restore_thread_if_deleted(
        self,
        *,
        connection_id: UUID,
        channel_id: str,
        thread_id: str,
    ) -> None:
        """Un-delete a thread on the way back in — sending a message to a
        deleted thread is a clear enough signal the user wants it back."""
        with Session(self.delegate.engine) as session:
            row = session.exec(
                select(WebChatThread).where(
                    col(WebChatThread.connection_id) == connection_id,
                    col(WebChatThread.channel_id) == channel_id,
                    col(WebChatThread.thread_id) == thread_id,
                    col(WebChatThread.deleted_at).is_not(None),
                )
            ).one_or_none()
            if row is None:
                return
            row.deleted_at = None
            session.add(row)
            session.commit()
