from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from hamcrest import assert_that, calling, equal_to, raises

from api.domains.agents.models import Agent, AgentStatus, AgentType
from api.domains.ingest.models import (
    IngestBatchRequest,
    IngestToolCallEvent,
    IngestToolResultEvent,
)
from api.domains.ingest.service import IngestService
from api.tests.core.givenpy import given, then, when


def _make_agent(ingest_key_encrypted: str | None = "encrypted-key") -> Agent:
    return Agent(
        id=uuid4(),
        organization_id=uuid4(),
        name="test-agent",
        status=AgentStatus.RUNNING,
        agent_type=AgentType.OPENCLAW,
        litellm_key_encrypted="encrypted",
        model="gpt-5",
        agent_template_id=uuid4(),
        ingest_key_encrypted=ingest_key_encrypted,
    )


def _make_service(agent_repo=None, tc_repo=None) -> IngestService:
    return IngestService(
        agent_repository=agent_repo or MagicMock(),
        tool_call_repository=tc_repo or MagicMock(),
    )


# --- authenticate ---


def test_authenticate_raises_when_agent_not_found():
    with given():
        repo = MagicMock()
        repo.get_by_id.return_value = None
        service = _make_service(agent_repo=repo)

        with when("I authenticate with any key"), then("a PermissionError is raised"):
            assert_that(
                calling(service.authenticate).with_args(uuid4(), "some-key"),
                raises(PermissionError, "agent not found"),
            )


def test_authenticate_raises_when_agent_has_no_ingest_key():
    with given():
        agent = _make_agent(ingest_key_encrypted=None)
        repo = MagicMock()
        repo.get_by_id.return_value = agent
        service = _make_service(agent_repo=repo)

        with when("I authenticate"), then("a PermissionError is raised"):
            assert_that(
                calling(service.authenticate).with_args(agent.id, "some-key"),
                raises(PermissionError, "no ingest key"),
            )


@patch("api.domains.ingest.service.get_config")
@patch("api.domains.ingest.service.decrypt_token")
def test_authenticate_raises_on_wrong_key(mock_decrypt, mock_config):
    with given():
        agent = _make_agent()
        repo = MagicMock()
        repo.get_by_id.return_value = agent
        mock_config.return_value = MagicMock(agent_token_encryption_key="enc-key")
        mock_decrypt.return_value = "correct-key"
        service = _make_service(agent_repo=repo)

        with when("I authenticate with a wrong key"), then("a PermissionError is raised"):
            assert_that(
                calling(service.authenticate).with_args(agent.id, "wrong-key"),
                raises(PermissionError, "invalid ingest key"),
            )


@patch("api.domains.ingest.service.get_config")
@patch("api.domains.ingest.service.decrypt_token")
def test_authenticate_returns_agent_on_valid_key(mock_decrypt, mock_config):
    with given():
        agent = _make_agent()
        repo = MagicMock()
        repo.get_by_id.return_value = agent
        mock_config.return_value = MagicMock(agent_token_encryption_key="enc-key")
        mock_decrypt.return_value = "correct-key"
        service = _make_service(agent_repo=repo)

        with when("I authenticate with the correct key"):
            result = service.authenticate(agent.id, "correct-key")

        with then("the agent is returned"):
            assert_that(result.id, equal_to(agent.id))


# --- process ---


def test_process_empty_batch_does_nothing():
    with given():
        tc_repo = MagicMock()
        service = _make_service(tc_repo=tc_repo)
        agent = _make_agent()

        with when("I process an empty batch"):
            service.process(agent, IngestBatchRequest())

        with then("no repo methods are called"):
            tc_repo.get_session.assert_not_called()


def test_process_tool_calls_calls_upsert_pending():
    with given():
        tc_repo = MagicMock()
        session = MagicMock()
        tc_repo.get_session.return_value.__enter__ = MagicMock(return_value=session)
        tc_repo.get_session.return_value.__exit__ = MagicMock(return_value=False)
        service = _make_service(tc_repo=tc_repo)
        agent = _make_agent()
        now = datetime.now(UTC)
        batch = IngestBatchRequest(
            tool_calls=[
                IngestToolCallEvent(
                    external_id="tc-1",
                    session_id="session-abc",
                    tool_name="read",
                    arguments={"path": "/tmp/x"},
                    occurred_at=now,
                )
            ]
        )

        with when("I process the batch"):
            service.process(agent, batch)

        with then("upsert_pending is called"):
            tc_repo.upsert_pending.assert_called_once_with(
                session,
                agent.organization_id,
                agent.id,
                "session-abc",
                "tc-1",
                "read",
                {"path": "/tmp/x"},
                now,
            )


def test_process_tool_results_calls_complete():
    with given():
        tc_repo = MagicMock()
        session = MagicMock()
        tc_repo.get_session.return_value.__enter__ = MagicMock(return_value=session)
        tc_repo.get_session.return_value.__exit__ = MagicMock(return_value=False)
        tc_repo.complete.return_value = None
        service = _make_service(tc_repo=tc_repo)
        agent = _make_agent()
        now = datetime.now(UTC)
        batch = IngestBatchRequest(
            tool_results=[
                IngestToolResultEvent(
                    external_id="tc-1",
                    result="file contents",
                    is_error=False,
                    completed_at=now,
                )
            ]
        )

        with when("I process the batch"):
            service.process(agent, batch)

        with then("complete is called"):
            tc_repo.complete.assert_called_once_with(
                session,
                agent.id,
                "tc-1",
                "file contents",
                False,
                now,
            )
