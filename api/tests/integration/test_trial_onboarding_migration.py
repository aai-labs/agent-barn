"""AF-368 migration: Google sign-in and trial columns, and the platform trial settings
row. It downgrades cleanly, upgrades again, and leaves a schema that matches the models."""

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
import api.domains.onboarding.models
import api.domains.organizations.models
import api.domains.users.models  # noqa: F401
from api.core.config import get_config

PRE_AF368_REVISION = "164fb0fb6c2c"
AF368_HEAD = "b3d8e1f4a6c2"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
AF368_COLUMNS = {
    ("user", "google_sub"),
    ("user", "signed_up_at"),
    ("user", "trial_ended_at"),
    ("user", "onboarding_completed_at"),
    ("organization", "is_trial"),
    ("platform_trial_settings", "agent_limit"),
}
AF368_TABLES = {"platform_trial_settings", "trial_grant"}


@pytest.fixture
def scratch_database(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"af368_{uuid7().hex}"
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


def _af368_objects(engine) -> tuple[set[tuple[str, str]], set[str]]:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    columns = {
        (table, column["name"])
        for table in ("user", "organization", "platform_trial_settings")
        if table in tables
        for column in inspector.get_columns(table)
        if (table, column["name"]) in AF368_COLUMNS
    }
    return columns, tables & AF368_TABLES


def test_trial_onboarding_downgrades_cleanly_and_upgrades_again(scratch_database):
    command.upgrade(scratch_database.config, AF368_HEAD)
    assert_that(_af368_objects(scratch_database.engine), equal_to((AF368_COLUMNS, AF368_TABLES)))

    command.downgrade(scratch_database.config, PRE_AF368_REVISION)
    scratch_database.engine.dispose()
    assert_that(_af368_objects(scratch_database.engine), equal_to((set(), set())))

    command.upgrade(scratch_database.config, AF368_HEAD)
    scratch_database.engine.dispose()
    assert_that(_af368_objects(scratch_database.engine), equal_to((AF368_COLUMNS, AF368_TABLES)))


def test_existing_organizations_are_not_trials_after_upgrade(scratch_database):
    command.upgrade(scratch_database.config, PRE_AF368_REVISION)
    organization_id = uuid7()
    with scratch_database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO organization (id, created_at, updated_at, name, allowed_models, llm_budget_usd, "
                "llm_budget_duration) VALUES (:id, now(), now(), 'Existing Org', '[]', 100, '30d')"
            ),
            {"id": organization_id},
        )

    command.upgrade(scratch_database.config, AF368_HEAD)
    scratch_database.engine.dispose()

    with scratch_database.engine.connect() as connection:
        is_trial = connection.execute(
            text("SELECT is_trial FROM organization WHERE id = :id"), {"id": organization_id}
        ).scalar_one()
    assert_that(is_trial, equal_to(False))


def test_the_migrated_schema_matches_the_models_for_trial_onboarding():
    engine = create_engine(str(get_config().db_connection_url))
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), SQLModel.metadata)
    ours = [
        diff
        for diff in differences
        if any(
            name in repr(diff)
            for name in (
                "google_sub",
                "signed_up_at",
                "trial_ended_at",
                "onboarding_completed_at",
                "is_trial",
                "trial_settings",
                "trial_grant",
                "agent_limit",
            )
        )
    ]

    assert_that(ours, equal_to([]))
