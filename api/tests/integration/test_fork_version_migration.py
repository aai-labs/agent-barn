import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from hamcrest import assert_that, equal_to
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

PRE_MIGRATION_REVISION = "d222461d5cd9"
CURRENT_REVISION = "f6a7b8c9d0e1"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture
def database_before_fork_version_migration(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"fork_versions_{uuid7().hex}"
    admin_engine = create_engine(
        source_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )
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


def test_migration_normalizes_org_fork_versions_and_backfills_baseline_version(
    database_before_fork_version_migration,
):
    database = database_before_fork_version_migration
    organization_id = uuid7()
    platform_id = uuid7()
    fork_ids = [uuid7() for _ in range(3)]
    custom_id = uuid7()
    created_at = datetime(2026, 7, 31, tzinfo=UTC)

    with database.engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO organization (id, created_at, updated_at, name, allowed_models)
                VALUES (:id, :created_at, :updated_at, 'Migration Test Org', '[]'::jsonb)
                """
            ),
            {"id": organization_id, "created_at": created_at, "updated_at": created_at},
        )
        connection.execute(
            text(
                """
                INSERT INTO platform_template (
                    id, created_at, updated_at, template_key, template_name, version,
                    description, soul_md, identity_md, user_md, tools_md, agents_md,
                    boot_md, bootstrap_md, heartbeat_md
                )
                VALUES (
                    :id, :created_at, :updated_at, 'migration-fork', 'Migration Fork', 1,
                    NULL, '# Soul', '# Identity', '# Users', '# Tools', '# Agents',
                    '# Boot', '# Bootstrap', '# Heartbeat'
                )
                """
            ),
            {"id": platform_id, "created_at": created_at, "updated_at": created_at},
        )

        for index, template_id in enumerate(fork_ids, start=1):
            row_created_at = created_at + timedelta(minutes=index)
            connection.execute(
                text(
                    """
                    INSERT INTO agent_template (
                        id, created_at, updated_at, organization_id,
                        forked_from_platform_template_id,
                        fork_baseline_platform_template_id,
                        template_key, template_name, template_source, version,
                        description, soul_md, identity_md, user_md, tools_md, agents_md,
                        boot_md, bootstrap_md, heartbeat_md
                    )
                    VALUES (
                        :id, :created_at, :updated_at, :organization_id,
                        :platform_id, :platform_id,
                        'migration-fork', 'Migration Fork', 'pre-defined', :version,
                        NULL, '# Soul', '# Identity', '# Users', '# Tools', '# Agents',
                        '# Boot', '# Bootstrap', '# Heartbeat'
                    )
                    """
                ),
                {
                    "id": template_id,
                    "created_at": row_created_at,
                    "updated_at": row_created_at,
                    "organization_id": organization_id,
                    "platform_id": platform_id,
                    "version": index + 1,
                },
            )

        connection.execute(
            text(
                """
                INSERT INTO agent_template (
                    id, created_at, updated_at, organization_id,
                    template_key, template_name, template_source, version,
                    description, soul_md, identity_md, user_md, tools_md, agents_md,
                    boot_md, bootstrap_md, heartbeat_md
                )
                VALUES (
                    :id, :created_at, :updated_at, :organization_id,
                    'migration-custom', 'Migration Custom', 'custom', 1,
                    NULL, '# Soul', '# Identity', '# Users', '# Tools', '# Agents',
                    '# Boot', '# Bootstrap', '# Heartbeat'
                )
                """
            ),
            {
                "id": custom_id,
                "created_at": created_at,
                "updated_at": created_at,
                "organization_id": organization_id,
            },
        )

    command.upgrade(database.config, CURRENT_REVISION)

    with database.engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT id, version, fork_baseline_platform_version
                FROM agent_template
                WHERE id = ANY(:template_ids)
                ORDER BY created_at, id
                """
            ),
            {"template_ids": fork_ids},
        ).all()
        custom = connection.execute(
            text(
                """
                SELECT version, fork_baseline_platform_version
                FROM agent_template
                WHERE id = :id
                """
            ),
            {"id": custom_id},
        ).one()

    assert_that(
        [(row.id, row.version, row.fork_baseline_platform_version) for row in rows],
        equal_to(
            [
                (fork_ids[0], 1, 1),
                (fork_ids[1], 2, 1),
                (fork_ids[2], 3, 1),
            ]
        ),
    )
    assert_that((custom.version, custom.fork_baseline_platform_version), equal_to((1, None)))

    command.downgrade(database.config, PRE_MIGRATION_REVISION)

    with database.engine.connect() as connection:
        legacy_rows = connection.execute(
            text(
                """
                SELECT id, version
                FROM agent_template
                WHERE organization_id = :organization_id
                  AND template_key = 'migration-fork'
                ORDER BY created_at, id
                """
            ),
            {"organization_id": organization_id},
        ).all()
        baseline_column_count = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_name = 'agent_template'
                  AND column_name = 'fork_baseline_platform_version'
                """
            )
        ).scalar_one()

    assert_that(
        [(row.id, row.version) for row in legacy_rows],
        equal_to(
            [
                (fork_ids[0], 2),
                (fork_ids[1], 3),
                (fork_ids[2], 4),
            ]
        ),
    )
    assert_that(baseline_column_count, equal_to(0))
