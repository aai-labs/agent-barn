"""The migration that lets Organizations choose an Agent Size, run against a database of its own."""

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from hamcrest import assert_that, contains_inanyorder, equal_to, has_entries
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

PRE_MIGRATION_REVISION = "dd9ef852a427"
ORGANIZATION_AGENT_SIZES_REVISION = "3046153d9447"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture
def database_before_organization_agent_sizes(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"organization_agent_sizes_{uuid7().hex}"
    admin_engine = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))

    target_url = source_url.set(database=database_name)
    monkeypatch.setenv("ALEMBIC_DB_URL", target_url.render_as_string(False))
    config = Config(ALEMBIC_INI)
    command.upgrade(config, PRE_MIGRATION_REVISION)
    engine = create_engine(target_url)
    try:
        yield SimpleNamespace(config=config, engine=engine)
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                    " WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f'DROP DATABASE "{database_name}"'))
        admin_engine.dispose()


def _agent_size_columns(engine) -> dict[str, dict]:
    return {
        column["name"]: column
        for column in inspect(engine).get_columns("agent")
        if column["name"] in {"agent_size_id", "running_resources"}
    }


def _permission_count(engine) -> int:
    with engine.connect() as connection:
        return connection.execute(text("SELECT count(*) FROM permissions WHERE key = 'agent.size.manage'")).scalar_one()


def test_existing_agents_follow_the_default_and_the_permission_exists(database_before_organization_agent_sizes):
    database = database_before_organization_agent_sizes

    command.upgrade(database.config, ORGANIZATION_AGENT_SIZES_REVISION)

    columns = _agent_size_columns(database.engine)
    assert_that(list(columns), contains_inanyorder("agent_size_id", "running_resources"))
    assert_that(columns["agent_size_id"], has_entries(nullable=True))
    assert_that(columns["running_resources"], has_entries(nullable=True))
    foreign_keys = {fk["name"]: fk for fk in inspect(database.engine).get_foreign_keys("agent")}
    assert_that(
        foreign_keys["agent_agent_size_id_fkey"],
        has_entries(referred_table="agent_sizes", options=has_entries(ondelete="RESTRICT")),
    )
    assert_that(inspect(database.engine).has_table("organization_agent_sizes"), equal_to(True))
    assert_that(_permission_count(database.engine), equal_to(1))


def test_the_migration_downgrades_cleanly(database_before_organization_agent_sizes):
    database = database_before_organization_agent_sizes
    command.upgrade(database.config, ORGANIZATION_AGENT_SIZES_REVISION)

    command.downgrade(database.config, PRE_MIGRATION_REVISION)

    assert_that(inspect(database.engine).has_table("organization_agent_sizes"), equal_to(False))
    assert_that(_agent_size_columns(database.engine), equal_to({}))
    assert_that(_permission_count(database.engine), equal_to(0))
