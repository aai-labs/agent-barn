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


@dataclass(frozen=True)
class WebChatDeliveryState:
    status: CommunicationDeliveryStatus
    cancel_requested_at: datetime | None


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

            # The initial page is a bounded history window. Read newest-first
            # so PostgreSQL can stop after `limit` rows, then restore the
            # chronological order expected by the UI.
            query = query.order_by(col(AgentChatMessage.id).desc()).limit(limit)
            return list(reversed(session.exec(query).all()))

    def delivery_statuses_for_messages(
        self,
        message_ids: list[UUID],
    ) -> dict[UUID, WebChatDeliveryState]:
        if not message_ids:
            return {}
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(
                    CommunicationDelivery.message_id,
                    CommunicationDelivery.status,
                    CommunicationDelivery.cancel_requested_at,
                ).where(col(CommunicationDelivery.message_id).in_(message_ids))
            ).all()
            return {
                message_id: WebChatDeliveryState(
                    status=CommunicationDeliveryStatus(status),
                    cancel_requested_at=cancel_requested_at,
                )
                for message_id, status, cancel_requested_at in rows
            }

    def get_message_for_delivery(
        self,
        *,
        delivery_id: UUID,
        connection_id: UUID,
        channel_id: str,
        thread_id: str,
    ) -> tuple[AgentChatMessage, WebChatDeliveryState] | None:
        """Return one message and its current delivery state, scoped to Web Chat."""
        with Session(self.delegate.engine) as session:
            delivery_row = session.exec(
                select(
                    CommunicationDelivery.message_id,
                    CommunicationDelivery.status,
                    CommunicationDelivery.cancel_requested_at,
                ).where(
                    col(CommunicationDelivery.id) == delivery_id,
                    col(CommunicationDelivery.connection_id) == connection_id,
                )
            ).one_or_none()
            if delivery_row is None:
                return None

            message_id, status, cancel_requested_at = delivery_row
            message = session.exec(
                select(AgentChatMessage).where(
                    col(AgentChatMessage.id) == message_id,
                    col(AgentChatMessage.connection_id) == connection_id,
                    col(AgentChatMessage.channel_id) == channel_id,
                    col(AgentChatMessage.thread_id) == thread_id,
                )
            ).one_or_none()
            if message is None:
                return None
            return message, WebChatDeliveryState(
                status=CommunicationDeliveryStatus(status),
                cancel_requested_at=cancel_requested_at,
            )

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
            deleted_thread_ids = select(WebChatThread.thread_id).where(
                col(WebChatThread.connection_id) == connection_id,
                col(WebChatThread.channel_id) == channel_id,
                col(WebChatThread.deleted_at).is_not(None),
            )

            # Postgres DISTINCT ON picks the first row per thread_id under the
            # given ORDER BY. Select only those message IDs in the inner query,
            # then apply the user-facing recency order and limit to the outer
            # query so PostgreSQL never materializes every thread row in Python.
            latest_message_ids = (
                select(AgentChatMessage.id)
                .distinct(col(AgentChatMessage.thread_id))
                .where(
                    col(AgentChatMessage.connection_id) == connection_id,
                    col(AgentChatMessage.channel_id) == channel_id,
                    col(AgentChatMessage.thread_id).is_not(None),
                    ~col(AgentChatMessage.thread_id).in_(deleted_thread_ids),
                )
                .order_by(
                    col(AgentChatMessage.thread_id),
                    col(AgentChatMessage.occurred_at).desc(),
                    col(AgentChatMessage.id).desc(),
                )
                .subquery()
            )
            last_rows = session.exec(
                select(AgentChatMessage)
                .where(col(AgentChatMessage.id).in_(select(latest_message_ids.c.id)))
                .order_by(col(AgentChatMessage.occurred_at).desc(), col(AgentChatMessage.id).desc())
                .limit(limit)
            ).all()

            # Same DISTINCT ON trick, ascending, restricted to the selected
            # threads and the user's own messages — the opening line, used as a
            # fallback title.
            selected_thread_ids = [row.thread_id for row in last_rows if row.thread_id is not None]
            first_rows = session.exec(
                select(AgentChatMessage)
                .distinct(col(AgentChatMessage.thread_id))
                .where(
                    col(AgentChatMessage.connection_id) == connection_id,
                    col(AgentChatMessage.channel_id) == channel_id,
                    col(AgentChatMessage.thread_id).is_not(None),
                    col(AgentChatMessage.direction) == MessageDirection.INBOUND,
                    col(AgentChatMessage.thread_id).in_(selected_thread_ids),
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
            ]
            return summaries

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
