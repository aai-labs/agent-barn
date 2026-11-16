"""The migration that creates LLM Provider Connections, run against a database of its own."""

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
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel

from api.domains.llm_providers.models import (
    OPENROUTER_CONNECTION_ID,
    OPENROUTER_NAME,
    OPENROUTER_SLUG,
    LlmProviderConnection,
)
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector
from api.tests.steps.database import database_is_clean, database_repo_is_ready

PRE_MIGRATION_REVISION = "38de1199ae19"
CONNECTIONS_REVISION = "22b93965859f"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
TABLE = LlmProviderConnection.__tablename__
SEEDED_ROW = (OPENROUTER_CONNECTION_ID, OPENROUTER_SLUG, OPENROUTER_NAME, "openrouter", None, None, None, None)
ROW_COLUMNS = "id, slug, name, provider_type, api_key_encrypted, api_key_last4, updated_by, deleted_at"


@pytest.fixture
def database_before_connections(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"llm_providers_{uuid7().hex}"
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


def _insert(connection, **overrides):
    row = {
        "id": uuid7(),
        "slug": "anthropic-main",
        "name": "Anthropic",
        "provider_type": "openrouter",
        "api_key_encrypted": None,
        "api_key_last4": None,
        "deleted_at": None,
        **overrides,
    }
    connection.execute(
        text(
            f"INSERT INTO {TABLE} (id, created_at, updated_at, slug, name, provider_type, api_key_encrypted,"
            " api_key_last4, deleted_at) VALUES (:id, now(), now(), :slug, :name, :provider_type,"
            " :api_key_encrypted, :api_key_last4, :deleted_at)"
        ),
        row,
    )


def test_the_migration_seeds_openrouter_without_a_key(database_before_connections):
    database = database_before_connections

    command.upgrade(database.config, CONNECTIONS_REVISION)

    with database.engine.connect() as connection:
        rows = connection.execute(text(f"SELECT {ROW_COLUMNS} FROM {TABLE}")).all()
    assert_that([tuple(row) for row in rows], equal_to([SEEDED_ROW]))


def test_a_complete_key_is_accepted(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, CONNECTIONS_REVISION)

    with database.engine.begin() as connection:
        _insert(connection, api_key_encrypted="ciphertext", api_key_last4="a1b2")

        count = connection.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one()
    assert_that(count, equal_to(2))


@pytest.mark.parametrize(
    "overrides",
    [
        {"slug": OPENROUTER_SLUG},  # a slug already taken
        {"slug": OPENROUTER_SLUG, "deleted_at": "2026-11-16T00:00:00Z"},  # a deleted connection's slug is never reused
        {"slug": "Anthropic"},  # upper case
        {"slug": "anthropic/main"},  # a slash would split a model reference
        {"slug": "-anthropic"},  # a leading hyphen
        {"slug": ""},  # no slug
        {"provider_type": "unknown"},  # a provider the platform does not know
        {"api_key_encrypted": "ciphertext"},  # a key with no last four
        {"api_key_last4": "a1b2"},  # a last four with no key
    ],
)
def test_the_database_refuses_a_connection_that_could_not_be_used(database_before_connections, overrides):
    database = database_before_connections
    command.upgrade(database.config, CONNECTIONS_REVISION)

    with pytest.raises(IntegrityError), database.engine.begin() as connection:
        _insert(connection, **overrides)


def test_the_model_matches_the_migration(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, CONNECTIONS_REVISION)

    with database.engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diffs = [diff for diff in compare_metadata(context, SQLModel.metadata) if TABLE in repr(diff)]

    assert_that(diffs, equal_to([]))


def test_the_downgrade_removes_the_table(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, CONNECTIONS_REVISION)

    command.downgrade(database.config, PRE_MIGRATION_REVISION)

    assert_that(inspect(database.engine).has_table(TABLE), equal_to(False))


def test_a_clean_database_has_only_the_seeded_openrouter_connection():
    with given([prepare_injector(), database_repo_is_ready(), database_is_clean()]) as context:
        engine = context.postgres_delegate.engine
        with engine.begin() as connection:
            connection.execute(
                text(f"UPDATE {TABLE} SET api_key_encrypted = 'ciphertext', api_key_last4 = 'a1b2', deleted_at = now()")
            )
            _insert(connection)

        database_is_clean()(context)

        with engine.connect() as connection:
            rows = connection.execute(text(f"SELECT {ROW_COLUMNS} FROM {TABLE}")).all()
        assert_that([tuple(row) for row in rows], equal_to([SEEDED_ROW]))
