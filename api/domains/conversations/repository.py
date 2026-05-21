from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col, select

from api.domains.conversations.models import AgentChatMessage
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

    def find_by_agent(self, agent_id: UUID) -> list[AgentChatMessage]:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentChatMessage)
                .where(col(AgentChatMessage.agent_id) == agent_id)
                .order_by(col(AgentChatMessage.occurred_at).asc())
            )
            return list(session.exec(query).all())
