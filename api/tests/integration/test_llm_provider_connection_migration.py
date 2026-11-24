"""The migrations that create LLM Provider Connections, add more providers and add their models, each run against a
database of its own."""

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
from sqlalchemy import CheckConstraint, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel

from api.domains.llm_providers.models import (
    OPENROUTER_CONNECTION_ID,
    OPENROUTER_NAME,
    OPENROUTER_SLUG,
    LlmProviderConnection,
    LlmProviderModel,
)
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector
from api.tests.steps.database import database_is_clean, database_repo_is_ready

PRE_MIGRATION_REVISION = "38de1199ae19"
CONNECTIONS_REVISION = "22b93965859f"
PROVIDERS_REVISION = "91ad0093c626"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
TABLE = LlmProviderConnection.__tablename__
SEEDED_ROW = (OPENROUTER_CONNECTION_ID, OPENROUTER_SLUG, OPENROUTER_NAME, "openrouter", None, None, None, None)
ROW_COLUMNS = "id, slug, name, provider_type, api_key_encrypted, api_key_last4, updated_by, deleted_at"
KNOWN_PROVIDER_TYPES = ["anthropic", "openai", "gemini", "xai", "deepseek", "fireworks", "novita"]
BASE_URL = "https://models.example.com/v1"
PRE_MODELS_REVISION = "3f9f88255e3b"
MODELS_REVISION = "bc817a73bb6d"
MODEL_TABLE = LlmProviderModel.__tablename__


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
    columns = ", ".join(row)
    values = ", ".join(f":{column}" for column in row)
    connection.execute(
        text(f"INSERT INTO {TABLE} (created_at, updated_at, {columns}) VALUES (now(), now(), {values})"), row
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


def test_the_model_matches_the_migrations(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, "head")

    with database.engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diffs = [diff for diff in compare_metadata(context, SQLModel.metadata) if TABLE in repr(diff)]

    assert_that(diffs, equal_to([]))


def test_the_downgrade_removes_the_table(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, CONNECTIONS_REVISION)

    command.downgrade(database.config, PRE_MIGRATION_REVISION)

    assert_that(inspect(database.engine).has_table(TABLE), equal_to(False))


def test_adding_providers_keeps_openrouter_without_a_base_url(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, PROVIDERS_REVISION)

    with database.engine.connect() as connection:
        rows = connection.execute(text(f"SELECT {ROW_COLUMNS}, base_url FROM {TABLE}")).all()
    assert_that([tuple(row) for row in rows], equal_to([(*SEEDED_ROW, None)]))


@pytest.mark.parametrize("provider_type", KNOWN_PROVIDER_TYPES)
def test_a_known_provider_is_accepted_under_its_own_name(database_before_connections, provider_type):
    database = database_before_connections
    command.upgrade(database.config, PROVIDERS_REVISION)

    with database.engine.begin() as connection:
        _insert(connection, slug=provider_type, provider_type=provider_type)

        count = connection.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one()
    assert_that(count, equal_to(2))


@pytest.mark.parametrize("provider_type", ["azure", "custom"])
def test_an_azure_or_custom_connection_is_accepted_with_its_own_slug_and_a_base_url(
    database_before_connections, provider_type
):
    database = database_before_connections
    command.upgrade(database.config, PROVIDERS_REVISION)

    with database.engine.begin() as connection:
        _insert(connection, slug=f"{provider_type}-eu", provider_type=provider_type, base_url=BASE_URL)
        _insert(connection, slug=f"{provider_type}-us", provider_type=provider_type, base_url=BASE_URL)

        count = connection.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one()
    assert_that(count, equal_to(3))


@pytest.mark.parametrize(
    ("overrides", "check"),
    [
        ({"slug": "anthropic", "provider_type": "anthropic", "base_url": BASE_URL}, "base_url_by_type"),
        ({"slug": "azure-eu", "provider_type": "azure"}, "base_url_by_type"),
        ({"slug": "custom-lab", "provider_type": "custom"}, "base_url_by_type"),
        ({"slug": "anthropic-main", "provider_type": "anthropic"}, "known_slug_is_type"),
        ({"slug": "openai", "provider_type": "custom", "base_url": BASE_URL}, "own_slug_not_a_type"),
        ({"slug": "anthropic", "provider_type": "azure", "base_url": BASE_URL}, "own_slug_not_a_type"),
        ({"slug": "azure", "provider_type": "azure", "base_url": BASE_URL}, "own_slug_not_a_type"),
        ({"slug": "custom", "provider_type": "custom", "base_url": BASE_URL}, "own_slug_not_a_type"),
        ({"slug": "mistral", "provider_type": "mistral"}, "provider_type_known"),
    ],
)
def test_the_database_refuses_a_connection_that_does_not_fit_its_provider(
    database_before_connections, overrides, check
):
    database = database_before_connections
    command.upgrade(database.config, PROVIDERS_REVISION)

    with (
        pytest.raises(IntegrityError, match=f"ck_llm_provider_connection_{check}"),
        database.engine.begin() as connection,
    ):
        _insert(connection, **overrides)


def test_removing_providers_deletes_every_other_connection_and_keeps_openrouter(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, PROVIDERS_REVISION)
    with database.engine.begin() as connection:
        connection.execute(text(f"UPDATE {TABLE} SET api_key_encrypted = 'ciphertext', api_key_last4 = 'a1b2'"))
        _insert(
            connection, slug="anthropic", provider_type="anthropic", api_key_encrypted="secret", api_key_last4="c3d4"
        )
        _insert(
            connection, slug="azure-eu", provider_type="azure", base_url=BASE_URL, deleted_at="2026-11-17T00:00:00Z"
        )

    command.downgrade(database.config, CONNECTIONS_REVISION)

    with database.engine.connect() as connection:
        rows = connection.execute(text(f"SELECT {ROW_COLUMNS} FROM {TABLE}")).all()
    openrouter_with_its_key = (*SEEDED_ROW[:4], "ciphertext", "a1b2", None, None)
    assert_that([tuple(row) for row in rows], equal_to([openrouter_with_its_key]))
    columns = [column["name"] for column in inspect(database.engine).get_columns(TABLE)]
    assert_that("base_url" in columns, equal_to(False))
    with (
        pytest.raises(IntegrityError, match="ck_llm_provider_connection_provider_type_known"),
        database.engine.begin() as connection,
    ):
        _insert(connection, slug="anthropic", provider_type="anthropic")


def test_a_clean_database_has_only_the_seeded_openrouter_connection():
    with given([prepare_injector(), database_repo_is_ready(), database_is_clean()]) as context:
        engine = context.postgres_delegate.engine
        with engine.begin() as connection:
            connection.execute(
                text(f"UPDATE {TABLE} SET api_key_encrypted = 'ciphertext', api_key_last4 = 'a1b2', deleted_at = now()")
            )
            _insert(connection, slug="azure-eu", provider_type="azure", base_url=BASE_URL)

        database_is_clean()(context)

        with engine.connect() as connection:
            rows = connection.execute(text(f"SELECT {ROW_COLUMNS} FROM {TABLE}")).all()
        assert_that([tuple(row) for row in rows], equal_to([SEEDED_ROW]))


def _insert_model(connection, **overrides):
    row = {
        "id": uuid7(),
        "connection_id": OPENROUTER_CONNECTION_ID,
        "model_id": "claude-opus-4-1",
        "input_cost_per_token": "0.000015",
        "output_cost_per_token": "0.000075",
        "cache_read_input_token_cost": "0",
        "cache_creation_input_token_cost": "0.00001875",
        "price_source": "litellm",
        "litellm_price_key": "claude-opus-4-1",
        **overrides,
    }
    columns = ", ".join(row)
    values = ", ".join(f":{column}" for column in row)
    connection.execute(
        text(f"INSERT INTO {MODEL_TABLE} (created_at, updated_at, {columns}) VALUES (now(), now(), {values})"), row
    )


def test_a_priced_model_is_accepted_with_its_exact_prices(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, MODELS_REVISION)

    with database.engine.begin() as connection:
        _insert_model(connection, input_cost_per_token="0.000000000000000001")
        _insert_model(connection, model_id="typed", price_source="manual", litellm_price_key=None)

        prices = connection.execute(
            text(f"SELECT input_cost_per_token FROM {MODEL_TABLE} WHERE model_id = 'claude-opus-4-1'")
        ).scalar_one()
    assert_that(format(prices, "f"), equal_to("0.000000000000000001"))


@pytest.mark.parametrize(
    "overrides",
    [
        {"input_cost_per_token": "0"},  # an input price of 0 would skip budget checks
        {"output_cost_per_token": "0"},  # so would an output price of 0
        {"input_cost_per_token": "-0.000001"},
        {"cache_read_input_token_cost": "-0.000001"},
        {"cache_creation_input_token_cost": "-0.000001"},
        {"price_source": "guessed"},  # a source the platform does not know
        {"litellm_price_key": None},  # a LiteLLM price with no key it was read under
        {"price_source": "manual"},  # a typed price that claims a LiteLLM key
        {"model_id": "claude opus"},  # a space can't be routed
        {"model_id": ""},  # no model id
        {"connection_id": uuid7()},  # a connection that does not exist
    ],
)
def test_the_database_refuses_a_model_that_could_not_be_billed(database_before_connections, overrides):
    database = database_before_connections
    command.upgrade(database.config, MODELS_REVISION)

    with pytest.raises(IntegrityError), database.engine.begin() as connection:
        _insert_model(connection, **overrides)


def test_a_connection_lists_a_model_once(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, MODELS_REVISION)

    with pytest.raises(IntegrityError), database.engine.begin() as connection:
        _insert_model(connection)
        _insert_model(connection)


def test_the_model_table_matches_its_migration(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, "head")

    with database.engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diffs = [diff for diff in compare_metadata(context, SQLModel.metadata) if MODEL_TABLE in repr(diff)]
        constraints = {
            constraint["name"]: constraint["sqltext"]
            for constraint in inspect(connection).get_check_constraints(MODEL_TABLE)
        }

    assert_that(diffs, equal_to([]))
    declared = {
        constraint.name
        for constraint in SQLModel.metadata.tables[MODEL_TABLE].constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert_that(set(constraints), equal_to(declared))


def test_the_models_downgrade_removes_only_the_model_table(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, MODELS_REVISION)

    command.downgrade(database.config, PRE_MODELS_REVISION)

    assert_that(inspect(database.engine).has_table(MODEL_TABLE), equal_to(False))
    assert_that(inspect(database.engine).has_table(TABLE), equal_to(True))
