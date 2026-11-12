"""Migration d1a390e7b2c4: workflow approval requests and the Awaiting Approval run state (AF-390)."""

from uuid import UUID

import pytest
from alembic import command
from hamcrest import assert_that, equal_to, is_
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.conftest import config
from api.tests.core.givenpy import given, then, when
from api.tests.integration.test_workflow_runs import _RUN_GIVEN, start

REVISION = "d1a390e7b2c4"
PREVIOUS = "a9d2e7c4b1f8"
TABLE = "workflow_approval_request"


def _engine(context):
    return context.injector.get(PostgresRepositoryDelegate).engine


def a_run(context) -> UUID:
    response, _, _ = start(context)
    assert_that(response.status_code, equal_to(202), response.text)
    return UUID(response.json()["id"])


def set_state(context, run_id: UUID, state: str) -> None:
    with _engine(context).begin() as connection:
        connection.execute(
            text("UPDATE workflow_run SET state = :state WHERE id = :id"), {"state": state, "id": run_id}
        )


def stored_run(context, run_id: UUID):
    with _engine(context).connect() as connection:
        return connection.execute(text("SELECT state, reason FROM workflow_run WHERE id = :id"), {"id": run_id}).one()


def has_table(context) -> bool:
    return inspect(_engine(context)).has_table(TABLE)


def test_upgrade_creates_the_request_table_and_allows_awaiting_approval() -> None:
    with given(_RUN_GIVEN) as context:
        run_id = a_run(context)
        command.downgrade(config, PREVIOUS)
        try:
            with then("the previous schema has no request table and rejects Awaiting Approval"):
                assert_that(has_table(context), is_(False))
                with pytest.raises(IntegrityError):
                    set_state(context, run_id, "AWAITING_APPROVAL")

            with when("the approval migration is applied"):
                command.upgrade(config, REVISION)

            with then("the request table exists and a run may await approval"):
                assert_that(has_table(context), is_(True))
                set_state(context, run_id, "AWAITING_APPROVAL")
                assert_that(stored_run(context, run_id).state, equal_to("AWAITING_APPROVAL"))
        finally:
            command.upgrade(config, "head")


def test_downgrade_blocks_runs_awaiting_approval_and_drops_the_request_table() -> None:
    with given(_RUN_GIVEN) as context:
        waiting = a_run(context)
        other = a_run(context)
        set_state(context, waiting, "AWAITING_APPROVAL")
        set_state(context, other, "RUNNING")
        try:
            with when("the approval migration is rolled back"):
                command.downgrade(config, PREVIOUS)

            with then("the request table is dropped"):
                assert_that(has_table(context), is_(False))

            with then("a run awaiting approval is blocked for a person, with the reason recorded"):
                assert_that(
                    tuple(stored_run(context, waiting)),
                    equal_to(("BLOCKED", "Awaiting approval; approval support was rolled back")),
                )

            with then("runs in other states are untouched"):
                assert_that(stored_run(context, other).state, equal_to("RUNNING"))
        finally:
            command.upgrade(config, "head")
