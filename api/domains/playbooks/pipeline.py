import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from injector import inject, singleton

from api.core.config import Config
from api.domains.agent_memory.view_client import MemoryViewClient
from api.domains.agents.repository import AgentRepository
from api.domains.playbooks.models import PlaybookExtraction, PlaybookExtractionError
from api.domains.playbooks.platform_service import PlatformPlaybookService
from api.domains.playbooks.prompts import (
    NOTES_MAX_TOKENS,
    PLAYBOOK_MAX_TOKENS,
    PROMPT_VERSION,
    clip_memory,
    notes_messages,
    parse_notes,
    parse_playbook,
    playbook_messages,
    skill_markdown,
)
from api.domains.playbooks.repository import PlaybookExtractionRepository
from api.domains.playbooks.sessions import PlaybookSessionReader
from api.domains.playbooks.transcripts import SessionTranscript
from api.domains.rbac.policy import AuthorizationScope
from api.domains.skills.service import PlaybookDraftConflict, PlaybookTargetUnavailable, SkillService
from api.domains.templates.slug import slugify
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.litellm.completions import (
    CompletionError,
    CompletionFailure,
    CompletionResult,
    LiteLLMCompletionClient,
)

logger = logging.getLogger(__name__)

NOTES_CONCURRENCY = 4
MAX_MEMORIES = 200
_MEMORY_PAGE = 50
_FAILURES = {
    CompletionFailure.BUDGET_EXCEEDED: PlaybookExtractionError.SPEND_LIMIT_REACHED,
    CompletionFailure.KEY_OR_MODEL_REJECTED: PlaybookExtractionError.MODEL_UNAVAILABLE,
    CompletionFailure.UNAVAILABLE: PlaybookExtractionError.MODEL_ERROR,
    CompletionFailure.BAD_RESPONSE: PlaybookExtractionError.MODEL_ERROR,
}


class PlaybookExtractionFailed(Exception):
    """A run stopped for a reason people can act on; the code is stored on the run.

    ``values`` carries figures already recorded, such as the tokens spent before the stop.
    """

    def __init__(self, error: PlaybookExtractionError, **values: Any) -> None:
        super().__init__(error.value)
        self.error = error
        self.values = values


class RunCancelled(Exception):
    """A person cancelled the run while it was working; its status already says so."""


@dataclass
class _Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: Decimal | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, result: CompletionResult) -> None:
        with self.lock:
            self.prompt_tokens += result.prompt_tokens
            self.completion_tokens += result.completion_tokens
            if result.cost_usd is not None:
                self.cost_usd = (self.cost_usd or Decimal(0)) + result.cost_usd

    def values(self) -> dict[str, Any]:
        with self.lock:
            return {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "cost_usd": self.cost_usd,
            }


@inject
@singleton
@dataclass
class PlaybookPipeline:
    """Reads the source Agent's sessions and memories and writes the playbook draft.

    Every model call is billed to the source Agent's own LiteLLM key. Progress is
    stored only while the run is still RUNNING, so a cancellation stops it.
    """

    repository: PlaybookExtractionRepository
    sessions: PlaybookSessionReader
    agents: AgentRepository
    memories: MemoryViewClient
    completions: LiteLLMCompletionClient
    settings: PlatformPlaybookService
    skills: SkillService
    config: Config

    def run(self, extraction: PlaybookExtraction, authorization_scope: AuthorizationScope) -> None:
        try:
            self._run(extraction, authorization_scope)
        except RunCancelled:
            logger.info("Playbook extraction %s stopped after cancellation", extraction.id)

    def _run(self, extraction: PlaybookExtraction, authorization_scope: AuthorizationScope) -> None:
        model = self.settings.current_model()
        api_key = self._agent_key(extraction.source_agent_id)
        transcripts = self.sessions.read(
            extraction.source_agent_id,
            authorization_scope,
            extraction.window_start,
            extraction.window_end,
            extraction.max_sessions,
        )
        self._progress(
            extraction.id,
            model=model,
            prompt_version=PROMPT_VERSION,
            session_keys=[t.session_key for t in transcripts],
            session_count=len(transcripts),
            message_count=sum(t.message_count for t in transcripts),
            tool_call_count=sum(t.tool_call_count for t in transcripts),
            input_chars=sum(len(t.text) for t in transcripts),
        )
        if not transcripts:
            raise PlaybookExtractionFailed(PlaybookExtractionError.NO_SESSIONS)

        usage = _Usage()
        notes = self._notes(extraction.id, transcripts, api_key, model, usage)
        memories = self._memories(extraction.organization_id, extraction.source_agent_id)
        self._progress(extraction.id, memory_count=len(memories), **usage.values())

        result = self._complete(
            api_key, model, playbook_messages(extraction.skill_name, notes, memories), PLAYBOOK_MAX_TOKENS, usage
        )
        if result.truncated:
            raise PlaybookExtractionFailed(PlaybookExtractionError.ANSWER_TRUNCATED, **usage.values())
        playbook = parse_playbook(result.content)
        if playbook is None:
            raise PlaybookExtractionFailed(PlaybookExtractionError.MODEL_ERROR, **usage.values())
        rendered: dict[str, str] = {}

        def render(slug: str) -> str:
            rendered["markdown"] = skill_markdown(slug, playbook)
            return rendered["markdown"]

        # Kept on the run first, so a draft that cannot be written loses nothing paid for.
        self._progress(
            extraction.id,
            result_markdown=render(_preview_slug(extraction.skill_name)),
            result_conventions=[{"rule": c.rule, "conversations": c.conversations} for c in playbook.conventions],
            **usage.values(),
        )
        try:
            skill_id = self.skills.write_playbook_draft(
                extraction.organization_id, extraction.skill_id, extraction.skill_name, playbook.description, render
            )
        except PlaybookDraftConflict:
            raise PlaybookExtractionFailed(PlaybookExtractionError.DRAFT_CONFLICT, **usage.values()) from None
        except PlaybookTargetUnavailable, HTTPException:
            raise PlaybookExtractionFailed(PlaybookExtractionError.SKILL_UNAVAILABLE, **usage.values()) from None
        if (
            self.repository.succeed(
                extraction.id, skill_id=skill_id, result_markdown=rendered["markdown"], **usage.values()
            )
            is None
        ):
            # Cancelled after the draft was written; the draft stays for people to review or discard.
            raise RunCancelled()

    def _agent_key(self, agent_id: UUID) -> str:
        agent = self.agents.get_by_id(agent_id)
        if agent is None:
            raise PlaybookExtractionFailed(PlaybookExtractionError.SOURCE_AGENT_UNAVAILABLE)
        if not agent.litellm_key_encrypted or not self.config.litellm_base_url:
            raise PlaybookExtractionFailed(PlaybookExtractionError.MODEL_UNAVAILABLE)
        try:
            return decrypt_token(agent.litellm_key_encrypted, self.config.agent_token_encryption_key)
        except InvalidToken, ValueError:
            raise PlaybookExtractionFailed(PlaybookExtractionError.MODEL_UNAVAILABLE) from None

    def _notes(
        self,
        extraction_id: UUID,
        transcripts: list[SessionTranscript],
        api_key: str,
        model: str,
        usage: _Usage,
    ) -> list[dict[str, Any] | str]:
        cancelled = threading.Event()

        def take_notes(transcript: SessionTranscript) -> dict[str, Any] | str | None:
            if cancelled.is_set():
                return None
            result = self._complete(api_key, model, notes_messages(transcript), NOTES_MAX_TOKENS, usage, json=True)
            if not self.repository.record_progress(extraction_id, **usage.values()):
                cancelled.set()
                return None
            return parse_notes(result.content)

        with ThreadPoolExecutor(max_workers=NOTES_CONCURRENCY, thread_name_prefix="playbook-notes") as pool:
            futures = [pool.submit(take_notes, transcript) for transcript in transcripts]
            try:
                notes = [future.result() for future in futures]
            except BaseException:
                cancelled.set()
                for future in futures:
                    future.cancel()
                raise
        if cancelled.is_set():
            raise RunCancelled()
        # Small talk and one-off requests teach nothing; drop them unless nothing else is left.
        reusable = [n for n in notes if n is not None and not (isinstance(n, dict) and n.get("reusable") is False)]
        return reusable or [n for n in notes if n is not None]

    def _memories(self, organization_id: UUID, agent_id: UUID) -> list[str]:
        """Up to MAX_MEMORIES long-term memories; the run continues without them if memory is unavailable."""
        memories: list[str] = []
        try:
            while len(memories) < MAX_MEMORIES:
                page = self.memories.list_memories(
                    organization_id, agent_id, search=None, limit=_MEMORY_PAGE, offset=len(memories)
                )
                memories += [clip_memory(item.text) for item in page.items]
                if len(page.items) < _MEMORY_PAGE or len(memories) >= page.total:
                    break
        except HTTPException as exc:
            logger.info("Playbook extraction read no long-term memories for Agent %s: %s", agent_id, exc.status_code)
        return memories[:MAX_MEMORIES]

    def _complete(
        self,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        usage: _Usage,
        *,
        json: bool = True,
    ) -> CompletionResult:
        try:
            result = self.completions.complete(api_key, model, messages, max_tokens=max_tokens, json_response=json)
        except CompletionError as exc:
            raise PlaybookExtractionFailed(_FAILURES[exc.failure], **usage.values()) from None
        usage.add(result)
        return result

    def _progress(self, extraction_id: UUID, **values: Any) -> None:
        if not self.repository.record_progress(extraction_id, **values):
            raise RunCancelled()


def _preview_slug(name: str) -> str:
    return slugify(name) or "playbook"
