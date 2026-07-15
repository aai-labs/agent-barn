import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.models import AgentPlatform
from api.domains.agents.repository import AgentRepository
from api.domains.conversations.models import (
    AgentChatMessage,
    ConversationChannelRead,
    ConversationMessageRead,
    ConversationThreadRead,
    ConversationThreadsPage,
    ConversationType,
    ConversationsCursor,
    ConversationsFilter,
)
from api.domains.conversations.repository import ConversationRepository
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.slack.client import SlackClient
from api.infrastructure.telegram.client import get_chat_display_name

logger = logging.getLogger(__name__)


@inject
@singleton
@dataclass
class ConversationService:
    repository: ConversationRepository
    agent_repository: AgentRepository
    config: Config

    def list_channels(
        self, agent_id: UUID, org_id: UUID
    ) -> list[ConversationChannelRead]:
        agent = self.agent_repository.get_active(agent_id, org_id)
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_id} not found",
            )

        db_channels = self.repository.distinct_channels(agent_id)
        merged: dict[str, tuple[str | None, ConversationType]] = {
            cid: (name, ctype) for cid, name, ctype in db_channels
        }

        self._resolve_channel_names(agent_id, merged)

        return [
            ConversationChannelRead(
                channel_id=cid, channel_name=name, conversation_type=ctype
            )
            for cid, (name, ctype) in sorted(merged.items())
        ]

    def _resolve_channel_names(
        self,
        agent_id: UUID,
        merged: dict[str, tuple[str | None, ConversationType]],
    ) -> None:
        unresolved_channels = [
            cid
            for cid, (name, ctype) in merged.items()
            if ctype == ConversationType.CHANNEL and (name is None or name == cid)
        ]
        unresolved_dms = [
            cid
            for cid, (name, ctype) in merged.items()
            if ctype == ConversationType.DM and (name is None or name == cid)
        ]
        if not unresolved_channels and not unresolved_dms:
            return
        user_map, channel_map, dm_map = self._platform_maps(
            agent_id, unresolved_ids=unresolved_channels + unresolved_dms
        )
        for cid in unresolved_channels:
            resolved = channel_map.get(cid)
            if resolved:
                merged[cid] = (resolved, merged[cid][1])
        for cid in unresolved_dms:
            resolved = dm_map.get(cid)
            if resolved:
                merged[cid] = (resolved, merged[cid][1])

    def _platform_maps(
        self,
        agent_id: UUID,
        unresolved_ids: list[str] | None = None,
    ) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        agent = self.agent_repository.get_by_id(agent_id)
        if not (agent and self.config.agent_token_encryption_key):
            return {}, {}, {}
        if agent.platform == AgentPlatform.TEAMS:
            return {}, {}, {}
        if agent.platform == AgentPlatform.TELEGRAM:
            return self._telegram_maps(agent_id, unresolved_ids or [])
        try:
            slack_config = self.agent_repository.get_slack_config(agent_id)
            if not slack_config:
                return {}, {}, {}
            bot_token = decrypt_token(
                slack_config.bot_token_encrypted,
                self.config.agent_token_encryption_key,
            )
            slack = SlackClient(bot_token)
            users = slack.list_users(include_bots=True, include_deleted=True)
            channels = slack.list_channels()
            user_map = {
                u["id"]: u["display_name"] or u["real_name"] or u["name"] or u["id"]
                for u in users
            }
            channel_map = {
                c["id"]: c["name"] for c in channels if c["id"] and c["name"]
            }
            try:
                dm_channels = slack.list_dm_channels()
                dm_map: dict[str, str] = {
                    dm["id"]: user_map.get(dm["user"], dm["user"]) for dm in dm_channels
                }
            except Exception:
                dm_map = {}
            return user_map, channel_map, dm_map
        except Exception as e:
            logger.warning("Failed to fetch Slack maps for agent %s: %s", agent_id, e)
            return {}, {}, {}

    def _telegram_maps(
        self, agent_id: UUID, unresolved_ids: list[str]
    ) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        if not unresolved_ids:
            return {}, {}, {}
        telegram_config = self.agent_repository.get_telegram_config(agent_id)
        if not telegram_config:
            return {}, {}, {}
        bot_token = decrypt_token(
            telegram_config.bot_token_encrypted,
            self.config.agent_token_encryption_key,
        )
        resolved: dict[str, str] = {}
        for chat_id in unresolved_ids:
            name = get_chat_display_name(bot_token, chat_id)
            if name:
                resolved[chat_id] = name
        return {}, resolved, resolved

    def list_threads(
        self,
        agent_id: UUID,
        org_id: UUID,
        channel_id: str,
        filter: ConversationsFilter,
        cursor: ConversationsCursor,
        page_size: int,
    ) -> ConversationThreadsPage:
        agent = self.agent_repository.get_active(agent_id, org_id)
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_id} not found",
            )

        messages = self.repository.find_all_channel_messages(
            agent_id=agent_id,
            channel_id=channel_id.upper(),
            filter=filter,
        )
        threads, has_more, next_cursor = _group_into_threads(
            messages, cursor, page_size
        )
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
                if nm.occurred_at > root.occurred_at and (
                    first_reply_ts is None or nm.occurred_at <= first_reply_ts
                ):
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
                if t[0].occurred_at < before_ts
                or (t[0].occurred_at == before_ts and t[0].id < before_id)
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
