from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.auth.models import CurrentUserContext
from api.domains.conversations.models import (
    AgentChatMessage,
    ConversationChannelRead,
    ConversationMessageRead,
    ConversationsCursor,
    ConversationsFilter,
    ConversationThreadRead,
    ConversationThreadsPage,
)
from api.domains.conversations.repository import ConversationRepository
from api.domains.rbac.catalog import PermissionKey


@inject
@singleton
@dataclass
class ConversationService:
    repository: ConversationRepository
    agent_authorization: AgentAuthorization

    def list_channels(self, agent_id: UUID, context: CurrentUserContext) -> list[ConversationChannelRead]:
        agent = self.agent_authorization.require_visible(context, agent_id)
        activity_scope = self.agent_authorization.require_action_for_visible(
            context, agent, PermissionKey.ACTIVITY_READ
        )
        db_channels = self.repository.distinct_channels(agent_id, activity_scope)
        return [
            ConversationChannelRead(
                connection_id=connection_id,
                connection_name=connection_name,
                platform_key=platform_key,
                channel_id=channel_id,
                channel_name=channel_name,
                conversation_type=conversation_type,
            )
            for connection_id, connection_name, platform_key, channel_id, channel_name, conversation_type in db_channels
        ]

    def platform_daily_message_counts(
        self, window_start: datetime, window_end: datetime, **kwargs
    ) -> list[tuple[datetime, int, int]]:
        """Return bounded cross-Organization message counts for Platform View."""
        return self.repository.daily_direction_counts_since(window_start, window_end, **kwargs)

    def platform_daily_active_agent_ids(
        self, window_start: datetime, window_end: datetime, **kwargs
    ) -> dict[datetime, set[UUID]]:
        """Return Agent IDs with communication activity for Platform View."""
        return self.repository.daily_active_agent_ids_since(window_start, window_end, **kwargs)

    def list_threads(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
        connection_id: UUID,
        channel_id: str,
        filter: ConversationsFilter,
        cursor: ConversationsCursor,
        page_size: int,
    ) -> ConversationThreadsPage:
        agent = self.agent_authorization.require_visible(context, agent_id)
        activity_scope = self.agent_authorization.require_action_for_visible(
            context, agent, PermissionKey.ACTIVITY_READ
        )
        messages = self.repository.find_all_channel_messages(
            agent_id=agent_id,
            connection_id=connection_id,
            channel_id=channel_id,
            filter=filter,
            authorization_scope=activity_scope,
        )
        threads, has_more, next_cursor = _group_into_threads(messages, cursor, page_size)
        return ConversationThreadsPage(
            threads=threads,
            has_more=has_more,
            next_cursor=next_cursor,
        )


def _group_into_threads(
    messages: list[AgentChatMessage],
    cursor: ConversationsCursor,
    page_size: int,
) -> tuple[list[ConversationThreadRead], bool, ConversationsCursor | None]:
    by_thread: dict[str | None, list[AgentChatMessage]] = {}
    for m in messages:
        by_thread.setdefault(m.thread_id, []).append(m)

    null_msgs = sorted(by_thread.pop(None, []), key=lambda m: (m.occurred_at, m.id))
    used_null_ids: set = set()

    raw_threads: list[tuple[AgentChatMessage, list[AgentChatMessage]]] = []

    for tid, msgs in by_thread.items():
        if tid is None:
            continue
        try:
            tid_f = float(tid)
        except ValueError, TypeError:
            continue

        msgs_sorted = sorted(msgs, key=lambda m: (m.occurred_at, m.id))

        root: AgentChatMessage | None = None
        for nm in null_msgs:
            if nm.id in used_null_ids:
                continue
            if abs(nm.occurred_at.timestamp() - tid_f) <= 5.0:
                root = nm
                used_null_ids.add(nm.id)
                break

        extra_null_replies: list[AgentChatMessage] = []
        if root is not None:
            first_reply_ts = msgs_sorted[0].occurred_at if msgs_sorted else None
            for nm in null_msgs:
                if nm.id in used_null_ids:
                    continue
                if nm.occurred_at > root.occurred_at and (first_reply_ts is None or nm.occurred_at <= first_reply_ts):
                    extra_null_replies.append(nm)
                    used_null_ids.add(nm.id)

        if root is None:
            root = msgs_sorted[0]
            replies = msgs_sorted[1:]
        else:
            replies = extra_null_replies + msgs_sorted

        replies.sort(key=lambda m: (m.occurred_at, m.id))
        raw_threads.append((root, replies))

    for nm in null_msgs:
        if nm.id not in used_null_ids:
            raw_threads.append((nm, []))

    raw_threads.sort(key=lambda t: (t[0].occurred_at, t[0].id), reverse=True)

    if cursor.before_occurred_at is not None:
        before_ts = cursor.before_occurred_at
        before_id = cursor.before_id
        if before_id is not None:
            raw_threads = [
                t
                for t in raw_threads
                if t[0].occurred_at < before_ts or (t[0].occurred_at == before_ts and t[0].id < before_id)
            ]
        else:
            raw_threads = [t for t in raw_threads if t[0].occurred_at < before_ts]

    has_more = len(raw_threads) > page_size
    page_threads = raw_threads[:page_size]

    threads: list[ConversationThreadRead] = []
    for root, replies in reversed(page_threads):
        threads.append(
            ConversationThreadRead(
                root=ConversationMessageRead.model_validate(root),
                replies=[ConversationMessageRead.model_validate(r) for r in replies],
            )
        )

    next_cursor: ConversationsCursor | None = None
    if has_more and page_threads:
        oldest_root = page_threads[-1][0]
        next_cursor = ConversationsCursor(
            before_occurred_at=oldest_root.occurred_at,
            before_id=oldest_root.id,
        )

    return threads, has_more, next_cursor
