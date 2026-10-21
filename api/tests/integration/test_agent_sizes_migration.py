"""The migration that creates the Agent Size catalog, run against a database of its own."""

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

PRE_MIGRATION_REVISION = "a4e9c2d7b615"
AGENT_SIZES_REVISION = "dd9ef852a427"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
_MIB = 1024**2
_GIB = 1024**3


@pytest.fixture
def database_before_agent_sizes(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"agent_sizes_{uuid7().hex}"
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


def _insert(connection, name: str, *, is_default: bool = False, enabled: bool = True, request: int = 1, limit: int = 2):
    connection.execute(
        text(
            "INSERT INTO agent_sizes (id, created_at, updated_at, name, cpu_request_millicores,"
            " cpu_limit_millicores, memory_request_bytes, memory_limit_bytes, enabled, is_default, sort_order)"
            " VALUES (:id, now(), now(), :name, :request, :limit, 1, 1, :enabled, :is_default, 0)"
        ),
        {"id": uuid7(), "name": name, "request": request, "limit": limit, "enabled": enabled, "is_default": is_default},
    )


def test_the_migration_seeds_standard_as_the_only_default_with_todays_values(database_before_agent_sizes):
    database = database_before_agent_sizes

    command.upgrade(database.config, AGENT_SIZES_REVISION)

    with database.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT name, cpu_request_millicores, cpu_limit_millicores, memory_request_bytes,"
                " memory_limit_bytes, enabled, is_default FROM agent_sizes"
            )
        ).all()
    assert_that([tuple(row) for row in rows], equal_to([("Standard", 50, 500, 320 * _MIB, 1 * _GIB, True, True)]))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"is_default": True},  # a second default
        {"is_default": True, "enabled": False},  # a disabled default
        {"request": 3, "limit": 2},  # a request above its limit
        {"request": 0, "limit": 2},  # a request of nothing
    ],
)
def test_the_database_refuses_a_catalog_that_could_not_run(database_before_agent_sizes, kwargs):
    database = database_before_agent_sizes
    command.upgrade(database.config, AGENT_SIZES_REVISION)

    with pytest.raises(IntegrityError), database.engine.begin() as connection:
        _insert(connection, "Bad", **kwargs)


def test_the_migration_downgrades_cleanly(database_before_agent_sizes):
    database = database_before_agent_sizes
    command.upgrade(database.config, AGENT_SIZES_REVISION)

    command.downgrade(database.config, PRE_MIGRATION_REVISION)

    assert_that(inspect(database.engine).has_table("agent_sizes"), equal_to(False))
