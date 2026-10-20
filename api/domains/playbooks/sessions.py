from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from injector import inject, singleton

from api.domains.playbooks.repository import PlaybookSessionRepository
from api.domains.playbooks.transcripts import (
    TOOL_SESSION_SLACK,
    SessionTranscript,
    assign_tool_sessions,
    render_transcripts,
)
from api.domains.rbac.policy import AuthorizationScope


@inject
@singleton
@dataclass
class PlaybookSessionReader:
    """The transcripts a run reads: the latest conversations in its window, with their Tool Calls."""

    repository: PlaybookSessionRepository

    def read(
        self,
        agent_id: UUID,
        authorization_scope: AuthorizationScope,
        window_start: datetime,
        window_end: datetime,
        max_sessions: int,
    ) -> list[SessionTranscript]:
        conversations = self.repository.conversation_spans(
            agent_id, authorization_scope, window_start, window_end, max_sessions
        )
        if not conversations:
            return []
        session_keys = [conversation.session_key for conversation in conversations]
        messages = self.repository.messages(agent_id, authorization_scope, session_keys, window_start, window_end)
        # Only runtime sessions that could fall inside a selected conversation are paired.
        tool_sessions = self.repository.tool_session_spans(
            agent_id,
            authorization_scope,
            max(window_start, min(c.started_at for c in conversations) - TOOL_SESSION_SLACK),
            min(window_end, max(c.ended_at for c in conversations) + TOOL_SESSION_SLACK),
        )
        owners = assign_tool_sessions(conversations, tool_sessions)
        tool_calls = self.repository.tool_calls(agent_id, authorization_scope, list(owners), window_start, window_end)
        return render_transcripts(conversations, messages, tool_calls, owners)
