"""The migration that adds Organization MCP Servers, run against a database of its own."""

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid7

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from hamcrest import assert_that, empty, equal_to
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlmodel import SQLModel

import api.domains.mcp_servers.models  # noqa: F401 - registers the tables on SQLModel.metadata

PRE_MIGRATION_REVISION = "3f9f88255e3b"
MCP_SERVERS_REVISION = "d3a8b61f4c20"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
_TABLES = {
    "organization_mcp_server",
    "agent_mcp_server_attachment",
    "agent_mcp_gateway_token",
    "mcp_server_credential",
}


@pytest.fixture
def database_before_mcp_servers(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"mcp_servers_{uuid7().hex}"
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


def _permission_keys(engine) -> list[str]:
    with engine.connect() as connection:
        return list(connection.execute(text("SELECT key FROM permissions WHERE key = 'mcp_server.manage'")).scalars())


def test_the_migration_creates_tables_matching_the_models_and_the_permission(database_before_mcp_servers):
    database = database_before_mcp_servers

    command.upgrade(database.config, MCP_SERVERS_REVISION)

    with database.engine.connect() as connection:
        diffs = compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), SQLModel.metadata)
    ours = [diff for diff in diffs if _touches(diff, _TABLES)]
    assert_that(ours, empty())
    assert_that(_permission_keys(database.engine), equal_to(["mcp_server.manage"]))


def test_downgrading_removes_the_tables_and_the_permission(database_before_mcp_servers):
    database = database_before_mcp_servers
    command.upgrade(database.config, MCP_SERVERS_REVISION)

    command.downgrade(database.config, PRE_MIGRATION_REVISION)

    assert_that(_TABLES & set(inspect(database.engine).get_table_names()), empty())
    assert_that(_permission_keys(database.engine), empty())


def _touches(diff, tables: set[str]) -> bool:
    """Whether one autogenerate difference concerns any of `tables`."""
    if isinstance(diff, list):
        return any(_touches(item, tables) for item in diff)
    for part in diff[1:]:
        name = getattr(part, "name", None) if not isinstance(part, str) else part
        table = getattr(part, "table", None)
        if name in tables or getattr(table, "name", None) in tables:
            return True
    return False
