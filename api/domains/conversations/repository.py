from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, and_, col, or_, select

from api.domains.conversations.models import (
    AgentChatMessage,
    ConversationType,
    ConversationsCursor,
    ConversationsFilter,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class ConversationRepository:
    delegate: PostgresRepositoryDelegate

    def upsert_messages(self, messages: list[AgentChatMessage]) -> None:
        if not messages:
            return
        with Session(self.delegate.engine) as session:
            rows = [
                {
                    "id": m.id,
                    "created_at": m.created_at,
                    "updated_at": m.updated_at,
                    "agent_id": m.agent_id,
                    "openclaw_msg_id": m.openclaw_msg_id,
                    "session_key": m.session_key,
                    "channel_id": m.channel_id,
                    "thread_id": m.thread_id,
                    "direction": m.direction,
                    "conversation_type": m.conversation_type,
                    "sender_id": m.sender_id,
                    "sender_name": m.sender_name,
                    "channel_name": m.channel_name,
                    "content": m.content,
                    "occurred_at": m.occurred_at,
                }
                for m in messages
            ]
            stmt = insert(AgentChatMessage).values(rows)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_agent_chat_message_agent_msg",
                set_={
                    "thread_id": stmt.excluded.thread_id,
                    "sender_name": stmt.excluded.sender_name,
                    "channel_name": stmt.excluded.channel_name,
                    "content": stmt.excluded.content,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            session.exec(stmt)  # type: ignore[call-overload]
            session.commit()

    def distinct_channels(
        self, agent_id: UUID
    ) -> list[tuple[str, str | None, ConversationType]]:
        """Returns DISTINCT (channel_id, channel_name, conversation_type) per agent.

        Picks the latest non-null channel_name per channel_id.
        """
        with Session(self.delegate.engine) as session:
            query = (
                select(
                    AgentChatMessage.channel_id,
                    AgentChatMessage.channel_name,
                    AgentChatMessage.conversation_type,
                )
                .where(col(AgentChatMessage.agent_id) == agent_id)
                .order_by(
                    col(AgentChatMessage.channel_id),
                    col(AgentChatMessage.channel_name).desc().nulls_last(),
                )
                .distinct(col(AgentChatMessage.channel_id))
            )
            rows = session.exec(query).all()
            return [(r[0], r[1], r[2]) for r in rows]

    def find_channel_page(
        self,
        agent_id: UUID,
        channel_id: str,
        filter: ConversationsFilter,
        cursor: ConversationsCursor,
        page_size: int,
    ) -> tuple[list[AgentChatMessage], ConversationsCursor | None]:
        """Fetch a page of messages for a channel.

        Returns messages ordered occurred_at ASC for direct UI append.
        Pages flat by occurred_at — channel-root and thread-reply messages are
        treated uniformly so threads remain visible even when no top-level
        @-mention exists.
        """
        with Session(self.delegate.engine) as session:
            filters = [
                col(AgentChatMessage.agent_id) == agent_id,
                col(AgentChatMessage.channel_id) == channel_id,
            ]
            if filter.from_date is not None:
                filters.append(col(AgentChatMessage.occurred_at) >= filter.from_date)
            if filter.to_date is not None:
                filters.append(col(AgentChatMessage.occurred_at) < filter.to_date)
            if cursor.before_occurred_at is not None:
                tiebreaker = (
                    col(AgentChatMessage.occurred_at) < cursor.before_occurred_at
                )
                if cursor.before_id is not None:
                    tiebreaker = or_(
                        col(AgentChatMessage.occurred_at) < cursor.before_occurred_at,
                        and_(
                            col(AgentChatMessage.occurred_at)
                            == cursor.before_occurred_at,
                            col(AgentChatMessage.id) < cursor.before_id,
                        ),
                    )
                filters.append(tiebreaker)

            query = (
                select(AgentChatMessage)
                .where(*filters)
                .order_by(
                    col(AgentChatMessage.occurred_at).desc(),
                    col(AgentChatMessage.id).desc(),
                )
                .limit(page_size + 1)
            )
            msgs_desc = list(session.exec(query).all())

            has_more = len(msgs_desc) > page_size
            msgs_desc = msgs_desc[:page_size]
            if not msgs_desc:
                return [], None

            oldest = msgs_desc[-1]
            next_cursor: ConversationsCursor | None = (
                ConversationsCursor(
                    before_occurred_at=oldest.occurred_at, before_id=oldest.id
                )
                if has_more
                else None
            )
            msgs_desc.reverse()
            return msgs_desc, next_cursor

    def find_all_channel_messages(
        self,
        agent_id: UUID,
        channel_id: str,
        filter: ConversationsFilter,
    ) -> list[AgentChatMessage]:
        """Return all messages for a channel in the filter range, ordered occurred_at ASC."""
        with Session(self.delegate.engine) as session:
            filters = [
                col(AgentChatMessage.agent_id) == agent_id,
                col(AgentChatMessage.channel_id) == channel_id,
            ]
            if filter.from_date is not None:
                filters.append(col(AgentChatMessage.occurred_at) >= filter.from_date)
            if filter.to_date is not None:
                filters.append(col(AgentChatMessage.occurred_at) < filter.to_date)
            query = (
                select(AgentChatMessage)
                .where(*filters)
                .order_by(
                    col(AgentChatMessage.occurred_at).asc(),
                    col(AgentChatMessage.id).asc(),
                )
            )
            return list(session.exec(query).all())
