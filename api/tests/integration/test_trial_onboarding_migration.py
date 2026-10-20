"""AF-368 migration: Google sign-in and trial columns, and the platform trial settings
row. It downgrades cleanly, upgrades again, and leaves a schema that matches the models."""

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

# Every model module must be imported for the metadata comparison to see its tables.
import api.domains.onboarding.models
import api.domains.organizations.models
import api.domains.users.models  # noqa: F401
from api.core.config import get_config

PRE_AF368_REVISION = "b3c9e1f2a7d4"
AF368_HEAD = "b3d8e1f4a6c2"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
AF368_COLUMNS = {
    ("user", "google_sub"),
    ("user", "signed_up_at"),
    ("user", "trial_ended_at"),
    ("user", "onboarding_completed_at"),
    ("organization", "is_trial"),
    ("platform_trial_settings", "agent_limit"),
    ("platform_trial_settings", "max_active_trials"),
}
AF368_TABLES = {"platform_trial_settings", "trial_grant"}


@pytest.fixture
def scratch_database(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"af368_{uuid7().hex}"
    target_url = source_url.set(database=database_name)
    admin_engine = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    monkeypatch.setenv("ALEMBIC_DB_URL", target_url.render_as_string(False))
    engine = create_engine(target_url)
    try:
        yield SimpleNamespace(config=Config(ALEMBIC_INI), engine=engine)
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    f"WHERE datname = '{database_name}' AND pid <> pg_backend_pid()"
                )
            )
            connection.execute(text(f'DROP DATABASE "{database_name}"'))
        admin_engine.dispose()


def _af368_objects(engine) -> tuple[set[tuple[str, str]], set[str]]:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    columns = {
        (table, column["name"])
        for table in ("user", "organization", "platform_trial_settings")
        if table in tables
        for column in inspector.get_columns(table)
        if (table, column["name"]) in AF368_COLUMNS
    }
    return columns, tables & AF368_TABLES


def test_trial_onboarding_downgrades_cleanly_and_upgrades_again(scratch_database):
    command.upgrade(scratch_database.config, AF368_HEAD)
    assert_that(_af368_objects(scratch_database.engine), equal_to((AF368_COLUMNS, AF368_TABLES)))

    command.downgrade(scratch_database.config, PRE_AF368_REVISION)
    scratch_database.engine.dispose()
    assert_that(_af368_objects(scratch_database.engine), equal_to((set(), set())))

    command.upgrade(scratch_database.config, AF368_HEAD)
    scratch_database.engine.dispose()
    assert_that(_af368_objects(scratch_database.engine), equal_to((AF368_COLUMNS, AF368_TABLES)))


def test_existing_organizations_are_not_trials_after_upgrade(scratch_database):
    command.upgrade(scratch_database.config, PRE_AF368_REVISION)
    organization_id = uuid7()
    with scratch_database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO organization (id, created_at, updated_at, name, allowed_models, llm_budget_usd, "
                "llm_budget_duration) VALUES (:id, now(), now(), 'Existing Org', '[]', 100, '30d')"
            ),
            {"id": organization_id},
        )

    command.upgrade(scratch_database.config, AF368_HEAD)
    scratch_database.engine.dispose()

    with scratch_database.engine.connect() as connection:
        is_trial = connection.execute(
            text("SELECT is_trial FROM organization WHERE id = :id"), {"id": organization_id}
        ).scalar_one()
    assert_that(is_trial, equal_to(False))


def test_the_migrated_schema_matches_the_models_for_trial_onboarding():
    engine = create_engine(str(get_config().db_connection_url))
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), SQLModel.metadata)
    ours = [
        diff
        for diff in differences
        if any(
            name in repr(diff)
            for name in (
                "google_sub",
                "signed_up_at",
                "trial_ended_at",
                "onboarding_completed_at",
                "is_trial",
                "trial_settings",
                "trial_grant",
                "agent_limit",
                "max_active_trials",
            )
        )
    ]

    assert_that(ours, equal_to([]))


def test_signup_policy_upgrade_constraint_and_downgrade(scratch_database):
    command.upgrade(scratch_database.config, AF368_HEAD)
    with scratch_database.engine.begin() as connection:
        connection.execute(
            text("INSERT INTO platform_trial_settings (id, credit_usd, updated_at) VALUES (1, 0, now())")
        )
    command.upgrade(scratch_database.config, "head")
    with scratch_database.engine.connect() as connection:
        assert_that(
            connection.execute(text("SELECT self_signup_enabled FROM platform_trial_settings")).scalar_one(),
            equal_to(False),
        )
    with pytest.raises(IntegrityError), scratch_database.engine.begin() as connection:
        connection.execute(text("UPDATE platform_trial_settings SET self_signup_enabled = true"))
    with scratch_database.engine.begin() as connection:
        connection.execute(text("UPDATE platform_trial_settings SET self_signup_enabled = true, credit_usd = 20"))
    command.downgrade(scratch_database.config, AF368_HEAD)
    with scratch_database.engine.connect() as connection:
        assert_that(
            connection.execute(text("SELECT credit_usd FROM platform_trial_settings")).scalar_one(), equal_to(20)
        )
    command.upgrade(scratch_database.config, "head")
    with scratch_database.engine.connect() as connection:
        assert_that(
            connection.execute(text("SELECT self_signup_enabled FROM platform_trial_settings")).scalar_one(),
            equal_to(False),
        )


# Existing membership-free users need a one-time data backfill, not a recovery API.
LEGACY_ORG_BASE = "c61a94e72b30"


def test_existing_users_receive_organizations_once_without_touching_trials_or_invitations(scratch_database):
    command.upgrade(scratch_database.config, LEGACY_ORG_BASE)
    users = {
        "legacy": {"name": "  Jane Doe  ", "verified": True},
        "unnamed": {"name": None, "verified": True},
        "long_name": {"name": "L" * 300, "verified": True},
        "owner": {"name": "Owner", "verified": True},
        "invited": {"name": "Invited", "verified": True},
        "pending_invite": {"name": "Pending", "verified": False},
        "unverified": {"name": "Unverified", "verified": False},
        "platform_admin": {"name": "Admin", "verified": True, "admin": True},
        "deleted_trial": {"name": "Trial", "verified": True, "signup": True},
        "ended_trial": {"name": "Ended", "verified": True, "signup": True, "ended": True},
    }
    user_ids = {key: uuid7() for key in users}
    existing_org = uuid7()
    with scratch_database.engine.begin() as connection:
        for key, user in users.items():
            connection.execute(
                text(
                    'INSERT INTO "user" (id, created_at, updated_at, full_name, email, hashed_password, '
                    "security_stamp, is_platform_admin, email_verified_at, signed_up_at, trial_ended_at) "
                    "VALUES (:id, now(), now(), :name, :email, :password, :stamp, :admin, "
                    "CASE WHEN :verified THEN now() ELSE NULL END, "
                    "CASE WHEN :signup THEN now() ELSE NULL END, CASE WHEN :ended THEN now() ELSE NULL END)"
                ),
                {
                    "id": user_ids[key],
                    "name": user["name"],
                    "email": f"{key}@example.com",
                    "password": "fixture-unusable-hash",
                    "stamp": uuid7().hex,
                    "admin": user.get("admin", False),
                    "verified": user["verified"],
                    "signup": user.get("signup", False),
                    "ended": user.get("ended", False),
                },
            )
        connection.execute(
            text(
                "INSERT INTO organization (id, created_at, updated_at, name, created_by_user_id, allowed_models, llm_budget_usd, llm_budget_duration) "
                "VALUES (:id, now(), now(), 'Existing team', :creator, '[]', 50, '30d')"
            ),
            {"id": existing_org, "creator": user_ids["owner"]},
        )
        for key in ("owner", "invited", "pending_invite"):
            connection.execute(
                text(
                    "INSERT INTO user_organization (id, created_at, updated_at, user_id, organization_id, role) "
                    "VALUES (:id, now(), now(), :user_id, :org_id, :role)"
                ),
                {
                    "id": uuid7(),
                    "user_id": user_ids[key],
                    "org_id": existing_org,
                    "role": "OWNER" if key == "owner" else "MEMBER",
                },
            )

    command.upgrade(scratch_database.config, "head")
    with scratch_database.engine.connect() as connection:
        memberships = (
            connection.execute(
                text(
                    "SELECT m.user_id, m.role, o.id, o.name, o.created_by_user_id, o.is_trial, o.llm_budget_usd, o.llm_budget_duration, o.allowed_models "
                    "FROM user_organization m JOIN organization o ON o.id = m.organization_id"
                )
            )
            .mappings()
            .all()
        )
        by_user = {row["user_id"]: row for row in memberships}
        assert_that(len(memberships), equal_to(6))
        for key, name in (
            ("legacy", "Jane's Organization"),
            ("unnamed", "My Organization"),
            ("long_name", "L" * 240 + "'s Organization"),
        ):
            row = by_user[user_ids[key]]
            assert_that(row["name"], equal_to(name))
            assert_that(row["role"], equal_to("OWNER"))
            assert_that(row["created_by_user_id"], equal_to(user_ids[key]))
            assert_that(row["is_trial"], equal_to(False))
            assert_that(row["llm_budget_usd"], equal_to(get_config().organization_default_llm_budget_usd))
            assert_that(row["llm_budget_duration"], equal_to("30d"))
            assert_that(
                row["allowed_models"], equal_to([get_config().agent_default_model.removeprefix("litellm/openrouter/")])
            )
        for key in ("owner", "invited", "pending_invite"):
            assert_that(by_user[user_ids[key]]["id"], equal_to(existing_org))
        assert_that(connection.execute(text("SELECT count(*) FROM agent")).scalar_one(), equal_to(0))
        assert_that(connection.execute(text("SELECT count(*) FROM trial_grant")).scalar_one(), equal_to(0))
        snapshot = {row["user_id"]: row["id"] for row in memberships}

    # Reapplying a data migration must preserve any Organization that can now hold work.
    command.downgrade(scratch_database.config, LEGACY_ORG_BASE)
    command.upgrade(scratch_database.config, "head")
    with scratch_database.engine.connect() as connection:
        actual = dict(connection.execute(text("SELECT user_id, organization_id FROM user_organization")).all())
        assert_that(actual, equal_to(snapshot))
