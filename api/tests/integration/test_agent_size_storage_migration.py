"""The migration that gives Agent Sizes their storage, run against a database of its own."""

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from hamcrest import assert_that, equal_to
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

PRE_MIGRATION_REVISION = "8b2e4f61c9d3"
STORAGE_REVISION = "20e7d399d7c9"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
_GIB = 1024**3


@pytest.fixture
def database_before_storage(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"agent_size_storage_{uuid7().hex}"
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


def test_every_existing_size_keeps_the_1gi_volume_agents_had(database_before_storage):
    database = database_before_storage
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO agent_sizes (id, created_at, updated_at, name, cpu_request_millicores,"
                " cpu_limit_millicores, memory_request_bytes, memory_limit_bytes, enabled, is_default, sort_order)"
                " VALUES (:id, now(), now(), 'Large', 500, 2000, 1, 1, true, false, 1)"
            ),
            {"id": uuid7()},
        )

    command.upgrade(database.config, STORAGE_REVISION)

    with database.engine.connect() as connection:
        rows = dict(connection.execute(text("SELECT name, storage_bytes FROM agent_sizes")).all())
    assert_that(rows, equal_to({"Standard": _GIB, "Large": _GIB}))


def test_a_size_must_name_a_positive_volume(database_before_storage):
    database = database_before_storage
    command.upgrade(database.config, STORAGE_REVISION)

    with pytest.raises(IntegrityError), database.engine.begin() as connection:
        connection.execute(text("UPDATE agent_sizes SET storage_bytes = 0"))


def test_the_migration_downgrades_cleanly(database_before_storage):
    database = database_before_storage
    command.upgrade(database.config, STORAGE_REVISION)

    command.downgrade(database.config, PRE_MIGRATION_REVISION)

    columns = {column["name"] for column in inspect(database.engine).get_columns("agent_sizes")}
    assert_that("storage_bytes" in columns, equal_to(False))
