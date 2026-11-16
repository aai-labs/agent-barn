"""Migration f3a393c5d1e2: where a workflow approval was decided, and by which Slack user (AF-393)."""

from datetime import UTC, datetime, timedelta

from alembic import command
from hamcrest import assert_that, equal_to, has_item, is_not
from sqlalchemy import inspect, text

from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.conftest import config
from api.tests.core.givenpy import given, then, when
from api.tests.integration.test_workflow_approvals import _raise, _started
from api.tests.integration.test_workflow_runs import _RUN_GIVEN

REVISION = "f3a393c5d1e2"
PREVIOUS = "e4b439a1c7d2"
TABLE = "workflow_approval_request"


def _engine(context):
    return context.injector.get(PostgresRepositoryDelegate).engine


def _columns(context) -> set[str]:
    return {column["name"] for column in inspect(_engine(context)).get_columns(TABLE)}


def test_upgrade_records_existing_decisions_as_web_and_downgrade_drops_the_columns() -> None:
    with given(_RUN_GIVEN) as context:
        _repository, row, token = _started(context)
        decided = _raise(context, row, token)
        # A decision made before the migration; one request per attempt may be live at a time.
        with _engine(context).begin() as connection:
            connection.execute(
                text("UPDATE workflow_approval_request SET state = 'DECLINED', decided_at = :at WHERE id = :id"),
                {"at": datetime.now(UTC) - timedelta(minutes=1), "id": decided},
            )
        open_ = _raise(context, row, token, command="ls")
        command.downgrade(config, PREVIOUS)
        try:
            with when("the migration is applied"):
                command.upgrade(config, REVISION)

            with then("it was decided on the web, and an undecided request has no source"):
                with _engine(context).connect() as connection:
                    sources = {
                        str(request_id): source
                        for request_id, source in connection.execute(
                            text("SELECT id, decision_source FROM workflow_approval_request")
                        ).all()
                    }
                assert_that((sources[decided], sources[open_]), equal_to(("web", None)))

            with when("the migration is rolled back"):
                command.downgrade(config, PREVIOUS)

            with then("the audit columns are gone"):
                assert_that(_columns(context), is_not(has_item("decision_source")))
                assert_that(_columns(context), is_not(has_item("decided_by_slack_handle")))
        finally:
            command.upgrade(config, "head")
