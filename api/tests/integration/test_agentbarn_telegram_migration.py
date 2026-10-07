"""AF-367 migrations: they downgrade cleanly to before Agent Barn Telegram, upgrade again,
and leave a schema that matches the models."""

import os
from pathlib import Path
from types import SimpleNamespace
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

# Every model module must be imported for the metadata comparison to see its tables.
import api.domains.communications.models  # noqa: F401
from api.core.config import get_config

PRE_AF367_REVISION = "69011ec264e7"
AF367_HEAD = "fcdc690dbf31"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
AF367_TABLES = (
    "agentbarn_telegram_link",
    "agentbarn_telegram_link_token",
    "agentbarn_telegram_ingress_lease",
    "agentbarn_telegram_update",
)


@pytest.fixture
def scratch_database(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"af367_{uuid7().hex}"
    target_url = source_url.set(database=database_name)
    admin_engine = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    monkeypatch.setenv("ALEMBIC_DB_URL", target_url.render_as_string(False))
    engine = create_engine(target_url)
    try:
        yield SimpleNamespace(config=Config(ALEMBIC_INI), engine=engine)
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    f"WHERE datname = '{database_name}' AND pid <> pg_backend_pid()"
                )
            )
            connection.execute(text(f'DROP DATABASE "{database_name}"'))
        admin_engine.dispose()


def _af367_objects(engine) -> tuple[set[str], bool]:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names()) & set(AF367_TABLES)
    index = any(
        index["name"] == "uq_communication_connection_active_telegram"
        for index in inspector.get_indexes("communication_connection")
    )
    return tables, index


def test_agentbarn_telegram_downgrades_cleanly_and_upgrades_again(scratch_database):
    command.upgrade(scratch_database.config, AF367_HEAD)
    assert_that(_af367_objects(scratch_database.engine), equal_to((set(AF367_TABLES), True)))

    command.downgrade(scratch_database.config, PRE_AF367_REVISION)
    scratch_database.engine.dispose()
    tables, index = _af367_objects(scratch_database.engine)
    assert_that((tables, index), equal_to((set(), False)))
    with scratch_database.engine.connect() as connection:
        enum_left = connection.execute(
            text("SELECT 1 FROM pg_type WHERE typname = 'agentbarntelegramupdatestatus'")
        ).first()
    assert_that(enum_left, equal_to(None))

    command.upgrade(scratch_database.config, AF367_HEAD)
    scratch_database.engine.dispose()
    assert_that(_af367_objects(scratch_database.engine), equal_to((set(AF367_TABLES), True)))


def test_the_migrated_schema_matches_the_models_for_agentbarn_telegram():
    engine = create_engine(str(get_config().db_connection_url))
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), SQLModel.metadata)
    ours = [diff for diff in differences if "agentbarn" in repr(diff) or "active_telegram" in repr(diff)]

    assert_that(ours, equal_to([]))
    assert set(AF367_TABLES) <= set(inspect(engine).get_table_names())
