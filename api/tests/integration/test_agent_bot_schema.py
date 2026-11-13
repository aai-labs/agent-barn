from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from hamcrest import assert_that, equal_to, has_length
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel

from api.domains.agents.models import AgentType
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector
from api.tests.integration.test_rbac_schema import isolated_database  # noqa: F401
from api.tests.steps.agent import there_is_an_agent
from api.tests.steps.database import database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization

PREVIOUS_HEAD = "3680352c132d"
BOT_COLUMNS = {"parent_agent_id", "bot_slot"}
BOT_CONSTRAINTS = {"fk_agent_parent_agent", "uq_agent_live_bot_slot"}

_GIVEN = [
    prepare_injector(),
    database_repo_is_ready(),
    there_is_an_organization(),
    there_is_an_agent(name="Parent", agent_type=AgentType.HERMES),
]


def _execute(context, sql, **params):
    with context.postgres_delegate.engine.begin() as connection:
        return connection.execute(text(sql), params)


def _insert_bot(context, parent_id, slot, *, source_id=None, agent_type="hermes"):
    bot_id = uuid7()
    with context.postgres_delegate.engine.begin() as connection:
        columns = [
            row[0]
            for row in connection.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'agent'")
            )
        ]
        overrides = {
            "id": ":bot_id",
            "name": "'Bot'",
            "parent_agent_id": ":parent_id",
            "bot_slot": ":slot",
            "agent_type": ":agent_type",
            "memory_key_hash": "NULL",
            "deleted_at": "NULL",
        }
        copied = [column for column in columns if column not in overrides]
        targets = ", ".join([*copied, *overrides])
        selected = ", ".join([*copied, *overrides.values()])
        connection.execute(
            text(f"INSERT INTO agent ({targets}) SELECT {selected} FROM agent WHERE id = :source_id"),
            {
                "bot_id": bot_id,
                "parent_id": parent_id,
                "slot": slot,
                "agent_type": agent_type,
                "source_id": source_id or parent_id,
            },
        )
    return bot_id


def _exists(context, agent_id):
    return _execute(context, "SELECT count(*) FROM agent WHERE id = :id", id=agent_id).scalar_one() == 1


def test_a_hermes_agent_can_hold_a_hermes_bot():
    with given(_GIVEN) as context:
        bot_id = _insert_bot(context, context.agent.id, 1)

        row = _execute(context, "SELECT parent_agent_id, bot_slot FROM agent WHERE id = :id", id=bot_id).one()

        assert_that((row.parent_agent_id, row.bot_slot), equal_to((context.agent.id, 1)))


def test_an_agent_without_a_parent_has_no_slot():
    with given(_GIVEN) as context:
        row = _execute(context, "SELECT parent_agent_id, bot_slot FROM agent WHERE id = :id", id=context.agent.id).one()

        assert_that((row.parent_agent_id, row.bot_slot), equal_to((None, None)))


def test_a_bot_needs_a_slot():
    with given(_GIVEN) as context:
        with pytest.raises(IntegrityError):
            _insert_bot(context, context.agent.id, None)


def test_an_agent_without_a_parent_cannot_take_a_slot():
    with given(_GIVEN) as context:
        with pytest.raises(IntegrityError):
            _execute(context, "UPDATE agent SET bot_slot = 1 WHERE id = :id", id=context.agent.id)


@pytest.mark.parametrize("slot", [0, 6])
def test_a_slot_outside_one_to_five_is_refused(slot):
    with given(_GIVEN) as context:
        with pytest.raises(IntegrityError):
            _insert_bot(context, context.agent.id, slot)


def test_two_live_bots_cannot_share_a_slot():
    with given(_GIVEN) as context:
        _insert_bot(context, context.agent.id, 1)

        with pytest.raises(IntegrityError):
            _insert_bot(context, context.agent.id, 1)


def test_a_parent_holds_at_most_five_live_bots():
    with given(_GIVEN) as context:
        for slot in range(1, 6):
            _insert_bot(context, context.agent.id, slot)

        with pytest.raises(IntegrityError):
            _insert_bot(context, context.agent.id, 6)


def test_a_deleted_bot_frees_its_slot():
    with given(_GIVEN) as context:
        first = _insert_bot(context, context.agent.id, 1)
        _execute(context, "UPDATE agent SET deleted_at = :now WHERE id = :id", now=datetime.now(UTC), id=first)

        second = _insert_bot(context, context.agent.id, 1)

        assert_that(_exists(context, second), equal_to(True))


def test_a_bot_cannot_hold_bots():
    with given(_GIVEN) as context:
        bot_id = _insert_bot(context, context.agent.id, 1)

        with pytest.raises(IntegrityError, match="Bot"):
            _insert_bot(context, bot_id, 1, source_id=context.agent.id)


def test_an_agent_cannot_be_its_own_parent():
    with given(_GIVEN) as context:
        with pytest.raises(IntegrityError):
            _execute(
                context,
                "UPDATE agent SET parent_agent_id = id, bot_slot = 1 WHERE id = :id",
                id=context.agent.id,
            )


def test_an_openclaw_agent_cannot_hold_bots():
    with given(_GIVEN) as context:
        there_is_an_agent(name="OpenClaw parent", agent_type=AgentType.OPENCLAW)(context)

        with pytest.raises(IntegrityError, match="Hermes"):
            _insert_bot(context, context.agent.id, 1)


def test_a_bot_must_be_hermes():
    with given(_GIVEN) as context:
        with pytest.raises(IntegrityError, match="Hermes"):
            _insert_bot(context, context.agent.id, 1, agent_type="openclaw")


def test_a_bot_must_be_in_its_parents_organization():
    with given(_GIVEN) as context:
        parent_id = context.agent.id
        there_is_an_organization(name="Other Organization")(context)
        there_is_an_agent(name="Other", agent_type=AgentType.HERMES)(context)

        with pytest.raises(IntegrityError):
            _insert_bot(context, parent_id, 1, source_id=context.agent.id)


def test_the_parent_link_cannot_be_added_later():
    with given(_GIVEN) as context:
        parent_id = context.agent.id
        there_is_an_agent(name="Standalone", agent_type=AgentType.HERMES)(context)

        with pytest.raises(IntegrityError, match="parent"):
            _execute(
                context,
                "UPDATE agent SET parent_agent_id = :parent_id, bot_slot = 1 WHERE id = :id",
                parent_id=parent_id,
                id=context.agent.id,
            )


def test_the_parent_link_cannot_be_removed():
    with given(_GIVEN) as context:
        bot_id = _insert_bot(context, context.agent.id, 1)

        with pytest.raises(IntegrityError, match="parent"):
            _execute(context, "UPDATE agent SET parent_agent_id = NULL, bot_slot = NULL WHERE id = :id", id=bot_id)


def test_deleting_a_parent_row_deletes_its_bots():
    with given(_GIVEN) as context:
        bot_id = _insert_bot(context, context.agent.id, 1)

        _execute(context, "DELETE FROM agent WHERE id = :id", id=context.agent.id)

        assert_that(_exists(context, bot_id), equal_to(False))


def test_deleting_an_organization_with_bots_succeeds():
    with given(_GIVEN) as context:
        bot_id = _insert_bot(context, context.agent.id, 1)

        _execute(context, "DELETE FROM organization WHERE id = :id", id=context.organization.id)

        assert_that(_exists(context, bot_id), equal_to(False))
        assert_that(_exists(context, context.agent.id), equal_to(False))


def test_the_migration_matches_the_models_and_downgrades_cleanly(isolated_database):  # noqa: F811
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(isolated_database)
    try:
        assert_that(BOT_COLUMNS <= {c["name"] for c in inspect(engine).get_columns("agent")}, equal_to(True))

        def only_agent(object_, name, type_, reflected, compare_to):
            if type_ == "table":
                return name == "agent"
            if type_ == "column":
                return name in BOT_COLUMNS
            return name in BOT_CONSTRAINTS

        with engine.connect() as connection:
            drift = compare_metadata(
                MigrationContext.configure(connection, opts={"include_object": only_agent, "compare_type": True}),
                SQLModel.metadata,
            )
            trigger = connection.execute(
                text("SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_agent_bot_parent'")
            ).scalar_one()
        database_wide_enums = "change_enum_variants"
        assert_that([diff for diff in drift if diff[0] != database_wide_enums], has_length(0))
        assert_that(trigger, equal_to(1))

        command.downgrade(config, PREVIOUS_HEAD)
        assert_that(BOT_COLUMNS & {c["name"] for c in inspect(engine).get_columns("agent")}, equal_to(set()))
        with engine.connect() as connection:
            remaining = connection.execute(
                text("SELECT count(*) FROM pg_proc WHERE proname = 'validate_agent_bot_parent'")
            ).scalar_one()
        assert_that(remaining, equal_to(0))

        command.upgrade(config, "head")
        assert_that(BOT_COLUMNS <= {c["name"] for c in inspect(engine).get_columns("agent")}, equal_to(True))
    finally:
        engine.dispose()
