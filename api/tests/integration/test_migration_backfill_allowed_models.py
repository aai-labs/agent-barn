import subprocess
import os
from uuid import uuid7
from sqlalchemy import text, create_engine
from hamcrest import assert_that, equal_to

from api.core.config import get_config


def test_backfill_allowed_models_migration():
    engine = create_engine(str(get_config().db_connection_url))

    # We will use alembic CLI via subprocess since it's reliable
    api_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..", "api"))
    env = os.environ.copy()
    env["AGENT_MODEL_ALLOWLIST"] = "openai/*,anthropic/*"

    # Revisions
    target_revision = "181dcfcc93ef"
    previous_revision = f"{target_revision}-1"

    org_id = str(uuid7())

    try:
        # Downgrade to right before our migration
        subprocess.run(
            ["uv", "run", "python", "-m", "alembic", "downgrade", previous_revision],
            cwd=api_dir,
            env=env,
            check=True,
        )

        # Insert a raw organization (simulating pre-migration state where allowed_models does not exist)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO organization (id, name, is_default, created_at, updated_at) VALUES (:id, 'Old Org', false, now(), now())"
                ),
                {"id": org_id},
            )

        # Upgrade through our migration
        subprocess.run(
            ["uv", "run", "python", "-m", "alembic", "upgrade", target_revision],
            cwd=api_dir,
            env=env,
            check=True,
        )

        # Verify backfill
        with engine.begin() as conn:
            result = conn.execute(
                text("SELECT allowed_models FROM organization WHERE id = :id"),
                {"id": org_id},
            ).fetchone()

            assert_that(result, equal_to((["openai/*", "anthropic/*"],)))

    finally:
        # Cleanup: Ensure we return to head and delete the test org
        subprocess.run(
            ["uv", "run", "python", "-m", "alembic", "upgrade", "head"],
            cwd=api_dir,
            env=env,
            check=False,  # Don't fail the finally block if already at head
        )
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM organization WHERE id = :id"), {"id": org_id})


def test_backfill_allowed_models_migration_empty_config_allows_all():
    """Old semantics: an empty/unset AGENT_MODEL_ALLOWLIST meant "allow everything".
    The new per-org allowlist treats an empty list as "block everything", so the
    backfill must map an empty config to ["*"], not []."""
    engine = create_engine(str(get_config().db_connection_url))

    api_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..", "api"))
    env = os.environ.copy()
    env["AGENT_MODEL_ALLOWLIST"] = ""

    target_revision = "181dcfcc93ef"
    previous_revision = f"{target_revision}-1"

    org_id = str(uuid7())

    try:
        subprocess.run(
            ["uv", "run", "python", "-m", "alembic", "downgrade", previous_revision],
            cwd=api_dir,
            env=env,
            check=True,
        )

        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO organization (id, name, is_default, created_at, updated_at) VALUES (:id, 'Old Org', false, now(), now())"
                ),
                {"id": org_id},
            )

        subprocess.run(
            ["uv", "run", "python", "-m", "alembic", "upgrade", target_revision],
            cwd=api_dir,
            env=env,
            check=True,
        )

        with engine.begin() as conn:
            result = conn.execute(
                text("SELECT allowed_models FROM organization WHERE id = :id"),
                {"id": org_id},
            ).fetchone()

            assert_that(result, equal_to((["*"],)))

    finally:
        subprocess.run(
            ["uv", "run", "python", "-m", "alembic", "upgrade", "head"],
            cwd=api_dir,
            env=env,
            check=False,
        )
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM organization WHERE id = :id"), {"id": org_id})
