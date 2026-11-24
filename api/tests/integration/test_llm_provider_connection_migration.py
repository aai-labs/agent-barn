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
PROVIDERS_REVISION = "91ad0093c626"
BEFORE_MODELS_REVISION = "3f9f88255e3b"
MODELS_REVISION = "bc817a73bb6d"
BEFORE_ACCESS_REVISION = "9a64534a1a2f"
ACCESS_REVISION = "7847fc32d19c"
MODEL_TABLE = "llm_provider_model"
ACCESS_TABLE = "llm_provider_connection_organization"
ORGANIZATION_ACCESS_MODES = ["all", "none", "all_except", "only"]
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
TABLE = LlmProviderConnection.__tablename__
SEEDED_ROW = (OPENROUTER_CONNECTION_ID, OPENROUTER_SLUG, OPENROUTER_NAME, "openrouter", None, None, None, None)
ROW_COLUMNS = "id, slug, name, provider_type, api_key_encrypted, api_key_last4, updated_by, deleted_at"
KNOWN_PROVIDER_TYPES = ["anthropic", "openai", "gemini", "xai", "deepseek", "fireworks", "novita"]
BASE_URL = "https://models.example.com/v1"


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
        organization_id = uuid7()
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"UPDATE {TABLE} SET api_key_encrypted = 'ciphertext', api_key_last4 = 'a1b2', deleted_at = now(),"
                    " organization_access = 'only'"
                )
            )
            _insert(connection, slug="azure-eu", provider_type="azure", base_url=BASE_URL)
            _insert_organization(connection, organization_id)
            _list_organization(connection, OPENROUTER_CONNECTION_ID, organization_id)

        database_is_clean()(context)

        with engine.connect() as connection:
            rows = connection.execute(text(f"SELECT {ROW_COLUMNS} FROM {TABLE}")).all()
            access = connection.execute(text(f"SELECT organization_access FROM {TABLE}")).scalar_one()
            listed = connection.execute(text(f"SELECT count(*) FROM {ACCESS_TABLE}")).scalar_one()
        assert_that([tuple(row) for row in rows], equal_to([SEEDED_ROW]))
        assert_that((access, listed), equal_to(("all", 0)))


def _insert_model(connection, connection_id, **overrides):
    row = {
        "id": uuid7(),
        "connection_id": connection_id,
        "model_id": "claude-sonnet-4-5",
        "input_cost_per_token": "0.000003",
        "output_cost_per_token": "0.000015",
        "cache_read_input_token_cost": "0",
        "cache_creation_input_token_cost": "0",
        "price_source": "manual",
        "litellm_price_key": None,
        **overrides,
    }
    columns = ", ".join(row)
    values = ", ".join(f":{column}" for column in row)
    connection.execute(
        text(f"INSERT INTO {MODEL_TABLE} (created_at, updated_at, {columns}) VALUES (now(), now(), {values})"), row
    )


def test_the_models_migration_starts_with_no_models(database_before_connections):
    database = database_before_connections

    command.upgrade(database.config, MODELS_REVISION)

    with database.engine.connect() as connection:
        count = connection.execute(text(f"SELECT count(*) FROM {MODEL_TABLE}")).scalar_one()
    assert_that(count, equal_to(0))


def test_a_model_priced_by_hand_or_from_litellm_is_accepted(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, MODELS_REVISION)

    with database.engine.begin() as connection:
        _insert_model(connection, OPENROUTER_CONNECTION_ID)
        _insert_model(
            connection,
            OPENROUTER_CONNECTION_ID,
            model_id="accounts/fireworks/models/llama-v3:latest",
            cache_creation_input_token_cost="0.000000000000000001",
            price_source="litellm",
            litellm_price_key="fireworks_ai/accounts/fireworks/models/llama-v3",
        )

        rows = connection.execute(
            text(f"SELECT model_id, cache_creation_input_token_cost FROM {MODEL_TABLE} ORDER BY model_id")
        ).all()
    assert_that(
        [(model_id, str(price)) for model_id, price in rows],
        equal_to([("accounts/fireworks/models/llama-v3:latest", "1E-18"), ("claude-sonnet-4-5", "0E-18")]),
    )


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"input_cost_per_token": "0"}, "ck_llm_provider_model_input_price_positive"),
        ({"output_cost_per_token": "0"}, "ck_llm_provider_model_output_price_positive"),
        ({"cache_read_input_token_cost": "-0.000001"}, "ck_llm_provider_model_cache_read_price_not_negative"),
        ({"cache_creation_input_token_cost": "-0.000001"}, "ck_llm_provider_model_cache_creation_price_not_negative"),
        ({"price_source": "guessed"}, "ck_llm_provider_model_price_source_known"),
        ({"price_source": "litellm"}, "ck_llm_provider_model_price_key_by_source"),  # LiteLLM's price with no key
        ({"litellm_price_key": "gpt-4o"}, "ck_llm_provider_model_price_key_by_source"),  # a typed price with a key
        ({"model_id": "gpt 4o"}, "ck_llm_provider_model_model_id_format"),
        ({"model_id": ""}, "ck_llm_provider_model_model_id_format"),
    ],
)
def test_the_database_refuses_a_model_that_could_not_be_routed_and_priced(
    database_before_connections, overrides, constraint
):
    database = database_before_connections
    command.upgrade(database.config, MODELS_REVISION)

    with pytest.raises(IntegrityError, match=constraint), database.engine.begin() as connection:
        _insert_model(connection, OPENROUTER_CONNECTION_ID, **overrides)


def test_the_database_refuses_a_model_listed_twice_or_without_its_connection(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, MODELS_REVISION)
    with database.engine.begin() as connection:
        _insert_model(connection, OPENROUTER_CONNECTION_ID)

    with (
        pytest.raises(IntegrityError, match="uq_llm_provider_model_connection_model"),
        database.engine.begin() as connection,
    ):
        _insert_model(connection, OPENROUTER_CONNECTION_ID)
    with pytest.raises(IntegrityError), database.engine.begin() as connection:
        _insert_model(connection, uuid7())


def test_the_model_table_matches_its_migration(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, "head")

    with database.engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diffs = [diff for diff in compare_metadata(context, SQLModel.metadata) if MODEL_TABLE in repr(diff)]

    assert_that(diffs, equal_to([]))


def test_the_models_downgrade_removes_the_table_and_keeps_the_connections(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, MODELS_REVISION)
    with database.engine.begin() as connection:
        _insert_model(connection, OPENROUTER_CONNECTION_ID)

    command.downgrade(database.config, BEFORE_MODELS_REVISION)

    assert_that(inspect(database.engine).has_table(MODEL_TABLE), equal_to(False))
    with database.engine.connect() as connection:
        count = connection.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one()
    assert_that(count, equal_to(1))


def _insert_organization(connection, organization_id):
    connection.execute(
        text(
            "INSERT INTO organization (id, created_at, updated_at, name, llm_budget_usd, llm_budget_duration)"
            " VALUES (:id, now(), now(), 'Listed Org', 100, '30d')"
        ),
        {"id": organization_id},
    )


def _list_organization(connection, connection_id, organization_id):
    connection.execute(
        text(f"INSERT INTO {ACCESS_TABLE} (connection_id, organization_id) VALUES (:connection_id, :organization_id)"),
        {"connection_id": connection_id, "organization_id": organization_id},
    )


def _listed(connection):
    return connection.execute(text(f"SELECT connection_id, organization_id FROM {ACCESS_TABLE}")).all()


def test_the_access_migration_opens_every_existing_connection_to_all_organizations(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, BEFORE_ACCESS_REVISION)
    with database.engine.begin() as connection:
        _insert(connection, slug="anthropic", provider_type="anthropic")
        _insert(
            connection, slug="azure-eu", provider_type="azure", base_url=BASE_URL, deleted_at="2026-11-17T00:00:00Z"
        )

    command.upgrade(database.config, ACCESS_REVISION)

    with database.engine.connect() as connection:
        rows = connection.execute(text(f"SELECT slug, organization_access FROM {TABLE} ORDER BY slug")).all()
        listed = _listed(connection)
    assert_that(
        [tuple(row) for row in rows], equal_to([("anthropic", "all"), ("azure-eu", "all"), (OPENROUTER_SLUG, "all")])
    )
    assert_that(listed, equal_to([]))


def test_a_new_connection_is_open_to_all_organizations_unless_told_otherwise(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, ACCESS_REVISION)

    with database.engine.begin() as connection:
        _insert(connection, slug="anthropic", provider_type="anthropic")

        access = connection.execute(
            text(f"SELECT organization_access FROM {TABLE} WHERE slug = 'anthropic'")
        ).scalar_one()
    assert_that(access, equal_to("all"))


@pytest.mark.parametrize("mode", ORGANIZATION_ACCESS_MODES)
def test_each_organization_access_mode_is_accepted(database_before_connections, mode):
    database = database_before_connections
    command.upgrade(database.config, ACCESS_REVISION)

    with database.engine.begin() as connection:
        _insert(connection, slug="anthropic", provider_type="anthropic", organization_access=mode)

        access = connection.execute(
            text(f"SELECT organization_access FROM {TABLE} WHERE slug = 'anthropic'")
        ).scalar_one()
    assert_that(access, equal_to(mode))


@pytest.mark.parametrize("mode", ["some", "ALL", ""])
def test_the_database_refuses_an_unknown_organization_access(database_before_connections, mode):
    database = database_before_connections
    command.upgrade(database.config, ACCESS_REVISION)

    with (
        pytest.raises(IntegrityError, match="ck_llm_provider_connection_organization_access_known"),
        database.engine.begin() as connection,
    ):
        _insert(connection, slug="anthropic", provider_type="anthropic", organization_access=mode)


def test_a_connection_lists_each_organization_once(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, ACCESS_REVISION)
    organization_id = uuid7()
    with database.engine.begin() as connection:
        _insert_organization(connection, organization_id)
        _list_organization(connection, OPENROUTER_CONNECTION_ID, organization_id)

    with database.engine.connect() as connection:
        listed = _listed(connection)
    assert_that([tuple(row) for row in listed], equal_to([(OPENROUTER_CONNECTION_ID, organization_id)]))
    with (
        pytest.raises(IntegrityError, match=f"{ACCESS_TABLE}_pkey"),
        database.engine.begin() as connection,
    ):
        _list_organization(connection, OPENROUTER_CONNECTION_ID, organization_id)


def test_the_database_refuses_listing_an_unknown_connection_or_organization(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, ACCESS_REVISION)
    organization_id = uuid7()
    with database.engine.begin() as connection:
        _insert_organization(connection, organization_id)

    with (
        pytest.raises(IntegrityError, match=f"{ACCESS_TABLE}_connection_id_fkey"),
        database.engine.begin() as connection,
    ):
        _list_organization(connection, uuid7(), organization_id)
    with (
        pytest.raises(IntegrityError, match=f"{ACCESS_TABLE}_organization_id_fkey"),
        database.engine.begin() as connection,
    ):
        _list_organization(connection, OPENROUTER_CONNECTION_ID, uuid7())


def test_deleting_a_connection_or_an_organization_removes_its_listings(database_before_connections):
    database = database_before_connections
    command.upgrade(database.config, ACCESS_REVISION)
    kept, removed = uuid7(), uuid7()
    anthropic_id = uuid7()
    with database.engine.begin() as connection:
        _insert(connection, id=anthropic_id, slug="anthropic", provider_type="anthropic")
        _insert_organization(connection, kept)
        _insert_organization(connection, removed)
        for connection_id in (OPENROUTER_CONNECTION_ID, anthropic_id):
            for organization_id in (kept, removed):
                _list_organization(connection, connection_id, organization_id)

    with database.engine.begin() as connection:
        connection.execute(text(f"DELETE FROM {TABLE} WHERE id = :id"), {"id": anthropic_id})
        connection.execute(text("DELETE FROM organization WHERE id = :id"), {"id": removed})

    with database.engine.connect() as connection:
        listed = _listed(connection)
    assert_that([tuple(row) for row in listed], equal_to([(OPENROUTER_CONNECTION_ID, kept)]))


def test_the_access_downgrade_removes_the_mode_and_the_listings_and_keeps_the_connections(
    database_before_connections,
):
    database = database_before_connections
    command.upgrade(database.config, ACCESS_REVISION)
    organization_id = uuid7()
    with database.engine.begin() as connection:
        _insert(connection, slug="anthropic", provider_type="anthropic", organization_access="only")
        _insert_organization(connection, organization_id)
        _list_organization(connection, OPENROUTER_CONNECTION_ID, organization_id)

    command.downgrade(database.config, BEFORE_ACCESS_REVISION)

    inspector = inspect(database.engine)
    assert_that(inspector.has_table(ACCESS_TABLE), equal_to(False))
    columns = [column["name"] for column in inspector.get_columns(TABLE)]
    assert_that("organization_access" in columns, equal_to(False))
    with database.engine.connect() as connection:
        slugs = connection.execute(text(f"SELECT slug FROM {TABLE} ORDER BY slug")).scalars().all()
    assert_that(slugs, equal_to(["anthropic", OPENROUTER_SLUG]))
