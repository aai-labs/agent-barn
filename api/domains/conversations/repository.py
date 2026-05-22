from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from injector import inject, singleton
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, and_, col, or_, select

from api.domains.conversations.models import (
    AgentChatMessage,
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
                    "sender_name": stmt.excluded.sender_name,
                    "channel_name": stmt.excluded.channel_name,
                    "content": stmt.excluded.content,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            session.exec(stmt)  # type: ignore[call-overload]
            session.commit()

    def distinct_channels(self, agent_id: UUID) -> list[tuple[str, str | None]]:
        """Returns DISTINCT (channel_id, channel_name) pairs for an agent.

        Picks the latest non-null channel_name per channel.
        """
        with Session(self.delegate.engine) as session:
            query = (
                select(
                    AgentChatMessage.channel_id,
                    AgentChatMessage.channel_name,
                )
                .where(col(AgentChatMessage.agent_id) == agent_id)
                .order_by(
                    col(AgentChatMessage.channel_id),
                    col(AgentChatMessage.channel_name).desc().nulls_last(),
                )
                .distinct(col(AgentChatMessage.channel_id))
            )
            rows = session.exec(query).all()
            return [(r[0], r[1]) for r in rows]

    def find_channel_page(
        self,
        agent_id: UUID,
        channel_id: str,
        filter: ConversationsFilter,
        cursor: ConversationsCursor,
        page_size: int,
    ) -> tuple[list[AgentChatMessage], ConversationsCursor | None]:
        """Fetch a page of channel-level messages + their thread replies.

        Returns messages ordered occurred_at ASC for direct UI append.
        next_cursor is None if there are no older channel-level messages.
        """
        with Session(self.delegate.engine) as session:
            base_filters = [
                col(AgentChatMessage.agent_id) == agent_id,
                col(AgentChatMessage.channel_id) == channel_id,
            ]
            if filter.from_date is not None:
                base_filters.append(
                    col(AgentChatMessage.occurred_at) >= filter.from_date
                )
            if filter.to_date is not None:
                base_filters.append(col(AgentChatMessage.occurred_at) < filter.to_date)

            channel_filters = list(base_filters) + [
                col(AgentChatMessage.thread_id).is_(None)
            ]
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
                channel_filters.append(tiebreaker)

            channel_query = (
                select(AgentChatMessage)
                .where(*channel_filters)
                .order_by(
                    col(AgentChatMessage.occurred_at).desc(),
                    col(AgentChatMessage.id).desc(),
                )
                .limit(page_size + 1)
            )
            channel_msgs_desc = list(session.exec(channel_query).all())

            has_more = len(channel_msgs_desc) > page_size
            channel_msgs_desc = channel_msgs_desc[:page_size]
            if not channel_msgs_desc:
                return [], None

            oldest = channel_msgs_desc[-1]
            next_cursor: ConversationsCursor | None = (
                ConversationsCursor(
                    before_occurred_at=oldest.occurred_at, before_id=oldest.id
                )
                if has_more
                else None
            )

            window_start = oldest.occurred_at
            window_end = (
                cursor.before_occurred_at
                if cursor.before_occurred_at is not None
                else datetime(9999, 12, 31, tzinfo=timezone.utc)
            )
            thread_filters = list(base_filters) + [
                col(AgentChatMessage.thread_id).is_not(None),
                col(AgentChatMessage.occurred_at) >= window_start,
                col(AgentChatMessage.occurred_at) < window_end,
            ]
            thread_query = select(AgentChatMessage).where(*thread_filters)
            thread_msgs = list(session.exec(thread_query).all())

            merged = channel_msgs_desc + thread_msgs
            merged.sort(key=lambda m: (m.occurred_at, m.id))
            return merged, next_cursor
