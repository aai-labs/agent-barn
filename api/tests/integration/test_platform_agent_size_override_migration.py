"""The migration that lets a Platform Administrator set one Agent's size, run against a database of its own."""

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from hamcrest import assert_that, equal_to, has_entries
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

PRE_MIGRATION_REVISION = "3046153d9447"
PLATFORM_OVERRIDE_REVISION = "8b2e4f61c9d3"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture
def database_before_platform_override(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"platform_agent_size_override_{uuid7().hex}"
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


def _override_column(engine) -> dict | None:
    return next(
        (column for column in inspect(engine).get_columns("agent") if column["name"] == "agent_size_set_by_platform"),
        None,
    )


def test_no_existing_agent_is_overridden(database_before_platform_override):
    database = database_before_platform_override

    command.upgrade(database.config, PLATFORM_OVERRIDE_REVISION)

    column = _override_column(database.engine)
    assert column is not None
    assert_that(column, has_entries(nullable=False))
    assert_that(str(column["default"]).lower(), equal_to("false"))


def test_the_migration_downgrades_cleanly(database_before_platform_override):
    database = database_before_platform_override
    command.upgrade(database.config, PLATFORM_OVERRIDE_REVISION)

    command.downgrade(database.config, PRE_MIGRATION_REVISION)

    assert_that(_override_column(database.engine), equal_to(None))
