"""Full upgrade/backfill verification for the completed Skill library migration
(b6c7d8e9f0a1) against realistic pre-migration data.

api/tests/unit/test_skill_library_migration.py exercises the migration's pure
helper functions in isolation. It never runs the migration's actual
_normalize_existing_files orchestration against real rows, and the shared
session-scoped test database (api/tests/conftest.py) only ever upgrades an
empty schema — so the backfill path that matters most in production (rewriting
years of already-seeded aai-cli content and legacy join-table rows) had no
coverage. This module seeds a legacy-shaped database at the migration's
down_revision, runs the upgrade, and asserts the resulting normalization.
"""

import io
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from hamcrest import assert_that, contains_string, equal_to, is_, not_, not_none
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

PRE_MIGRATION_REVISION = "9b4c7d2e6f10"
CURRENT_REVISION = "b6c7d8e9f0a1"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture
def database_before_skill_library_migration(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"skill_library_{uuid7().hex}"
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


def test_migration_isolates_a_shared_builtin_root_and_rewrites_every_reference(
    database_before_skill_library_migration,
):
    """A pre-migration aai-cli skill shares the "aai-cli" root and a legacy
    entry filename. The migration must: give it its own aai-<slug> root, rename
    its entry point to SKILL.md in every version and the open draft, rewrite
    every ./skills/aai-cli/<old-entry> mount reference in file content and in
    template Markdown, backfill skill_version onto legacy join rows to the
    latest published version, and drop the legacy zip_content column."""
    database = database_before_skill_library_migration
    skill_id = uuid7()
    version_1_id = uuid7()
    version_2_id = uuid7()
    draft_id = uuid7()
    template_id = uuid7()
    join_id = uuid7()
    created_at = datetime(2026, 7, 1, tzinfo=UTC)

    old_pointer = "./skills/aai-cli/jira_skill.md"

    with database.engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO skill (
                    id, created_at, updated_at, organization_id, name, slug,
                    description, root_dir, entry_path, source, required_providers, tools_pointer
                )
                VALUES (
                    :id, :created_at, :updated_at, NULL, 'Jira', 'jira',
                    'Work with Jira issues.', 'aai-cli', 'jira_skill.md', 'aai_cli', '["jira"]'::json,
                    :tools_pointer
                )
                """
            ),
            {
                "id": skill_id,
                "created_at": created_at,
                "updated_at": created_at,
                "tools_pointer": f"\nFor Jira, use the aai-cli tool. See {old_pointer}\n",
            },
        )

        for version_id, version_number in ((version_1_id, 1), (version_2_id, 2)):
            connection.execute(
                text(
                    """
                    INSERT INTO skill_version (id, created_at, updated_at, skill_id, version)
                    VALUES (:id, :created_at, :updated_at, :skill_id, :version)
                    """
                ),
                {
                    "id": version_id,
                    "created_at": created_at,
                    "updated_at": created_at,
                    "skill_id": skill_id,
                    "version": version_number,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO skill_file (id, created_at, updated_at, skill_version_id, path, content)
                    VALUES
                        (:entry_id, :created_at, :updated_at, :version_id, 'jira_skill.md', :entry_content),
                        (:notes_id, :created_at, :updated_at, :version_id, 'helpers/notes.md', :notes_content)
                    """
                ),
                {
                    "entry_id": uuid7(),
                    "notes_id": uuid7(),
                    "created_at": created_at,
                    "updated_at": created_at,
                    "version_id": version_id,
                    "entry_content": f"# Jira v{version_number}\n\nSee {old_pointer} for details.",
                    "notes_content": f"v{version_number} notes also reference {old_pointer}.",
                },
            )

        connection.execute(
            text(
                """
                INSERT INTO skill_draft (id, created_at, updated_at, skill_id, description, required_providers)
                VALUES (:id, :created_at, :updated_at, :skill_id, NULL, '["jira"]'::json)
                """
            ),
            {"id": draft_id, "created_at": created_at, "updated_at": created_at, "skill_id": skill_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO skill_draft_file (id, created_at, updated_at, skill_draft_id, path, content)
                VALUES (:id, :created_at, :updated_at, :draft_id, 'jira_skill.md', :content)
                """
            ),
            {
                "id": uuid7(),
                "created_at": created_at,
                "updated_at": created_at,
                "draft_id": draft_id,
                "content": f"# Draft. Still points at {old_pointer}.",
            },
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
                    :id, :created_at, :updated_at, 'migration-skill-lib', 'Migration Skill Lib', 1,
                    NULL, '# Soul', '# Identity', '# Users', :tools_md, '# Agents',
                    '# Boot', '# Bootstrap', '# Heartbeat'
                )
                """
            ),
            {
                "id": template_id,
                "created_at": created_at,
                "updated_at": created_at,
                "tools_md": f"For Jira, use the aai-cli tool. See {old_pointer}\n",
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO platform_template_skill (id, created_at, updated_at, template_id, skill_id)
                VALUES (:id, :created_at, :updated_at, :template_id, :skill_id)
                """
            ),
            {
                "id": join_id,
                "created_at": created_at,
                "updated_at": created_at,
                "template_id": template_id,
                "skill_id": skill_id,
            },
        )

    command.upgrade(database.config, CURRENT_REVISION)

    new_pointer = "./skills/aai-jira/SKILL.md"
    with database.engine.connect() as connection:
        skill_row = connection.execute(
            text("SELECT slug, root_dir, entry_path, tools_pointer FROM skill WHERE id = :id"),
            {"id": skill_id},
        ).one()
        version_files = {
            version_number: {
                row.path: row.content
                for row in connection.execute(
                    text(
                        """
                        SELECT skill_file.path, skill_file.content
                        FROM skill_file
                        JOIN skill_version ON skill_version.id = skill_file.skill_version_id
                        WHERE skill_version.skill_id = :skill_id AND skill_version.version = :version
                        """
                    ),
                    {"skill_id": skill_id, "version": version_number},
                ).all()
            }
            for version_number in (1, 2)
        }
        version_rows = connection.execute(
            text(
                "SELECT version, description, required_providers FROM skill_version "
                "WHERE skill_id = :skill_id ORDER BY version"
            ),
            {"skill_id": skill_id},
        ).all()
        draft_files = {
            row.path: row.content
            for row in connection.execute(
                text("SELECT path, content FROM skill_draft_file WHERE skill_draft_id = :draft_id"),
                {"draft_id": draft_id},
            ).all()
        }
        template_tools_md = connection.execute(
            text("SELECT tools_md FROM platform_template WHERE id = :id"), {"id": template_id}
        ).scalar_one()
        join_skill_version = connection.execute(
            text("SELECT skill_version FROM platform_template_skill WHERE id = :id"), {"id": join_id}
        ).scalar_one()
        zip_column_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_name = 'skill' AND column_name = 'zip_content'"
            )
        ).scalar_one()
        agent_id_column_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_name = 'skill' AND column_name = 'agent_id'"
            )
        ).scalar_one()

    # The lineage gets its own isolated root and a canonical SKILL.md entry.
    assert_that(
        (skill_row.slug, skill_row.root_dir, skill_row.entry_path), equal_to(("aai-jira", "aai-jira", "SKILL.md"))
    )
    assert_that(skill_row.tools_pointer, contains_string(new_pointer))
    assert_that(skill_row.tools_pointer, is_(not_none()))

    # Every version's entry file is renamed and every file's content is rewritten —
    # not just the entry file, and not just the latest version.
    for version_number in (1, 2):
        files = version_files[version_number]
        assert_that(set(files), equal_to({"SKILL.md", "helpers/notes.md"}))
        assert_that(files["SKILL.md"], contains_string(new_pointer))
        assert_that(files["SKILL.md"], contains_string(f"Jira v{version_number}"))
        assert_that(files["helpers/notes.md"], contains_string(new_pointer))

    # skill_version.description/required_providers are backfilled from the
    # lineage row (they didn't exist pre-migration).
    for row in version_rows:
        assert_that(row.description, equal_to("Work with Jira issues."))
        assert_that(list(row.required_providers), equal_to(["jira"]))

    # The open draft is normalized identically to published versions.
    assert_that(set(draft_files), equal_to({"SKILL.md"}))
    assert_that(draft_files["SKILL.md"], contains_string(new_pointer))

    # Template Markdown referencing the old mount is rewritten too, and the old
    # reference does not linger alongside the new one.
    assert_that(template_tools_md, contains_string(new_pointer))
    assert_that(template_tools_md, not_(contains_string("aai-cli/jira_skill.md")))

    # The legacy join row (no skill_version column pre-migration) is backfilled
    # to the lineage's latest published version.
    assert_that(join_skill_version, equal_to(2))

    # Migration input only: the ZIP column is gone in steady state.
    assert_that(zip_column_count, equal_to(0))
    assert_that(agent_id_column_count, equal_to(1))


def test_migration_does_not_rename_a_custom_skills_own_root(database_before_skill_library_migration):
    """Only aai-cli lineages get the aai-<slug> prefix. A pre-migration custom
    (organization-owned) skill already has its own dedicated root and must keep
    it — otherwise every organization's custom skill would be renamed for no
    reason and any hand-authored links to it would break."""
    database = database_before_skill_library_migration
    organization_id = uuid7()
    skill_id = uuid7()
    version_id = uuid7()
    created_at = datetime(2026, 7, 1, tzinfo=UTC)

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
                INSERT INTO skill (
                    id, created_at, updated_at, organization_id, name, slug,
                    description, root_dir, entry_path, source, required_providers, tools_pointer
                )
                VALUES (
                    :id, :created_at, :updated_at, :organization_id, 'My Tool', 'my-tool',
                    NULL, 'my-tool', 'SKILL.md', 'custom', '[]'::json, NULL
                )
                """
            ),
            {
                "id": skill_id,
                "created_at": created_at,
                "updated_at": created_at,
                "organization_id": organization_id,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO skill_version (id, created_at, updated_at, skill_id, version)
                VALUES (:id, :created_at, :updated_at, :skill_id, 1)
                """
            ),
            {"id": version_id, "created_at": created_at, "updated_at": created_at, "skill_id": skill_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO skill_file (id, created_at, updated_at, skill_version_id, path, content)
                VALUES (:id, :created_at, :updated_at, :version_id, 'SKILL.md', '# My Tool')
                """
            ),
            {"id": uuid7(), "created_at": created_at, "updated_at": created_at, "version_id": version_id},
        )

    command.upgrade(database.config, CURRENT_REVISION)

    with database.engine.connect() as connection:
        skill_row = connection.execute(
            text("SELECT slug, root_dir, entry_path FROM skill WHERE id = :id"), {"id": skill_id}
        ).one()

    assert_that(
        (skill_row.slug, skill_row.root_dir, skill_row.entry_path), equal_to(("my-tool", "my-tool", "SKILL.md"))
    )


def test_migration_downgrade_restores_zip_content_from_the_normalized_snapshot(
    database_before_skill_library_migration,
):
    """Operators may need to roll back a bad deploy. Downgrading must rehydrate
    a working zip_content from whatever the current (already-normalized) latest
    version looks like, not silently drop content or leave the column empty."""
    database = database_before_skill_library_migration
    skill_id = uuid7()
    version_id = uuid7()
    created_at = datetime(2026, 7, 1, tzinfo=UTC)

    with database.engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO skill (
                    id, created_at, updated_at, organization_id, name, slug,
                    description, root_dir, entry_path, source, required_providers, tools_pointer
                )
                VALUES (
                    :id, :created_at, :updated_at, NULL, 'Slack', 'slack',
                    NULL, 'aai-cli', 'slack_skill.md', 'aai_cli', '["slack"]'::json, NULL
                )
                """
            ),
            {"id": skill_id, "created_at": created_at, "updated_at": created_at},
        )
        connection.execute(
            text(
                """
                INSERT INTO skill_version (id, created_at, updated_at, skill_id, version)
                VALUES (:id, :created_at, :updated_at, :skill_id, 1)
                """
            ),
            {"id": version_id, "created_at": created_at, "updated_at": created_at, "skill_id": skill_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO skill_file (id, created_at, updated_at, skill_version_id, path, content)
                VALUES (:id, :created_at, :updated_at, :version_id, 'slack_skill.md', '# Slack')
                """
            ),
            {"id": uuid7(), "created_at": created_at, "updated_at": created_at, "version_id": version_id},
        )

    command.upgrade(database.config, CURRENT_REVISION)
    command.downgrade(database.config, PRE_MIGRATION_REVISION)

    with database.engine.connect() as connection:
        zip_bytes = connection.execute(
            text("SELECT zip_content FROM skill WHERE id = :id"), {"id": skill_id}
        ).scalar_one()
        agent_id_column_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_name = 'skill' AND column_name = 'agent_id'"
            )
        ).scalar_one()

    assert_that(zip_bytes, is_(not_none()))
    with zipfile.ZipFile(io.BytesIO(bytes(zip_bytes))) as archive:
        assert_that(archive.namelist(), equal_to(["aai-slack/SKILL.md"]))
        assert_that(archive.read("aai-slack/SKILL.md").decode(), equal_to("# Slack"))
    assert_that(agent_id_column_count, equal_to(0))
