"""AF-337 migration: every Organization ends up with a ceiling, and the permission that
lets an Organization manage its own limits exists."""

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid7

import pytest
from alembic import command
from alembic.config import Config
from hamcrest import assert_that, equal_to, is_
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

PRE_AF337_REVISION = "73e85ce78653"
AF337_REVISION = "d7a2c4f81b36"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
LLM_BUDGET_MANAGE_ID = UUID("5d0c2b7e-8f41-5a6c-9e3d-1b7f4a2c6e90")
NOW = "2026-09-23T00:00:00+00:00"


@pytest.fixture
def pre_af337_database(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"af337_{uuid7().hex}"
    target_url = source_url.set(database=database_name)
    admin_engine = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))

    monkeypatch.setenv("ALEMBIC_DB_URL", target_url.render_as_string(False))
    config = Config(ALEMBIC_INI)
    command.upgrade(config, PRE_AF337_REVISION)
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


def insert_organization(engine, budget=None, duration=None) -> UUID:
    organization_id = uuid7()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO organization "
                "(id, created_at, updated_at, name, allowed_models, llm_budget_usd, llm_budget_duration) "
                "VALUES (:id, :now, :now, :name, '[]'::jsonb, :budget, :duration)"
            ),
            {
                "id": organization_id,
                "now": NOW,
                "name": f"Org {organization_id}",
                "budget": budget,
                "duration": duration,
            },
        )
    return organization_id


def ceiling_of(engine, organization_id):
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT llm_budget_usd, llm_budget_duration FROM organization WHERE id = :id"),
            {"id": organization_id},
        ).one()


def test_an_uncapped_organization_gets_the_deployment_default(pre_af337_database):
    """conftest sets ORGANIZATION_DEFAULT_LLM_BUDGET_USD=100."""
    organization_id = insert_organization(pre_af337_database.engine)
    command.upgrade(pre_af337_database.config, AF337_REVISION)
    assert_that(tuple(ceiling_of(pre_af337_database.engine, organization_id)), equal_to((100.0, "30d")))


def test_a_capped_organization_keeps_its_ceiling_and_window(pre_af337_database):
    organization_id = insert_organization(pre_af337_database.engine, budget=12.5, duration="7d")
    command.upgrade(pre_af337_database.config, AF337_REVISION)
    assert_that(tuple(ceiling_of(pre_af337_database.engine, organization_id)), equal_to((12.5, "7d")))


def test_the_ceiling_can_no_longer_be_cleared(pre_af337_database):
    organization_id = insert_organization(pre_af337_database.engine)
    command.upgrade(pre_af337_database.config, AF337_REVISION)
    with pytest.raises(IntegrityError), pre_af337_database.engine.begin() as connection:
        connection.execute(
            text("UPDATE organization SET llm_budget_usd = NULL WHERE id = :id"), {"id": organization_id}
        )


def test_an_organizations_own_limit_can_never_exceed_its_ceiling(pre_af337_database):
    organization_id = insert_organization(pre_af337_database.engine, budget=50, duration="30d")
    command.upgrade(pre_af337_database.config, AF337_REVISION)
    with pytest.raises(IntegrityError), pre_af337_database.engine.begin() as connection:
        connection.execute(
            text("UPDATE organization SET llm_own_budget_usd = 60 WHERE id = :id"), {"id": organization_id}
        )


def test_the_budget_management_permission_is_catalogued(pre_af337_database):
    command.upgrade(pre_af337_database.config, AF337_REVISION)
    with pre_af337_database.engine.connect() as connection:
        key = connection.execute(
            text("SELECT key FROM permissions WHERE id = :id"), {"id": LLM_BUDGET_MANAGE_ID}
        ).scalar_one()
    assert_that(key, equal_to("llm_budget.manage"))


def test_the_catalogue_is_locked_again_afterwards(pre_af337_database):
    command.upgrade(pre_af337_database.config, AF337_REVISION)
    with pytest.raises(IntegrityError) as raised, pre_af337_database.engine.begin() as connection:
        connection.execute(
            text("INSERT INTO permissions (id, created_at, updated_at, key) VALUES (:id, now(), now(), 'rogue')"),
            {"id": uuid7()},
        )
    assert_that("Permission catalogue cannot be changed" in str(raised.value), is_(True))


def test_downgrade_removes_the_permission_and_the_new_columns(pre_af337_database):
    command.upgrade(pre_af337_database.config, AF337_REVISION)
    command.downgrade(pre_af337_database.config, PRE_AF337_REVISION)
    with pre_af337_database.engine.connect() as connection:
        permission = connection.execute(
            text("SELECT count(*) FROM permissions WHERE id = :id"), {"id": LLM_BUDGET_MANAGE_ID}
        ).scalar_one()
        columns = connection.execute(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE (table_name = 'organization' AND column_name = 'llm_own_budget_usd') "
                "OR (table_name = 'agent' AND column_name = 'llm_budget_usd') "
                "OR (table_name = 'organization_agent_settings' AND column_name = 'default_agent_llm_budget_usd')"
            )
        ).scalar_one()
    assert_that((permission, columns), is_((0, 0)))
