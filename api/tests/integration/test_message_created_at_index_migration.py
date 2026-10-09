"""AF-357 migration: hourly message counts read agent_chat_message by created_at."""

import os
from pathlib import Path
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from hamcrest import assert_that, equal_to
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

PREVIOUS_REVISION = "5a1e7c3b9d20"
REVISION = "6c3f9a2e8b41"
INDEX = "ix_agent_chat_message_created_at"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture
def database(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"af357_idx_{uuid7().hex}"
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


def _index_count(engine) -> int:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT count(*) FROM pg_indexes WHERE indexname = :name"), {"name": INDEX}
        ).scalar_one()


def test_upgrade_adds_the_created_at_index_and_downgrade_removes_it(database):
    config, engine = database

    command.upgrade(config, REVISION)
    added = _index_count(engine)
    command.downgrade(config, PREVIOUS_REVISION)

    assert_that((added, _index_count(engine)), equal_to((1, 0)))
