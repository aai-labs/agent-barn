"""Migration b7e2c41d9a63: Approval step rounds, step results per round and the Rejected run state."""

from uuid import UUID

from alembic import command
from hamcrest import assert_that, equal_to, is_
from sqlalchemy import inspect, text

from api.domains.workflows.run_models import AttemptResult
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.conftest import config
from api.tests.core.givenpy import given, then, when
from api.tests.integration.test_workflow_approval_steps import DRAFT, REVIEW, _decide, _run, _waiting_run
from api.tests.integration.test_workflow_runs import _RUN_GIVEN, attempt

REVISION = "b7e2c41d9a63"
PREVIOUS = "0a07b0b57b62"


def _engine(context):
    return context.injector.get(PostgresRepositoryDelegate).engine


def _stored(context, run_id: str):
    with _engine(context).connect() as connection:
        return connection.execute(
            text("SELECT state, reason, settled_at IS NOT NULL FROM workflow_run WHERE id = :id"), {"id": run_id}
        ).one()


def _checkpoints(context, run_id: str) -> list:
    with _engine(context).connect() as connection:
        return [
            row[0]
            for row in connection.execute(
                text("SELECT result->>'summary' FROM workflow_checkpoint WHERE run_id = :id ORDER BY created_at"),
                {"id": run_id},
            )
        ]


def test_downgrade_settles_runs_the_older_api_cannot_represent_and_keeps_current_results() -> None:
    with given(_RUN_GIVEN) as context:
        waiting = _waiting_run(context, DRAFT, REVIEW)
        rejected = _waiting_run(context, DRAFT, REVIEW)
        _decide(context, rejected["id"], rejected["step_approval"]["id"], "reject")
        revised = _waiting_run(context, DRAFT, REVIEW)
        _decide(context, revised["id"], revised["step_approval"]["id"], "request_changes", "Shorter")
        repository, row, token = attempt(context, revised["id"])
        repository.complete(row.id, token, AttemptResult(summary="Second draft", criteria_met=True))
        try:
            with when("the Approval step migration is rolled back"):
                command.downgrade(config, PREVIOUS)

            with then("the round table is gone"):
                assert_that(inspect(_engine(context)).has_table("workflow_step_approval"), is_(False))

            with then("a run waiting at an Approval step is cancelled and settled, with the reason recorded"):
                assert_that(
                    tuple(_stored(context, waiting["id"])),
                    equal_to(("CANCELLED", "Waiting at an Approval step; approval step support was rolled back", True)),
                )

            with then("a rejected run becomes failed with its reason"):
                assert_that(_stored(context, rejected["id"])[:2], equal_to(("FAILED", "Rejected at step 2")))

            with then("only the current round of a step that ran again is kept"):
                assert_that(_checkpoints(context, revised["id"]), equal_to(["Second draft"]))
        finally:
            command.upgrade(config, "head")


def test_upgrade_numbers_existing_results_as_their_first_round() -> None:
    with given(_RUN_GIVEN) as context:
        run = _waiting_run(context, DRAFT, REVIEW)
        _decide(context, run["id"], run["step_approval"]["id"], "approve")
        try:
            command.downgrade(config, PREVIOUS)
            with when("the Approval step migration is applied"):
                command.upgrade(config, REVISION)

            with then("the earlier result is round 1 of its step and still current"):
                with _engine(context).connect() as connection:
                    rounds = connection.execute(
                        text("SELECT round, superseded_at FROM workflow_checkpoint WHERE run_id = :id"),
                        {"id": UUID(run["id"])},
                    ).all()
                assert_that([tuple(item) for item in rounds], equal_to([(1, None)]))
                assert_that(_run(context, run["id"])["state"], equal_to("SUCCEEDED"))
        finally:
            command.upgrade(config, "head")
