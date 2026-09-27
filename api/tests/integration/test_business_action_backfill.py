import json
from datetime import UTC, datetime, timedelta
from typing import Any

from hamcrest import assert_that, equal_to
from sqlmodel import col, select

from api.domains.business_value import catalogue
from api.domains.business_value.backfill import BackfillResult, run_backfill
from api.domains.business_value.catalogue import CatalogueEntry, CommandKind, OutcomeType
from api.domains.business_value.classifier import BusinessActionStatus
from api.domains.business_value.models import BusinessAction
from api.domains.business_value.repository import BusinessActionRepository
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
_ENVELOPE = (
    '{"code":"config_error","details":null,"message":"m","operation":"issues.get","service":"jira","status":null}'
)


def _hermes_result(exit_code: int, output: str = "{}") -> str:
    return json.dumps({"output": output, "exit_code": exit_code, "error": None})


def _seed(
    context, external_id: str, command: str, result: Any, *, tool_name: str = "terminal", complete: bool = True
) -> None:
    tool_calls: ToolCallRepository = context.injector.get(ToolCallRepository)
    occurred_at = datetime.now(UTC)
    with tool_calls.get_session() as session:
        tool_calls.upsert_pending(
            session,
            context.organization.id,
            context.agent.id,
            "session",
            external_id,
            tool_name,
            {"command": command},
            occurred_at,
        )
        if complete:
            tool_calls.complete(
                session, context.agent.id, external_id, result, False, occurred_at + timedelta(seconds=1)
            )
        session.commit()


def _backfill(context, batch_size: int = 2) -> BackfillResult:
    return run_backfill(context.injector.get(BusinessActionRepository), batch_size=batch_size)


def _actions(context) -> list[tuple[Any, ...]]:
    with context.injector.get(ToolCallRepository).get_session() as session:
        rows = session.exec(
            select(BusinessAction).order_by(col(BusinessAction.occurred_at), col(BusinessAction.ordinal))
        ).all()
        return [(row.integration, row.resource, row.verb, row.outcome_type, row.status) for row in rows]


def _seed_history(context) -> None:
    _seed(context, "call-1", "aai-cli excel workbook create f.xlsx", _hermes_result(0))
    _seed(context, "call-2", "aai-cli jira issues get A-1", _hermes_result(3, _ENVELOPE))
    _seed(context, "call-3", "aai-cli excel sheets list f.xlsx && aai-cli excel sheets add f.xlsx X", _hermes_result(0))
    _seed(context, "call-4", "ls -la", _hermes_result(0))
    _seed(context, "call-5", "aai-cli excel sheets add f.xlsx Y", None, complete=False)
    _seed(context, "call-6", "aai-cli excel sheets add f.xlsx Z", "contents", tool_name="read_file")


_EXPECTED_HISTORY = [
    ("excel", "workbook", "create", "DOCUMENT_AUTHORED", BusinessActionStatus.SUCCESS),
    ("jira", "issues", "get", None, BusinessActionStatus.ERROR),
    ("excel", "sheets", "list", None, BusinessActionStatus.SUCCESS),
    ("excel", "sheets", "add", "SPREADSHEET_UPDATED", BusinessActionStatus.SUCCESS),
]


def test_backfill_classifies_completed_shell_tool_calls_across_batches():
    with given([*_GIVEN]) as context:
        _seed_history(context)

        with when("the backfill runs with batches smaller than the history"):
            result = _backfill(context, batch_size=2)

        with then("every completed shell Tool Call is classified and nothing else is"):
            assert_that(_actions(context), equal_to(_EXPECTED_HISTORY))
            assert_that(result, equal_to(BackfillResult(scanned=4, recorded=4, failed=0)))


def test_backfill_infers_status_from_content_not_the_stored_tool_call_status():
    with given([*_GIVEN]) as context:
        with when("a Hermes Tool Call stored as SUCCESS exited non-zero"):
            _seed(context, "call-1", "aai-cli jira issues get A-1", _hermes_result(3, _ENVELOPE))
            _backfill(context)

        with then("its Business Action is an ERROR"):
            assert_that(_actions(context), equal_to([("jira", "issues", "get", None, BusinessActionStatus.ERROR)]))


def test_backfill_rerun_does_not_duplicate_actions():
    with given([*_GIVEN]) as context:
        _seed_history(context)

        with when("the backfill runs twice"):
            _backfill(context)
            _backfill(context)

        with then("each action is stored once"):
            assert_that(_actions(context), equal_to(_EXPECTED_HISTORY))


def test_backfill_remaps_history_after_a_catalogue_change_and_keeps_status(monkeypatch):
    with given([*_GIVEN]) as context:
        _seed(context, "call-1", "aai-cli excel workbook create f.xlsx", _hermes_result(0))
        _backfill(context)
        with context.injector.get(ToolCallRepository).get_session() as session:
            row = session.exec(select(BusinessAction)).one()
            row.status = BusinessActionStatus.UNKNOWN
            session.add(row)
            session.commit()

        with when("the catalogue re-maps the path and the backfill runs again"):
            monkeypatch.setitem(
                catalogue.CATALOGUE,
                ("excel", "workbook", "create"),
                CatalogueEntry(CommandKind.WRITE, OutcomeType.RECORD_CREATED),
            )
            _backfill(context)

        with then("the mapping changes and the stored status is left alone"):
            assert_that(
                _actions(context),
                equal_to([("excel", "workbook", "create", "RECORD_CREATED", BusinessActionStatus.UNKNOWN)]),
            )
