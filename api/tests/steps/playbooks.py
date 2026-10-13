from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid7

from injector import Module, provider, singleton

from api.domains.communications.models import CommunicationConnection
from api.domains.conversations.models import AgentChatMessage, MessageDirection
from api.domains.playbooks.models import PlaybookExtraction, PlaybookExtractionStatus
from api.domains.playbooks.processor import PlaybookExtractionProcessor
from api.domains.playbooks.transport import PlaybookExtractionQueue
from api.domains.skills.repository import SkillRepository
from api.domains.tool_calls.models import ToolCall, ToolCallStatus
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, use_org_for_auth
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token


class RecordingQueue(PlaybookExtractionQueue):
    """Records accepted runs instead of sending them to Redis; can be made to fail."""

    def __init__(self) -> None:
        self.enqueued: list[UUID] = []
        self.unavailable = False

    def enqueue(self, extraction_id: UUID) -> None:
        if self.unavailable:
            raise ConnectionError("broker unavailable")
        self.enqueued.append(extraction_id)


class RecordingQueueModule(Module):
    def __init__(self) -> None:
        self.queue = RecordingQueue()

    @provider
    @singleton
    def provide_queue(self) -> PlaybookExtractionQueue:
        return self.queue


def playbooks_api_setup(*steps: Any) -> list[Any]:
    queue_module = RecordingQueueModule()

    def remember_queue(context: Any) -> None:
        context.queue = queue_module.queue

    return [
        set_env_variable(
            {
                "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                "LITELLM_BASE_URL": "http://litellm:4000",
                "LITELLM_SECRET_NAME": "litellm",
                "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            }
        ),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), queue_module]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(),
        use_org_for_auth(),
        remember_queue,
        *steps,
    ]


def there_is_a_playbook_extraction(
    status: PlaybookExtractionStatus = PlaybookExtractionStatus.QUEUED,
    skill_name: str = "Billing playbook",
    skill_id: UUID | None = None,
    created_at: datetime | None = None,
    started_at: datetime | None = None,
):
    """A run requested by the current Membership for the current Agent."""

    def step(context):
        now = created_at or datetime.now(UTC)
        extraction = PlaybookExtraction(
            organization_id=context.agent.organization_id,
            source_agent_id=context.agent.id,
            requested_by_membership_id=context.organization_user.id,
            requested_by_user_id=context.user.id,
            skill_id=skill_id,
            skill_name=skill_name,
            window_start=now - timedelta(days=30),
            window_end=now,
            max_sessions=20,
            status=status,
            started_at=started_at,
            created_at=now,
            updated_at=now,
        )
        context.postgres_delegate.save(extraction)
        context.extraction = extraction

    return step


def the_skill_has_a_draft():
    def step(context):
        context.injector.get(SkillRepository).save_new_draft(
            context.skill.id, [("SKILL.md", "# Unpublished edits")], description=None, required_providers=[]
        )

    return step


def process_extraction(context: Any, extraction_id: UUID | None = None) -> PlaybookExtraction:
    extraction_id = extraction_id or context.extraction.id
    context.injector.get(PlaybookExtractionProcessor).process(extraction_id)
    reloaded = context.postgres_delegate.find_by_id(PlaybookExtraction, extraction_id)
    assert reloaded is not None
    return reloaded


def there_is_a_conversation(
    session_key: str,
    started_at: datetime,
    messages: list[tuple[int, MessageDirection, str]],
    tool_session_id: str | None = None,
    tool_calls: tuple[tuple[int, str, dict, str], ...] = (),
):
    """Mirrored messages for the current Agent, and Tool Calls its runtime reported under its own session ID.

    Offsets are seconds after ``started_at``.
    """

    def step(context):
        connections = getattr(context, "playbook_connections", {})
        connection = connections.get(context.agent.id)
        if connection is None:
            connection = CommunicationConnection(
                organization_id=context.agent.organization_id,
                agent_id=context.agent.id,
                platform_key="slack",
                display_name="Slack",
                credentials_encrypted="test",
                driver_key_encrypted="test",
            )
            context.postgres_delegate.save(connection)
            connections[context.agent.id] = connection
            context.playbook_connections = connections
        for offset, direction, content in messages:
            context.postgres_delegate.save(
                AgentChatMessage(
                    agent_id=context.agent.id,
                    connection_id=connection.id,
                    openclaw_msg_id=str(uuid7()),
                    session_key=session_key,
                    channel_id="C1",
                    direction=direction,
                    sender_name="Ana" if direction == MessageDirection.INBOUND else None,
                    content=content,
                    occurred_at=started_at + timedelta(seconds=offset),
                )
            )
        for offset, tool_name, arguments, result in tool_calls:
            context.postgres_delegate.save(
                ToolCall(
                    organization_id=context.agent.organization_id,
                    agent_id=context.agent.id,
                    session_id=tool_session_id or f"run-{session_key}",
                    external_id=str(uuid7()),
                    tool_name=tool_name,
                    arguments=arguments,
                    result=result,
                    status=ToolCallStatus.SUCCESS,
                    occurred_at=started_at + timedelta(seconds=offset),
                    completed_at=started_at + timedelta(seconds=offset),
                )
            )

    return step
