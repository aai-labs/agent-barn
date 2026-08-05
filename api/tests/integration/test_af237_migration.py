import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from hamcrest import assert_that, equal_to, is_
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

PRE_AF237_REVISION = "181dcfcc93ef"
CURRENT_REVISION = "3b7c9d1e4f62"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture
def legacy_af237_database(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"af237_{uuid7().hex}"
    target_url = source_url.set(database=database_name)
    admin_engine = create_engine(
        source_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))

    monkeypatch.setenv("ALEMBIC_DB_URL", target_url.render_as_string(False))
    config = Config(ALEMBIC_INI)
    command.upgrade(config, PRE_AF237_REVISION)
    engine = create_engine(target_url)
    try:
        yield SimpleNamespace(config=config, engine=engine)
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :database_name
                      AND pid <> pg_backend_pid()
                    """
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f'DROP DATABASE "{database_name}"'))
        admin_engine.dispose()


def test_migration_backfills_creator_from_owner_and_keeps_ownerless_unknown(
    legacy_af237_database,
):
    owner_id = uuid7()
    owned_org_id = uuid7()
    ownerless_org_id = uuid7()
    now = "2026-07-31T00:00:00+00:00"

    with legacy_af237_database.engine.begin() as connection:
        connection.execute(
            text(
                'INSERT INTO "user" '
                "(id, created_at, updated_at, email, hashed_password, "
                "is_platform_admin, security_stamp) "
                "VALUES (:id, :now, :now, :email, :password, false, :stamp)"
            ),
            {
                "id": owner_id,
                "now": now,
                "email": "legacy-owner@example.com",
                "password": "hash",
                "stamp": uuid7().hex,
            },
        )
        for organization_id, name in (
            (owned_org_id, "Owned Legacy Org"),
            (ownerless_org_id, "Ownerless Legacy Org"),
        ):
            connection.execute(
                text(
                    "INSERT INTO organization "
                    "(id, created_at, updated_at, name, allowed_models) "
                    "VALUES (:id, :now, :now, :name, '[]'::jsonb)"
                ),
                {
                    "id": organization_id,
                    "now": now,
                    "name": name,
                },
            )
        event_id = uuid7()
        outbox_id = uuid7()
        connection.execute(
            text(
                "INSERT INTO event_outbox_message "
                "(id, created_at, updated_at, event_id, event_name, schema_version, "
                "occurred_at, organization_id, actor, subject, correlation_id, payload) "
                "VALUES (:id, :now, :now, :event_id, 'legacy.event', 1, :now, "
                ":organization_id, '{}'::jsonb, '{}'::jsonb, :correlation_id, '{}'::jsonb)"
            ),
            {
                "id": outbox_id,
                "event_id": event_id,
                "now": now,
                "organization_id": owned_org_id,
                "correlation_id": uuid7(),
            },
        )
        connection.execute(
            text(
                "INSERT INTO event_delivery "
                "(id, created_at, updated_at, outbox_message_id, event_id, "
                "organization_id, handler_name, status, attempt_count) "
                "VALUES (:id, :now, :now, :outbox_id, :event_id, :organization_id, "
                "'legacy.handler', CAST('PENDING' AS eventdeliverystatus), 0)"
            ),
            {
                "id": uuid7(),
                "now": now,
                "outbox_id": outbox_id,
                "event_id": event_id,
                "organization_id": owned_org_id,
            },
        )
        connection.execute(
            text(
                "INSERT INTO user_organization "
                "(id, created_at, updated_at, user_id, organization_id, role) "
                "VALUES (:id, :now, :now, :user_id, :organization_id, "
                "CAST('OWNER' AS organizationrole))"
            ),
            {
                "id": uuid7(),
                "now": now,
                "user_id": owner_id,
                "organization_id": owned_org_id,
            },
        )

    command.upgrade(legacy_af237_database.config, CURRENT_REVISION)

    with legacy_af237_database.engine.connect() as connection:
        result = connection.execute(
            text("SELECT id, created_by_user_id FROM organization WHERE id IN (:owned_id, :ownerless_id)"),
            {
                "owned_id": owned_org_id,
                "ownerless_id": ownerless_org_id,
            },
        )
        rows = {row.id: row.created_by_user_id for row in result}
        event_scopes = set(
            connection.execute(
                text(
                    "SELECT DISTINCT event_scope FROM event_outbox_message "
                    "UNION SELECT DISTINCT event_scope FROM event_delivery"
                )
            ).scalars()
        )
        connection.execute(
            text("DELETE FROM organization WHERE id = :organization_id"),
            {"organization_id": owned_org_id},
        )
        retained_events = (
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM event_outbox_message WHERE event_id = :event_id "
                    "UNION ALL SELECT COUNT(*) FROM event_delivery WHERE event_id = :event_id"
                ),
                {"event_id": event_id},
            )
            .scalars()
            .all()
        )

    assert_that(rows[owned_org_id], equal_to(owner_id))
    assert_that(rows[ownerless_org_id], is_(None))
    assert_that(event_scopes, equal_to({"ORGANIZATION"}))
    assert_that(retained_events, equal_to([1, 1]))
