import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from hamcrest import assert_that, equal_to, is_, none
from sqlalchemy import MetaData, Table, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from api.domains.agents.models import Agent
from api.domains.organizations.models import Organization

PREVIOUS_REVISION = "72c4a9e1b6d8"
REVISION = "8b1d5e7f9a23"


@pytest.fixture
def driver_key_database(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"driver_default_{uuid7().hex}"
    admin = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    target_url = source_url.set(database=database_name)
    monkeypatch.setenv("ALEMBIC_DB_URL", target_url.render_as_string(False))
    config = Config(Path(__file__).resolve().parents[2] / "alembic.ini")
    engine = create_engine(target_url)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        with Session(engine) as session:
            organization = Organization(name="Driver default migration")
            session.add(organization)
            session.flush()
            agent = Agent(
                name="Historical Migration Agent", organization_id=organization.id, deleted_at=datetime.now(UTC)
            )
            session.add(agent)
            session.commit()
            database = SimpleNamespace(config=config, engine=engine, agent_id=agent.id, organization_id=organization.id)
        yield database
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": database_name},
            )
            connection.execute(text(f'DROP DATABASE "{database_name}"'))
        admin.dispose()


def insert_connection(database, platform, **legacy_fields):
    # Reflection supports both historical explicit writers and omitted-column writers.
    table = Table("communication_connection", MetaData(), autoload_with=database.engine)
    with database.engine.begin() as connection:
        return connection.execute(
            table.insert()
            .values(
                id=uuid7(),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                organization_id=database.organization_id,
                agent_id=database.agent_id,
                platform_key=platform,
                display_name=platform,
                credentials_encrypted="fixture-provider-credentials",
                **legacy_fields,
            )
            .returning(table.c.id)
        ).scalar_one()


def test_driver_default_preserves_old_rows_and_accepts_old_and_future_writers(driver_key_database):
    database = driver_key_database
    historical_id = insert_connection(
        database, "slack", driver_key_encrypted="fixture-legacy-driver", ingress_lease_owner="old-owner"
    )
    before = inspect(database.engine).get_columns("communication_connection")
    with database.engine.connect() as connection:
        table = Table("communication_connection", MetaData(), autoload_with=database.engine)
        original = dict(connection.execute(table.select().where(table.c.id == historical_id)).mappings().one())

    command.upgrade(database.config, REVISION)
    omitted_id = insert_connection(database, "web")
    explicit_id = insert_connection(database, "email", driver_key_encrypted="fixture-old-writer")

    with database.engine.connect() as connection:
        # Reflection selects every retained column like older mapped readers.
        omitted = connection.execute(table.select().where(table.c.id == omitted_id)).mappings().one()
        explicit = connection.execute(table.select().where(table.c.id == explicit_id)).mappings().one()
        assert_that(omitted["driver_key_encrypted"], equal_to(""))
        assert_that(explicit["driver_key_encrypted"], equal_to("fixture-old-writer"))
    with database.engine.connect() as connection:
        assert_that(
            dict(connection.execute(table.select().where(table.c.id == historical_id)).mappings().one()),
            equal_to(original),
        )
    after = inspect(database.engine).get_columns("communication_connection")
    assert_that([column["name"] for column in after], equal_to([column["name"] for column in before]))
    driver = next(column for column in after if column["name"] == "driver_key_encrypted")
    assert_that(driver["nullable"], is_(False))
    with pytest.raises(IntegrityError):
        insert_connection(database, "discord", driver_key_encrypted=None)


def test_driver_default_downgrade_preserves_rows_and_restores_required_explicit_value(driver_key_database):
    database = driver_key_database
    command.upgrade(database.config, REVISION)
    created_id = insert_connection(database, "web")

    command.downgrade(database.config, PREVIOUS_REVISION)

    driver = next(
        column
        for column in inspect(database.engine).get_columns("communication_connection")
        if column["name"] == "driver_key_encrypted"
    )
    assert_that(driver["default"], none())
    with database.engine.connect() as connection:
        table = Table("communication_connection", MetaData(), autoload_with=database.engine)
        created = connection.execute(table.select().where(table.c.id == created_id)).mappings().one()
        assert_that(created["driver_key_encrypted"], equal_to(""))
    with pytest.raises(IntegrityError):
        insert_connection(database, "email")
    insert_connection(database, "email", driver_key_encrypted="fixture-old-writer")
    command.upgrade(database.config, REVISION)
    insert_connection(database, "telegram")
