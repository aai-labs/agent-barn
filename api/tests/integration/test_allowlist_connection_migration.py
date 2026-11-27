"""The migration that names the connection of every allowlist entry, run against a database of its own."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid7

import pytest
from alembic import command
from alembic.config import Config
from hamcrest import assert_that, equal_to
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BEFORE_REVISION = "b3d81c5e9f42"
PREFIX_REVISION = "e5c2a9d4b7f1"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
BARE_ENTRIES = ["z-ai/glm-5.2", "*", "openrouter/free"]
PREFIXED_ENTRIES = ["openrouter/z-ai/glm-5.2", "openrouter/*", "openrouter/openrouter/free"]


@pytest.fixture
def database_before_prefixing(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"allowlist_prefix_{uuid7().hex}"
    admin_engine = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))

    target_url = source_url.set(database=database_name)
    monkeypatch.setenv("ALEMBIC_DB_URL", target_url.render_as_string(False))
    config = Config(ALEMBIC_INI)
    command.upgrade(config, BEFORE_REVISION)
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


def _organization_with(database, allowed_models: list[str]) -> UUID:
    organization_id = uuid7()
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO organization (id, created_at, updated_at, name, allowed_models, llm_budget_usd,"
                " llm_budget_duration) VALUES (:id, now(), now(), :name, CAST(:allowed_models AS jsonb), 100, '30d')"
            ),
            {"id": organization_id, "name": f"Org {organization_id}", "allowed_models": json.dumps(allowed_models)},
        )
    return organization_id


def _set_allowlist(database, organization_id: UUID, allowed_models: list[str]) -> None:
    with database.engine.begin() as connection:
        connection.execute(
            text("UPDATE organization SET allowed_models = CAST(:allowed_models AS jsonb) WHERE id = :id"),
            {"id": organization_id, "allowed_models": json.dumps(allowed_models)},
        )


def _allowlist(database, organization_id: UUID) -> list[str]:
    with database.engine.connect() as connection:
        return connection.execute(
            text("SELECT allowed_models FROM organization WHERE id = :id"), {"id": organization_id}
        ).scalar_one()


def test_every_entry_is_named_by_openrouter_and_an_empty_allowlist_stays_empty(database_before_prefixing):
    database = database_before_prefixing
    listed = _organization_with(database, BARE_ENTRIES)
    empty = _organization_with(database, [])

    command.upgrade(database.config, PREFIX_REVISION)

    assert_that(_allowlist(database, listed), equal_to(PREFIXED_ENTRIES))
    assert_that(_allowlist(database, empty), equal_to([]))


def test_the_downgrade_strips_openrouter_and_drops_entries_of_other_connections(database_before_prefixing):
    database = database_before_prefixing
    migrated = _organization_with(database, BARE_ENTRIES)
    mixed = _organization_with(database, [])
    command.upgrade(database.config, PREFIX_REVISION)
    _set_allowlist(database, mixed, ["openrouter/openai/gpt-5", "anthropic/claude-sonnet-4-5", "openrouter/*"])

    command.downgrade(database.config, BEFORE_REVISION)

    assert_that(_allowlist(database, migrated), equal_to(BARE_ENTRIES))
    assert_that(_allowlist(database, mixed), equal_to(["openai/gpt-5", "*"]))
