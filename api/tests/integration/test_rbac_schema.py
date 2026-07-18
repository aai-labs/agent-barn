import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from hamcrest import assert_that, calling, equal_to, none, raises
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError

from api.core.config import Config as AppConfig
from api.domains.rbac.catalog import (
    ADMIN_ROLE_ID,
    MEMBER_ROLE_ID,
    OWNER_ROLE_ID,
    PERMISSION_ID_BY_KEY,
    PERMISSIONS,
    SYSTEM_ROLE_GRANTS,
    PermissionKey,
)
from api.domains.rbac.repository import RbacRepository
from api.domains.rbac.seeder import RbacSeedConflictError, RbacSeeder
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

PRE_RBAC_REVISION = "d3f9a1c7b2e5"
RBAC_REVISION = "a6f2c9d18e47"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture
def isolated_database(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"rbac_{uuid7().hex}"
    target_url = source_url.set(database=database_name)
    admin_url = source_url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")

    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))

    monkeypatch.setenv("ALEMBIC_DB_URL", target_url.render_as_string(False))
    try:
        yield target_url
    finally:
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


def _alembic_config() -> Config:
    return Config(ALEMBIC_INI)


def _seeder_for(url: URL) -> RbacSeeder:
    config = AppConfig.model_construct(db_connection_url=url.render_as_string(False))
    delegate = PostgresRepositoryDelegate(config)
    return RbacSeeder(repository=RbacRepository(delegate=delegate))


@pytest.fixture
def fresh_database(isolated_database):
    command.upgrade(_alembic_config(), "heads")
    engine = create_engine(isolated_database)
    try:
        yield SimpleNamespace(url=isolated_database, engine=engine)
    finally:
        engine.dispose()


@pytest.fixture
def legacy_database(isolated_database):
    config = _alembic_config()
    command.upgrade(config, PRE_RBAC_REVISION)
    engine = create_engine(isolated_database)

    org_a, org_b = uuid7(), uuid7()
    owner, member, admin = uuid7(), uuid7(), uuid7()
    owner_membership, member_membership, admin_membership = uuid7(), uuid7(), uuid7()
    agent_a, deleted_agent_a, agent_b = uuid7(), uuid7(), uuid7()
    now = "2026-07-18T00:00:00+00:00"

    with engine.begin() as connection:
        for org_id, name in ((org_a, "Org A"), (org_b, "Org B")):
            connection.execute(
                text(
                    "INSERT INTO organization "
                    "(id, created_at, updated_at, name, description, is_default) "
                    "VALUES (:id, :now, :now, :name, NULL, false)"
                ),
                {"id": org_id, "now": now, "name": name},
            )
        for user_id, email in (
            (owner, "owner@example.com"),
            (member, "member@example.com"),
            (admin, "admin@example.com"),
        ):
            connection.execute(
                text(
                    'INSERT INTO "user" '
                    "(id, created_at, updated_at, email, full_name, hashed_password, "
                    "is_superuser, security_stamp, email_verified_at) "
                    "VALUES (:id, :now, :now, :email, NULL, :password, false, "
                    ":stamp, :now)"
                ),
                {
                    "id": user_id,
                    "now": now,
                    "email": email,
                    "password": "hash",
                    "stamp": uuid7().hex,
                },
            )
        for membership_id, user_id, org_id, role in (
            (owner_membership, owner, org_a, "OWNER"),
            (member_membership, member, org_a, "MEMBER"),
            (admin_membership, admin, org_b, "ADMIN"),
        ):
            connection.execute(
                text(
                    "INSERT INTO user_organization "
                    "(id, created_at, updated_at, user_id, organization_id, role) "
                    "VALUES (:id, :now, :now, :user_id, :org_id, "
                    "CAST(:role AS organizationrole))"
                ),
                {
                    "id": membership_id,
                    "now": now,
                    "user_id": user_id,
                    "org_id": org_id,
                    "role": role,
                },
            )
        for org_id in (org_a, org_b):
            connection.execute(
                text(
                    "INSERT INTO agent_template "
                    "(id, created_at, updated_at, organization_id, template_slug, "
                    "template_name, template_source, version, description, soul_md, "
                    "identity_md, user_md, tools_md, agents_md, boot_md, bootstrap_md, "
                    "heartbeat_md) VALUES "
                    "(:id, :now, :now, :org_id, :slug, :name, :source, 1, NULL, "
                    ":body, :body, :body, :body, :body, :body, :body, :body)"
                ),
                {
                    "id": uuid7(),
                    "now": now,
                    "org_id": org_id,
                    "slug": "legacy",
                    "name": "Legacy",
                    "source": "custom",
                    "body": "legacy",
                },
            )
        for agent_id, org_id, deleted_at in (
            (agent_a, org_a, None),
            (deleted_agent_a, org_a, now),
            (agent_b, org_b, None),
        ):
            connection.execute(
                text(
                    "INSERT INTO agent "
                    "(id, created_at, updated_at, organization_id, name, "
                    "litellm_key_encrypted, status, deleted_at, template_slug, "
                    "template_version, model, platform, agent_type, last_error, "
                    "ingest_key_encrypted, approval_mode) VALUES "
                    "(:id, :now, :now, :org_id, :name, :key, "
                    "CAST(:status AS agentstatus), :deleted_at, :slug, 1, :model, "
                    ":platform, :agent_type, NULL, NULL, :approval_mode)"
                ),
                {
                    "id": agent_id,
                    "now": now,
                    "org_id": org_id,
                    "name": f"Agent {agent_id}",
                    "key": "",
                    "status": "STOPPED",
                    "deleted_at": deleted_at,
                    "slug": "legacy",
                    "model": "",
                    "platform": "slack",
                    "agent_type": "openclaw",
                    "approval_mode": "auto",
                },
            )

    command.upgrade(config, RBAC_REVISION)
    try:
        yield SimpleNamespace(
            config=config,
            engine=engine,
            now=now,
            org_a=org_a,
            org_b=org_b,
            owner=owner,
            member=member,
            admin=admin,
            owner_membership=owner_membership,
            member_membership=member_membership,
            admin_membership=admin_membership,
            agent_a=agent_a,
            deleted_agent_a=deleted_agent_a,
            agent_b=agent_b,
        )
    finally:
        engine.dispose()


def _execute(engine, statement: str, params: dict[str, object]) -> None:
    with engine.begin() as connection:
        connection.execute(text(statement), params)


def _insert_custom_role(db) -> object:
    role_id = uuid7()
    _execute(
        db.engine,
        "INSERT INTO roles "
        "(id, created_at, updated_at, organization_id, name, is_system) "
        "VALUES (:id, :now, :now, :org_id, :name, false)",
        {
            "id": role_id,
            "now": db.now,
            "org_id": db.org_b,
            "name": f"CUSTOM-{role_id}",
        },
    )
    return role_id


def test_fresh_upgrade_seeds_exact_system_catalogue(fresh_database):
    with fresh_database.engine.connect() as connection:
        actual = {
            "roles": dict(
                (name, role_id)
                for role_id, name in connection.execute(
                    text("SELECT id, name FROM roles WHERE is_system ORDER BY name")
                ).all()
            ),
            "permissions": dict(
                (key, permission_id)
                for permission_id, key in connection.execute(
                    text("SELECT id, key FROM permissions ORDER BY key")
                ).all()
            ),
            "grant_count": connection.execute(
                text("SELECT count(*) FROM role_permissions")
            ).scalar_one(),
            "legacy_enum_count": connection.execute(
                text("SELECT count(*) FROM pg_type WHERE typname = 'organizationrole'")
            ).scalar_one(),
        }

    assert_that(
        actual,
        equal_to(
            {
                "roles": {
                    "ADMIN": ADMIN_ROLE_ID,
                    "MEMBER": MEMBER_ROLE_ID,
                    "OWNER": OWNER_ROLE_ID,
                },
                "permissions": {
                    permission.key.value: permission.id for permission in PERMISSIONS
                },
                "grant_count": sum(
                    len(grants) for grants in SYSTEM_ROLE_GRANTS.values()
                ),
                "legacy_enum_count": 0,
            }
        ),
    )


def test_rbac_seeder_is_idempotent(fresh_database):
    seeder = _seeder_for(fresh_database.url)
    seeder.seed()
    seeder.seed()

    with fresh_database.engine.connect() as connection:
        counts = (
            connection.execute(text("SELECT count(*) FROM roles")).scalar_one(),
            connection.execute(text("SELECT count(*) FROM permissions")).scalar_one(),
            connection.execute(
                text("SELECT count(*) FROM role_permissions")
            ).scalar_one(),
        )

    assert_that(
        counts,
        equal_to(
            (
                3,
                len(PERMISSIONS),
                sum(len(grants) for grants in SYSTEM_ROLE_GRANTS.values()),
            )
        ),
    )


def test_rbac_seeder_rejects_unexpected_system_grant(fresh_database):
    unexpected_permission_id = PERMISSION_ID_BY_KEY[PermissionKey.ORGANIZATION_DELETE]
    _execute(
        fresh_database.engine,
        "INSERT INTO role_permissions (role_id, permission_id, scope) "
        "VALUES (:role_id, :permission_id, CAST(:scope AS permissionscope))",
        {
            "role_id": ADMIN_ROLE_ID,
            "permission_id": unexpected_permission_id,
            "scope": "ORGANIZATION",
        },
    )

    assert_that(
        calling(_seeder_for(fresh_database.url).seed),
        raises(RbacSeedConflictError),
    )


def test_rbac_seeder_rejects_conflicting_permission_identity(fresh_database):
    conflicting_permission = PERMISSIONS[0]
    with fresh_database.engine.begin() as connection:
        connection.execute(
            text("DELETE FROM permissions WHERE id = :id"),
            {"id": conflicting_permission.id},
        )
        connection.execute(
            text(
                "INSERT INTO permissions (id, created_at, updated_at, key) "
                "VALUES (:id, now(), now(), :key)"
            ),
            {"id": conflicting_permission.id, "key": "conflicting.permission"},
        )

    assert_that(
        calling(_seeder_for(fresh_database.url).seed),
        raises(RbacSeedConflictError),
    )


def test_upgrade_backfills_membership_roles(legacy_database):
    with legacy_database.engine.connect() as connection:
        actual = {
            row[0]: row[1]
            for row in connection.execute(
                text("SELECT id, role_id FROM user_organization")
            ).all()
        }

    assert_that(
        actual,
        equal_to(
            {
                legacy_database.owner_membership: OWNER_ROLE_ID,
                legacy_database.member_membership: MEMBER_ROLE_ID,
                legacy_database.admin_membership: ADMIN_ROLE_ID,
            }
        ),
    )


def test_upgrade_backfills_same_organization_agent_access(legacy_database):
    with legacy_database.engine.connect() as connection:
        actual = set(
            connection.execute(
                text(
                    "SELECT membership_id, agent_id, organization_id FROM agent_access"
                )
            ).all()
        )

    assert_that(
        actual,
        equal_to(
            {
                (
                    legacy_database.owner_membership,
                    legacy_database.agent_a,
                    legacy_database.org_a,
                ),
                (
                    legacy_database.owner_membership,
                    legacy_database.deleted_agent_a,
                    legacy_database.org_a,
                ),
                (
                    legacy_database.member_membership,
                    legacy_database.agent_a,
                    legacy_database.org_a,
                ),
                (
                    legacy_database.member_membership,
                    legacy_database.deleted_agent_a,
                    legacy_database.org_a,
                ),
                (
                    legacy_database.admin_membership,
                    legacy_database.agent_b,
                    legacy_database.org_b,
                ),
            }
        ),
    )


def test_upgrade_leaves_legacy_agent_creator_unknown(legacy_database):
    with legacy_database.engine.connect() as connection:
        creators = (
            connection.execute(text("SELECT created_by_user_id FROM agent"))
            .scalars()
            .all()
        )

    assert_that(creators, equal_to([None, None, None]))


def test_deleting_creator_sets_agent_provenance_to_null(legacy_database):
    with legacy_database.engine.begin() as connection:
        connection.execute(
            text("UPDATE agent SET created_by_user_id = :user_id WHERE id = :agent_id"),
            {"user_id": legacy_database.admin, "agent_id": legacy_database.agent_b},
        )
        connection.execute(
            text('DELETE FROM "user" WHERE id = :id'),
            {"id": legacy_database.admin},
        )
        creator = connection.execute(
            text("SELECT created_by_user_id FROM agent WHERE id = :id"),
            {"id": legacy_database.agent_b},
        ).scalar_one_or_none()

    assert_that(creator, none())


def test_deleting_membership_cascades_agent_access(legacy_database):
    with legacy_database.engine.begin() as connection:
        connection.execute(
            text("DELETE FROM user_organization WHERE id = :id"),
            {"id": legacy_database.member_membership},
        )
        access_count = connection.execute(
            text("SELECT count(*) FROM agent_access WHERE membership_id = :id"),
            {"id": legacy_database.member_membership},
        ).scalar_one()

    assert_that(access_count, equal_to(0))


def test_agent_access_rejects_cross_organization_assignment(legacy_database):
    assert_that(
        calling(_execute).with_args(
            legacy_database.engine,
            "INSERT INTO agent_access "
            "(id, created_at, updated_at, organization_id, membership_id, agent_id) "
            "VALUES (:id, :now, :now, :org_id, :membership_id, :agent_id)",
            {
                "id": uuid7(),
                "now": legacy_database.now,
                "org_id": legacy_database.org_b,
                "membership_id": legacy_database.member_membership,
                "agent_id": legacy_database.agent_b,
            },
        ),
        raises(IntegrityError),
    )


def test_membership_rejects_role_from_another_organization(legacy_database):
    custom_role_id = _insert_custom_role(legacy_database)

    assert_that(
        calling(_execute).with_args(
            legacy_database.engine,
            "UPDATE user_organization SET role_id = :role_id WHERE id = :membership_id",
            {
                "role_id": custom_role_id,
                "membership_id": legacy_database.member_membership,
            },
        ),
        raises(IntegrityError),
    )


def test_assigned_custom_role_scope_is_immutable(legacy_database):
    custom_role_id = _insert_custom_role(legacy_database)
    _execute(
        legacy_database.engine,
        "UPDATE user_organization SET role_id = :role_id WHERE id = :membership_id",
        {
            "role_id": custom_role_id,
            "membership_id": legacy_database.admin_membership,
        },
    )

    assert_that(
        calling(_execute).with_args(
            legacy_database.engine,
            "UPDATE roles SET organization_id = :org_id WHERE id = :role_id",
            {"org_id": legacy_database.org_a, "role_id": custom_role_id},
        ),
        raises(IntegrityError),
    )


def test_membership_enforces_one_owner_per_organization(legacy_database):
    assert_that(
        calling(_execute).with_args(
            legacy_database.engine,
            "UPDATE user_organization SET role_id = :role_id WHERE id = :membership_id",
            {
                "role_id": OWNER_ROLE_ID,
                "membership_id": legacy_database.member_membership,
            },
        ),
        raises(IntegrityError),
    )


def test_downgrade_restores_legacy_role_enum(legacy_database):
    command.downgrade(legacy_database.config, PRE_RBAC_REVISION)
    with legacy_database.engine.connect() as connection:
        actual = {
            "roles": {
                row[0]: row[1]
                for row in connection.execute(
                    text("SELECT id, role::text FROM user_organization")
                ).all()
            },
            "enum_labels": connection.execute(
                text(
                    """
                    SELECT enumlabel
                    FROM pg_enum
                    JOIN pg_type ON pg_type.oid = pg_enum.enumtypid
                    WHERE pg_type.typname = 'organizationrole'
                    ORDER BY enumsortorder
                    """
                )
            )
            .scalars()
            .all(),
        }

    assert_that(
        actual,
        equal_to(
            {
                "roles": {
                    legacy_database.owner_membership: "OWNER",
                    legacy_database.member_membership: "MEMBER",
                    legacy_database.admin_membership: "ADMIN",
                },
                "enum_labels": ["ADMIN", "MEMBER", "OWNER"],
            }
        ),
    )
