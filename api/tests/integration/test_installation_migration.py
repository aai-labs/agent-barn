"""AF-357 migration: every database identifies its Installation with exactly one generated id."""

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid7

import pytest
from alembic import command
from alembic.config import Config
from hamcrest import assert_that, equal_to, instance_of
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

PRE_AF357_REVISION = "c055b65baf67"
AF357_REVISION = "5a1e7c3b9d20"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture
def pre_af357_database(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"af357_{uuid7().hex}"
    target_url = source_url.set(database=database_name)
    admin_engine = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))

    monkeypatch.setenv("ALEMBIC_DB_URL", target_url.render_as_string(False))
    config = Config(ALEMBIC_INI)
    command.upgrade(config, PRE_AF357_REVISION)
    engine = create_engine(target_url)
    try:
        yield SimpleNamespace(config=config, engine=engine)
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f'DROP DATABASE "{database_name}"'))
        admin_engine.dispose()


def installation_ids(engine) -> list[UUID]:
    with engine.connect() as connection:
        return list(connection.execute(text("SELECT id FROM installation")).scalars())


def test_upgrade_creates_exactly_one_installation(pre_af357_database):
    command.upgrade(pre_af357_database.config, AF357_REVISION)

    ids = installation_ids(pre_af357_database.engine)

    assert_that(len(ids), equal_to(1))
    assert_that(ids[0], instance_of(UUID))


def test_downgrade_removes_the_installation_table(pre_af357_database):
    command.upgrade(pre_af357_database.config, AF357_REVISION)
    command.downgrade(pre_af357_database.config, PRE_AF357_REVISION)

    with pre_af357_database.engine.connect() as connection:
        tables = connection.execute(
            text("SELECT count(*) FROM information_schema.tables WHERE table_name = 'installation'")
        ).scalar_one()

    assert_that(tables, equal_to(0))
