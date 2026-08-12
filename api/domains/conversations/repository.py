from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, and_, col, or_, select

from api.domains.agents.models import Agent, AgentPlatform
from api.domains.agents.repository import agent_scope_predicates
from api.domains.conversations.models import (
    AgentChatMessage,
    ConversationsCursor,
    ConversationsFilter,
    ConversationType,
    MessageDirection,
)
from api.domains.rbac.policy import AuthorizationScope
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

    def daily_direction_counts_since(
        self,
        window_start: datetime,
        window_end: datetime,
        *,
        unit: str = "day",
        organization_id: UUID | None = None,
        agent_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
        platform: AgentPlatform | None = None,
    ) -> list[tuple[datetime, int, int]]:
        """Daily inbound/outbound message counts for the stats surfaces (AF-256).
        Returns (iso_date, inbound, outbound) ordered by day.

        Unscoped by default and only ever reached through
        `require_platform_admin` — org-scoped reads go through AuthorizationScope
        like everything else. `agent_scope_predicates` is unusable here on three
        counts: it hard-requires a single organization_id, it appends
        `deleted_at IS NULL`, and it adds per-membership EXISTS subqueries.

        `organization_id` narrows the same aggregate to one tenant so a future
        Organization dashboard reuses this query behind its own route, DTO, and
        authorization rather than growing a second one.

        The join to Agent is conditional: with no Agent-owned filter there is no
        join at all, which keeps messages of soft-deleted Agents counted.
        Historical volume should survive an Agent's retirement, and AF-250
        requires the same of deleted-Agent activity. When a filter *is* applied
        the join is an inner join and deleted Agents still match, since nothing
        here predicates on `Agent.deleted_at`.

        occurred_at is timestamptz, so date_trunc would otherwise bucket in the
        session TimeZone. The explicit UTC conversion makes the buckets
        deterministic regardless of who is asking.
        """
        occurred_at_utc = sa.func.timezone("UTC", col(AgentChatMessage.occurred_at))
        message_bucket = sa.func.date_trunc(unit, occurred_at_utc)
        step = sa.text(f"interval '1 {unit}'")

        message_predicates = [
            col(AgentChatMessage.occurred_at) >= window_start,
            col(AgentChatMessage.occurred_at) < window_end,
        ]
        if agent_id is not None:
            message_predicates.append(col(AgentChatMessage.agent_id) == agent_id)

        agent_predicates = []
        if organization_id is not None:
            agent_predicates.append(col(Agent.organization_id) == organization_id)
        if created_by_user_id is not None:
            agent_predicates.append(col(Agent.created_by_user_id) == created_by_user_id)
        if platform is not None:
            agent_predicates.append(col(Agent.platform) == platform)

        with Session(self.delegate.engine) as session:
            # Every bucket in the window is generated up front and left-joined,
            # so a quiet hour is a zero rather than a hole. Without this the
            # series is sparse and an hourly chart collapses to the few buckets
            # that happened to see traffic.
            buckets = select(
                sa.func.generate_series(
                    sa.func.date_trunc(unit, sa.func.timezone("UTC", sa.literal(window_start))),
                    sa.func.date_trunc(unit, sa.func.timezone("UTC", sa.literal(window_end))),
                    step,
                ).label("bucket")
            ).subquery()

            messages = select(
                message_bucket.label("bucket"),
                col(AgentChatMessage.direction).label("direction"),
            ).where(*message_predicates)
            if agent_predicates:
                messages = messages.join(Agent, col(Agent.id) == col(AgentChatMessage.agent_id)).where(
                    *agent_predicates
                )
            messages = messages.subquery()

            bucket_col = buckets.c.bucket
            joined_direction = messages.c.direction

            query = (
                select(
                    sa.func.timezone("UTC", bucket_col).label("bucket"),
                    sa.func.count(joined_direction)
                    .filter(joined_direction == MessageDirection.INBOUND)
                    .label("inbound"),
                    sa.func.count(joined_direction)
                    .filter(joined_direction == MessageDirection.OUTBOUND)
                    .label("outbound"),
                )
                .select_from(buckets)
                .outerjoin(messages, messages.c.bucket == bucket_col)
                .group_by(bucket_col)
                .order_by(bucket_col)
            )
            rows = session.exec(query).all()  # type: ignore[call-overload]
            return [(row[0], int(row[1]), int(row[2])) for row in rows]

    def daily_active_agent_ids_since(
        self,
        window_start: datetime,
        window_end: datetime,
        *,
        unit: str = "day",
        organization_id: UUID | None = None,
        agent_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
        platform: AgentPlatform | None = None,
    ) -> dict[datetime, set[UUID]]:
        """{iso_date: {agent_id}} — Agents that exchanged at least one message
        that UTC day (AF-256).

        Returns the identities rather than a count because activity is the union
        of this and tool-call activity, and an Agent that both messaged and
        called a tool must not be counted twice. Deduplication happens in the
        service, which is also the only place allowed to see both domains.
        """
        occurred_at_utc = sa.func.timezone("UTC", col(AgentChatMessage.occurred_at))
        day = sa.func.date_trunc(unit, occurred_at_utc).label("day")

        agent_predicates = []
        if organization_id is not None:
            agent_predicates.append(col(Agent.organization_id) == organization_id)
        if created_by_user_id is not None:
            agent_predicates.append(col(Agent.created_by_user_id) == created_by_user_id)
        if platform is not None:
            agent_predicates.append(col(Agent.platform) == platform)

        with Session(self.delegate.engine) as session:
            query = select(sa.func.timezone("UTC", day), col(AgentChatMessage.agent_id)).where(
                col(AgentChatMessage.occurred_at) >= window_start,
                col(AgentChatMessage.occurred_at) < window_end,
            )
            if agent_id is not None:
                query = query.where(col(AgentChatMessage.agent_id) == agent_id)
            if agent_predicates:
                query = query.join(Agent, col(Agent.id) == col(AgentChatMessage.agent_id)).where(*agent_predicates)

            query = query.distinct()
            rows = session.exec(query).all()  # type: ignore[call-overload]

            by_bucket: dict[datetime, set[UUID]] = {}
            for bucket, active_agent_id in rows:
                by_bucket.setdefault(bucket, set()).add(active_agent_id)
            return by_bucket

    def distinct_channels(
        self, agent_id: UUID, authorization_scope: AuthorizationScope
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
                .join(Agent, col(Agent.id) == col(AgentChatMessage.agent_id))
                .where(
                    col(AgentChatMessage.agent_id) == agent_id,
                    *agent_scope_predicates(authorization_scope),
                )
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
        authorization_scope: AuthorizationScope,
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
                tiebreaker = col(AgentChatMessage.occurred_at) < cursor.before_occurred_at
                if cursor.before_id is not None:
                    tiebreaker = or_(
                        col(AgentChatMessage.occurred_at) < cursor.before_occurred_at,
                        and_(
                            col(AgentChatMessage.occurred_at) == cursor.before_occurred_at,
                            col(AgentChatMessage.id) < cursor.before_id,
                        ),
                    )
                filters.append(tiebreaker)

            query = (
                select(AgentChatMessage)
                .join(Agent, col(Agent.id) == col(AgentChatMessage.agent_id))
                .where(*filters, *agent_scope_predicates(authorization_scope))
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
                ConversationsCursor(before_occurred_at=oldest.occurred_at, before_id=oldest.id) if has_more else None
            )
            msgs_desc.reverse()
            return msgs_desc, next_cursor

    def find_all_channel_messages(
        self,
        agent_id: UUID,
        channel_id: str,
        filter: ConversationsFilter,
        authorization_scope: AuthorizationScope,
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
                .join(Agent, col(Agent.id) == col(AgentChatMessage.agent_id))
                .where(*filters, *agent_scope_predicates(authorization_scope))
                .order_by(
                    col(AgentChatMessage.occurred_at).asc(),
                    col(AgentChatMessage.id).asc(),
                )
            )
            return list(session.exec(query).all())
