"""AF-374 migration: agentbarn_telegram_link.first_message_at. Links that existed before it
count as already messaged, so their next message is not reported as a first one."""

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from hamcrest import assert_that, equal_to
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlmodel import SQLModel

import api.domains.communications.models  # noqa: F401
from api.core.config import get_config

PREVIOUS_REVISION = "b3d8e1f4a6c2"
REVISION = "a78bcde4b918"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
CREATED_AT = datetime(2026, 10, 7, 9, 30, tzinfo=UTC)


@pytest.fixture
def database(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"af374_first_message_{uuid7().hex}"
    admin_engine = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    target_url = source_url.set(database=database_name)
    monkeypatch.setenv("ALEMBIC_DB_URL", target_url.render_as_string(False))
    config = Config(ALEMBIC_INI)
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(target_url)
    try:
        yield config, engine
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": database_name},
            )
            connection.execute(text(f'DROP DATABASE "{database_name}"'))
        admin_engine.dispose()


def _columns(engine) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("agentbarn_telegram_link")}


def _existing_link(engine):
    link_id = uuid7()
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text(
                "INSERT INTO agentbarn_telegram_link (id, created_at, updated_at, organization_id, agent_id, "
                "connection_id, linked_by_membership_id, telegram_user_id) "
                "VALUES (:id, :created_at, :created_at, :org, :agent, :connection, :membership, 5550001)"
            ),
            {
                "id": link_id,
                "created_at": CREATED_AT,
                "org": uuid7(),
                "agent": uuid7(),
                "connection": uuid7(),
                "membership": uuid7(),
            },
        )
    return link_id


def test_existing_links_count_as_already_messaged(database):
    config, engine = database
    link_id = _existing_link(engine)

    command.upgrade(config, REVISION)
    engine.dispose()

    with engine.connect() as connection:
        first_message_at = connection.execute(
            text("SELECT first_message_at FROM agentbarn_telegram_link WHERE id = :id"), {"id": link_id}
        ).scalar_one()
    assert_that(first_message_at, equal_to(CREATED_AT))


def test_upgrade_adds_the_column_and_downgrade_removes_it(database):
    config, engine = database

    command.upgrade(config, REVISION)
    engine.dispose()
    added = "first_message_at" in _columns(engine)
    command.downgrade(config, PREVIOUS_REVISION)
    engine.dispose()

    assert_that((added, "first_message_at" in _columns(engine)), equal_to((True, False)))


def test_the_migrated_schema_matches_the_model():
    engine = create_engine(str(get_config().db_connection_url))
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), SQLModel.metadata)

    assert_that([diff for diff in differences if "first_message_at" in repr(diff)], equal_to([]))
