import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from hamcrest import assert_that, empty, equal_to, has_length
from sqlmodel import col, select

from api.domains.business_value import repository as business_action_repository_module
from api.domains.business_value.catalogue import OutcomeType
from api.domains.business_value.classifier import BusinessActionStatus
from api.domains.business_value.models import BusinessAction
from api.domains.business_value.repository import BusinessActionRepository
from api.domains.tool_calls.models import ToolCall, ToolCallStatus
from api.domains.tool_calls.repository import ToolCallRepository
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    there_is_an_agent(),
]
_CHAIN = "aai-cli excel workbook create f.xlsx && aai-cli jira issues get A-1"
_HERMES_SUCCESS = json.dumps({"output": "{}", "exit_code": 0, "error": None})


def _record(context, external_id: str, command: str, result=_HERMES_SUCCESS) -> list[BusinessAction]:
    tool_calls: ToolCallRepository = context.injector.get(ToolCallRepository)
    business_actions: BusinessActionRepository = context.injector.get(BusinessActionRepository)
    occurred_at = datetime.now(UTC)
    with tool_calls.get_session() as session:
        tool_calls.upsert_pending(
            session,
            context.organization.id,
            context.agent.id,
            "session",
            external_id,
            "terminal",
            {"command": command},
            occurred_at,
        )
        completed = tool_calls.complete(
            session, context.agent.id, external_id, result, False, occurred_at + timedelta(seconds=1)
        )
        assert completed is not None
        inserted = business_actions.record_in_session(session, completed)
        session.commit()
        return inserted


def _session(context):
    return context.injector.get(ToolCallRepository).get_session()


def _stored_actions(context) -> list[BusinessAction]:
    with _session(context) as session:
        return list(session.exec(select(BusinessAction).order_by(col(BusinessAction.ordinal))).all())


def _stored_tool_call(context, external_id: str) -> ToolCall:
    with _session(context) as session:
        return session.exec(select(ToolCall).where(col(ToolCall.external_id) == external_id)).one()


def test_record_in_session_persists_one_row_per_classified_action():
    with given([*_GIVEN]) as context:
        with when("a completed Tool Call with two aai-cli invocations is recorded"):
            inserted = _record(context, "call-1", _CHAIN)

        with then("both actions are stored with the Tool Call's tenancy and timing"):
            tool_call = _stored_tool_call(context, "call-1")
            stored = _stored_actions(context)
            assert_that(inserted, has_length(2))
            assert_that(stored, has_length(2))
            first, second = stored
            assert_that(
                (first.ordinal, first.integration, first.resource, first.verb, first.is_write, first.outcome_type),
                equal_to((0, "excel", "workbook", "create", True, OutcomeType.DOCUMENT_AUTHORED.value)),
            )
            assert_that(
                (second.ordinal, second.integration, second.resource, second.verb, second.is_write),
                equal_to((1, "jira", "issues", "get", False)),
            )
            assert_that(second.outcome_type, equal_to(None))
            for action in stored:
                assert_that(action.status, equal_to(BusinessActionStatus.SUCCESS))
                assert_that(action.organization_id, equal_to(context.organization.id))
                assert_that(action.agent_id, equal_to(context.agent.id))
                assert_that(action.tool_call_id, equal_to(tool_call.id))
                assert_that(action.occurred_at, equal_to(tool_call.occurred_at))
                assert_that(action.completed_at, equal_to(tool_call.completed_at))


def test_record_in_session_skips_tool_calls_without_business_actions():
    with given([*_GIVEN]) as context:
        with when("a non-aai-cli command is recorded"):
            inserted = _record(context, "call-1", "ls -la")

        with then("nothing is stored"):
            assert_that(inserted, empty())
            assert_that(_stored_actions(context), empty())


def test_record_in_session_ignores_a_duplicate_result():
    with given([*_GIVEN]) as context:
        with when("the same Tool Call result is recorded twice"):
            _record(context, "call-1", _CHAIN)
            duplicate = _record(context, "call-1", _CHAIN)

        with then("the second recording inserts nothing"):
            assert_that(duplicate, empty())
            assert_that(_stored_actions(context), has_length(2))


def test_database_error_rolls_back_only_the_business_action_savepoint():
    with given([*_GIVEN]) as context:
        tool_calls: ToolCallRepository = context.injector.get(ToolCallRepository)
        business_actions: BusinessActionRepository = context.injector.get(BusinessActionRepository)
        now = datetime.now(UTC)
        missing_tool_call = ToolCall(
            id=uuid.uuid7(),
            organization_id=context.organization.id,
            agent_id=context.agent.id,
            session_id="session",
            external_id="never-stored",
            tool_name="terminal",
            arguments={"command": "aai-cli excel sheets list f.xlsx"},
            result=_HERMES_SUCCESS,
            status=ToolCallStatus.SUCCESS,
            occurred_at=now,
            completed_at=now,
        )

        with when("recording violates a foreign key inside the Ingest transaction"):
            with tool_calls.get_session() as session:
                tool_calls.upsert_pending(
                    session,
                    context.organization.id,
                    context.agent.id,
                    "session",
                    "call-1",
                    "terminal",
                    {"command": "ls"},
                    now,
                )
                inserted = business_actions.record_in_session(session, missing_tool_call)
                session.commit()

        with then("the Tool Call batch still commits and no action is stored"):
            assert_that(inserted, empty())
            assert_that(_stored_tool_call(context, "call-1").external_id, equal_to("call-1"))
            assert_that(_stored_actions(context), empty())


def test_classification_error_is_logged_and_skipped(monkeypatch, caplog):
    def fail(_tool_call):
        raise RuntimeError("boom")

    monkeypatch.setattr(business_action_repository_module, "classify", fail)

    with given([*_GIVEN]) as context:
        with when("the classifier raises"):
            with caplog.at_level(logging.ERROR, logger=business_action_repository_module.__name__):
                inserted = _record(context, "call-1", _CHAIN)

        with then("the Tool Call is stored, no action is stored, and the failure is logged"):
            assert_that(inserted, empty())
            assert_that(_stored_tool_call(context, "call-1").status, equal_to(ToolCallStatus.SUCCESS))
            assert_that(_stored_actions(context), empty())
            assert_that(any("classify" in record.getMessage() for record in caplog.records), equal_to(True))


def test_business_actions_are_deleted_with_their_tool_call():
    with given([*_GIVEN]) as context:
        _record(context, "call-1", _CHAIN)

        with when("the Tool Call is deleted"):
            with _session(context) as session:
                session.delete(session.exec(select(ToolCall).where(col(ToolCall.external_id) == "call-1")).one())
                session.commit()

        with then("its Business Actions cascade"):
            assert_that(_stored_actions(context), empty())
