"""Migration cb14de9a231b: a workflow's approval request recipient and each request's Slack message."""

from uuid import UUID

import pytest
from alembic import command
from hamcrest import assert_that, equal_to, is_
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.conftest import config
from api.tests.core.givenpy import given, then, when
from api.tests.integration.test_workflows import _GIVEN, create

REVISION = "cb14de9a231b"
PREVIOUS = "463f987cd60d"


def _engine(context):
    return context.injector.get(PostgresRepositoryDelegate).engine


def notice_columns(context) -> set[str]:
    return {column["name"] for column in inspect(_engine(context)).get_columns("workflow")} & {
        "approval_notice_enabled",
        "approval_notice_platform",
        "approval_notice_user_id",
        "approval_notice_user_name",
        "approval_notice_team_id",
    }


def stored_enabled(context, workflow_id: UUID) -> bool:
    with _engine(context).connect() as connection:
        return connection.execute(
            text("SELECT approval_notice_enabled FROM workflow WHERE id = :id"), {"id": workflow_id}
        ).scalar_one()


def turn_on(context, workflow_id: UUID, **values) -> None:
    columns = ", ".join(f"approval_notice_{name} = :{name}" for name in values)
    with _engine(context).begin() as connection:
        connection.execute(
            text(f"UPDATE workflow SET approval_notice_enabled = true, {columns} WHERE id = :id"),
            {"id": workflow_id, **values},
        )


def test_upgrade_leaves_existing_workflows_sending_nothing() -> None:
    with given(_GIVEN) as context:
        workflow_id = UUID(create(context)["id"])
        command.downgrade(config, PREVIOUS)
        try:
            with then("the previous schema has neither the setting nor the message table"):
                assert_that(notice_columns(context), equal_to(set()))
                assert_that(inspect(_engine(context)).has_table("workflow_approval_notice"), is_(False))

            with when("the migration is applied"):
                command.upgrade(config, REVISION)

            with then("an existing workflow does not send approval requests"):
                assert_that(stored_enabled(context, workflow_id), is_(False))
                assert_that(inspect(_engine(context)).has_table("workflow_approval_notice"), is_(True))
        finally:
            command.upgrade(config, "head")


def test_the_database_refuses_a_workflow_sending_to_nobody() -> None:
    with given(_GIVEN) as context:
        workflow_id = UUID(create(context)["id"])
        with pytest.raises(IntegrityError):
            turn_on(context, workflow_id, platform="slack", team_id="T0APPROVE")


def test_downgrade_drops_the_setting_and_the_messages() -> None:
    with given(_GIVEN) as context:
        workflow_id = UUID(create(context)["id"])
        turn_on(context, workflow_id, platform="slack", user_id="U0DECIDER", team_id="T0APPROVE")
        try:
            with when("the migration is rolled back"):
                command.downgrade(config, PREVIOUS)

            with then("the columns and table are gone and the workflow remains"):
                assert_that(notice_columns(context), equal_to(set()))
                assert_that(inspect(_engine(context)).has_table("workflow_approval_notice"), is_(False))
                with _engine(context).connect() as connection:
                    assert_that(
                        connection.execute(
                            text("SELECT count(*) FROM workflow WHERE id = :id"), {"id": workflow_id}
                        ).scalar_one(),
                        equal_to(1),
                    )
        finally:
            command.upgrade(config, "head")
