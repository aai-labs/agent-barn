"""The migration that adds Agent Add-ons, run against a database of its own."""

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from hamcrest import assert_that, equal_to, has_item, is_not
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

PRE_MIGRATION_REVISION = "8b2e4f61c9d3"
ADDONS_REVISION = "6fe963719ec9"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
AGENT_ADDON_MANAGE_ID = "8b81242c-14ec-5777-9619-da649a795dda"


@pytest.fixture
def database_before_addons(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"agent_addons_{uuid7().hex}"
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


def _running_agent(engine) -> str:
    """A running Agent as the database held one before add-ons existed."""
    organization_id, agent_id = uuid7(), uuid7()
    with engine.begin() as connection:
        # A Template pin is beside the point here, and only a live Agent needs one.
        connection.execute(text("ALTER TABLE agent DROP CONSTRAINT IF EXISTS ck_agent_template_pin_state"))
        connection.execute(
            text(
                "INSERT INTO organization (id, created_at, updated_at, name, llm_budget_usd, llm_budget_duration)"
                " VALUES (:id, now(), now(), 'Example', 100, '30d')"
            ),
            {"id": organization_id},
        )
        connection.execute(
            text(
                "INSERT INTO agent (id, created_at, updated_at, organization_id, name, litellm_key_encrypted, model,"
                " approval_mode, verbose_mode, status)"
                " VALUES (:id, now(), now(), :organization_id, 'Drafting', '', '', 'auto', false,"
                " CAST('RUNNING' AS agentstatus))"
            ),
            {"id": agent_id, "organization_id": organization_id},
        )
    return str(agent_id)


def test_no_existing_agent_reads_as_having_add_ons(database_before_addons):
    database = database_before_addons
    agent_id = _running_agent(database.engine)

    command.upgrade(database.config, ADDONS_REVISION)

    with database.engine.connect() as connection:
        running_hash = connection.execute(
            text("SELECT running_addons_hash FROM agent WHERE id = :id"), {"id": agent_id}
        ).scalar_one()
        addons = connection.execute(text("SELECT count(*) FROM agent_addons")).scalar_one()
    assert_that(running_hash, equal_to(None))
    assert_that(addons, equal_to(0))


def test_the_permission_joins_the_catalogue(database_before_addons):
    database = database_before_addons

    command.upgrade(database.config, ADDONS_REVISION)

    with database.engine.connect() as connection:
        key = connection.execute(
            text("SELECT key FROM permissions WHERE id = :id"), {"id": AGENT_ADDON_MANAGE_ID}
        ).scalar_one()
    assert_that(key, equal_to("agent.addon.manage"))


def test_the_catalogue_is_locked_again_afterwards(database_before_addons):
    database = database_before_addons
    command.upgrade(database.config, ADDONS_REVISION)

    with pytest.raises(Exception), database.engine.begin() as connection:  # noqa: B017 - the trigger's own error type
        connection.execute(
            text("UPDATE permissions SET key = 'agent.addon.anything' WHERE id = :id"), {"id": AGENT_ADDON_MANAGE_ID}
        )


def test_a_rejection_needs_its_reason_and_an_active_name_is_unique_per_agent(database_before_addons):
    database = database_before_addons
    agent_id = _running_agent(database.engine)
    command.upgrade(database.config, ADDONS_REVISION)
    with database.engine.connect() as connection:
        organization_id = connection.execute(
            text("SELECT organization_id FROM agent WHERE id = :id"), {"id": agent_id}
        ).scalar_one()

    def insert(state: str, name: str = "humanize", rejection_reason: str | None = None) -> None:
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO agent_addons (id, created_at, updated_at, organization_id, agent_id, kind, name, spec,"
                    " reason, state, rejection_reason) VALUES (:id, now(), now(), :organization_id, :agent_id, 'pip',"
                    " :name, '{\"version\": \"1.2.0\"}', 'why', :state, :rejection_reason)"
                ),
                {
                    "id": uuid7(),
                    "organization_id": organization_id,
                    "agent_id": agent_id,
                    "name": name,
                    "state": state,
                    "rejection_reason": rejection_reason,
                },
            )

    insert("PENDING")
    with pytest.raises(Exception):  # noqa: B017 - uq_agent_addons_active_name
        insert("APPROVED", name="Humanize")
    with pytest.raises(Exception):  # noqa: B017 - ck_agent_addons_rejection_reason
        insert("REJECTED")
    insert("REJECTED", rejection_reason="No.")
    insert("WITHDRAWN")


def test_the_migration_downgrades_cleanly(database_before_addons):
    database = database_before_addons
    command.upgrade(database.config, ADDONS_REVISION)

    command.downgrade(database.config, PRE_MIGRATION_REVISION)

    tables = inspect(database.engine).get_table_names()
    columns = [column["name"] for column in inspect(database.engine).get_columns("agent")]
    assert_that(tables, is_not(has_item("agent_addons")))
    assert_that(tables, is_not(has_item("agent_addon_email_receipt")))
    assert_that(columns, is_not(has_item("running_addons_hash")))
    with database.engine.connect() as connection:
        remaining = connection.execute(
            text("SELECT count(*) FROM permissions WHERE id = :id"), {"id": AGENT_ADDON_MANAGE_ID}
        ).scalar_one()
    assert_that(remaining, equal_to(0))
