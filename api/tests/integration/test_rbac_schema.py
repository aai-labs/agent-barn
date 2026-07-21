import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from hamcrest import assert_that, calling, equal_to, has_item, is_not, none, raises
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError

from api.core.config import Config as AppConfig
from api.domains.rbac.catalog import (
    ADMIN_ROLE_ID,
    AGENT_EDITOR_ROLE_ID,
    AGENT_OWNER_ROLE_ID,
    AGENT_VIEWER_ROLE_ID,
    MEMBER_ROLE_ID,
    OWNER_ROLE_ID,
    PERMISSION_ID_BY_KEY,
    PERMISSIONS,
    SYSTEM_AGENT_ACCESS_ROLE_GRANTS,
    SYSTEM_ROLE_GRANTS,
    PermissionKey,
)
from api.domains.rbac.repository import RbacRepository
from api.domains.rbac.seeder import RbacSeeder
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


def _repository_for(url: URL) -> RbacRepository:
    config = AppConfig.model_construct(db_connection_url=url.render_as_string(False))
    delegate = PostgresRepositoryDelegate(config)
    return RbacRepository(delegate=delegate)


def _seeder_for(url: URL) -> RbacSeeder:
    return RbacSeeder(repository=_repository_for(url))


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
    owner, member, admin, pending = uuid7(), uuid7(), uuid7(), uuid7()
    owner_membership, member_membership, admin_membership, pending_membership = (
        uuid7(),
        uuid7(),
        uuid7(),
        uuid7(),
    )
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
        for user_id, email, verified_at in (
            (owner, "owner@example.com", now),
            (member, "member@example.com", now),
            (admin, "admin@example.com", now),
            (pending, "pending@example.com", None),
        ):
            connection.execute(
                text(
                    'INSERT INTO "user" '
                    "(id, created_at, updated_at, email, full_name, hashed_password, "
                    "is_superuser, security_stamp, email_verified_at) "
                    "VALUES (:id, :now, :now, :email, NULL, :password, false, "
                    ":stamp, :verified_at)"
                ),
                {
                    "id": user_id,
                    "now": now,
                    "email": email,
                    "password": "hash",
                    "stamp": uuid7().hex,
                    "verified_at": verified_at,
                },
            )
        for membership_id, user_id, org_id, role in (
            (owner_membership, owner, org_a, "OWNER"),
            (member_membership, member, org_a, "MEMBER"),
            (admin_membership, admin, org_b, "ADMIN"),
            (pending_membership, pending, org_a, "MEMBER"),
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

    with engine.connect() as connection:
        pre_rbac_agent_columns = set(
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'agent'"
                )
            ).scalars()
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
            pending=pending,
            owner_membership=owner_membership,
            member_membership=member_membership,
            admin_membership=admin_membership,
            pending_membership=pending_membership,
            agent_a=agent_a,
            deleted_agent_a=deleted_agent_a,
            agent_b=agent_b,
            pre_rbac_agent_columns=pre_rbac_agent_columns,
        )
    finally:
        engine.dispose()


def _execute(engine, statement: str, params: dict[str, object]) -> None:
    with engine.begin() as connection:
        connection.execute(text(statement), params)


def _insert_custom_agent_access_role(db, organization_id):
    role_id = uuid7()
    _execute(
        db.engine,
        "INSERT INTO agent_access_roles "
        "(id, created_at, updated_at, organization_id, name, is_system) "
        "VALUES (:id, :now, :now, :org_id, :name, false)",
        {
            "id": role_id,
            "now": db.now,
            "org_id": organization_id,
            "name": f"CUSTOM-{role_id}",
        },
    )
    return role_id


def test_fresh_upgrade_seeds_exact_system_catalogues(fresh_database):
    with fresh_database.engine.connect() as connection:
        actual = {
            "organization_roles": dict(
                (name, role_id)
                for role_id, name in connection.execute(
                    text("SELECT id, name FROM roles ORDER BY name")
                ).all()
            ),
            "agent_access_roles": dict(
                (name, role_id)
                for role_id, name in connection.execute(
                    text(
                        "SELECT id, name FROM agent_access_roles "
                        "WHERE is_system ORDER BY name"
                    )
                ).all()
            ),
            "permissions": dict(
                (key, permission_id)
                for permission_id, key in connection.execute(
                    text("SELECT id, key FROM permissions ORDER BY key")
                ).all()
            ),
            "organization_grants": connection.execute(
                text("SELECT count(*) FROM role_permissions")
            ).scalar_one(),
            "agent_grants": connection.execute(
                text("SELECT count(*) FROM agent_access_role_permissions")
            ).scalar_one(),
            "legacy_enum_count": connection.execute(
                text("SELECT count(*) FROM pg_type WHERE typname = 'organizationrole'")
            ).scalar_one(),
            "scope_enum_count": connection.execute(
                text("SELECT count(*) FROM pg_type WHERE typname = 'permissionscope'")
            ).scalar_one(),
        }

    assert_that(
        actual,
        equal_to(
            {
                "organization_roles": {
                    "ADMIN": ADMIN_ROLE_ID,
                    "MEMBER": MEMBER_ROLE_ID,
                    "OWNER": OWNER_ROLE_ID,
                },
                "agent_access_roles": {
                    "EDITOR": AGENT_EDITOR_ROLE_ID,
                    "OWNER": AGENT_OWNER_ROLE_ID,
                    "VIEWER": AGENT_VIEWER_ROLE_ID,
                },
                "permissions": {
                    permission.key.value: permission.id for permission in PERMISSIONS
                },
                "organization_grants": sum(
                    len(grants) for grants in SYSTEM_ROLE_GRANTS.values()
                ),
                "agent_grants": sum(
                    len(grants) for grants in SYSTEM_AGENT_ACCESS_ROLE_GRANTS.values()
                ),
                "legacy_enum_count": 0,
                "scope_enum_count": 0,
            }
        ),
    )


def test_repository_resolves_separate_role_permissions(fresh_database):
    repository = _repository_for(fresh_database.url)

    assert repository.has_permission(MEMBER_ROLE_ID, PermissionKey.AGENT_CREATE)
    assert not repository.has_permission(MEMBER_ROLE_ID, PermissionKey.AGENT_READ)
    assert_that(
        repository.get_agent_access_role_permissions(AGENT_VIEWER_ROLE_ID),
        equal_to(
            {
                PermissionKey.AGENT_READ,
                PermissionKey.ACTIVITY_READ,
                PermissionKey.COST_READ,
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
            connection.execute(
                text("SELECT count(*) FROM agent_access_roles")
            ).scalar_one(),
            connection.execute(text("SELECT count(*) FROM permissions")).scalar_one(),
            connection.execute(
                text("SELECT count(*) FROM role_permissions")
            ).scalar_one(),
            connection.execute(
                text("SELECT count(*) FROM agent_access_role_permissions")
            ).scalar_one(),
        )

    assert_that(
        counts,
        equal_to(
            (
                3,
                3,
                len(PERMISSIONS),
                sum(len(grants) for grants in SYSTEM_ROLE_GRANTS.values()),
                sum(len(grants) for grants in SYSTEM_AGENT_ACCESS_ROLE_GRANTS.values()),
            )
        ),
    )


def test_fixed_organization_role_grants_reject_mutation(fresh_database):
    mutations = (
        (
            "INSERT INTO role_permissions (role_id, permission_id) "
            "VALUES (:role_id, :permission_id)",
            {
                "role_id": ADMIN_ROLE_ID,
                "permission_id": PERMISSION_ID_BY_KEY[
                    PermissionKey.ORGANIZATION_DELETE
                ],
            },
        ),
        (
            "DELETE FROM role_permissions "
            "WHERE role_id = :role_id AND permission_id = :permission_id",
            {
                "role_id": ADMIN_ROLE_ID,
                "permission_id": PERMISSION_ID_BY_KEY[PermissionKey.TEMPLATE_MANAGE],
            },
        ),
        (
            "UPDATE role_permissions SET permission_id = :new_permission_id "
            "WHERE role_id = :role_id AND permission_id = :permission_id",
            {
                "role_id": MEMBER_ROLE_ID,
                "permission_id": PERMISSION_ID_BY_KEY[PermissionKey.TEMPLATE_READ],
                "new_permission_id": PERMISSION_ID_BY_KEY[PermissionKey.COST_READ],
            },
        ),
    )

    for statement, parameters in mutations:
        assert_that(
            calling(_execute).with_args(
                fresh_database.engine,
                statement,
                parameters,
            ),
            raises(IntegrityError),
        )


def test_system_agent_access_role_grants_reject_mutation(fresh_database):
    mutations = (
        (
            "INSERT INTO agent_access_role_permissions (role_id, permission_id) "
            "VALUES (:role_id, :permission_id)",
            {
                "role_id": AGENT_VIEWER_ROLE_ID,
                "permission_id": PERMISSION_ID_BY_KEY[
                    PermissionKey.ORGANIZATION_DELETE
                ],
            },
        ),
        (
            "DELETE FROM agent_access_role_permissions "
            "WHERE role_id = :role_id AND permission_id = :permission_id",
            {
                "role_id": AGENT_VIEWER_ROLE_ID,
                "permission_id": PERMISSION_ID_BY_KEY[PermissionKey.AGENT_READ],
            },
        ),
        (
            "UPDATE agent_access_role_permissions "
            "SET permission_id = :new_permission_id "
            "WHERE role_id = :role_id AND permission_id = :permission_id",
            {
                "role_id": AGENT_VIEWER_ROLE_ID,
                "permission_id": PERMISSION_ID_BY_KEY[PermissionKey.AGENT_READ],
                "new_permission_id": PERMISSION_ID_BY_KEY[PermissionKey.AGENT_UPDATE],
            },
        ),
    )

    for statement, parameters in mutations:
        assert_that(
            calling(_execute).with_args(
                fresh_database.engine,
                statement,
                parameters,
            ),
            raises(IntegrityError),
        )


def test_custom_agent_access_role_grants_remain_mutable(legacy_database):
    custom_role_id = _insert_custom_agent_access_role(
        legacy_database,
        legacy_database.org_a,
    )
    parameters = {
        "role_id": custom_role_id,
        "permission_id": PERMISSION_ID_BY_KEY[PermissionKey.AGENT_READ],
    }

    _execute(
        legacy_database.engine,
        "INSERT INTO agent_access_role_permissions (role_id, permission_id) "
        "VALUES (:role_id, :permission_id)",
        parameters,
    )
    _execute(
        legacy_database.engine,
        "DELETE FROM agent_access_role_permissions "
        "WHERE role_id = :role_id AND permission_id = :permission_id",
        parameters,
    )

    with legacy_database.engine.connect() as connection:
        count = connection.execute(
            text(
                "SELECT count(*) FROM agent_access_role_permissions "
                "WHERE role_id = :role_id"
            ),
            {"role_id": custom_role_id},
        ).scalar_one()
    assert_that(count, equal_to(0))


def test_permission_catalogue_rejects_mutation(fresh_database):
    permission = PERMISSIONS[0]
    mutations = (
        (
            "INSERT INTO permissions (id, created_at, updated_at, key) "
            "VALUES (:id, now(), now(), :key)",
            {"id": uuid7(), "key": "unexpected.permission"},
        ),
        (
            "UPDATE permissions SET key = :key WHERE id = :id",
            {"id": permission.id, "key": "changed.permission"},
        ),
        (
            "DELETE FROM permissions WHERE id = :id",
            {"id": permission.id},
        ),
    )

    for statement, parameters in mutations:
        assert_that(
            calling(_execute).with_args(
                fresh_database.engine,
                statement,
                parameters,
            ),
            raises(IntegrityError),
        )


def test_upgrade_backfills_membership_roles(legacy_database):
    with legacy_database.engine.connect() as connection:
        actual = dict(
            connection.execute(text("SELECT id, role_id FROM user_organization")).all()
        )

    assert_that(
        actual,
        equal_to(
            {
                legacy_database.owner_membership: OWNER_ROLE_ID,
                legacy_database.member_membership: MEMBER_ROLE_ID,
                legacy_database.admin_membership: ADMIN_ROLE_ID,
                legacy_database.pending_membership: MEMBER_ROLE_ID,
            }
        ),
    )


def test_upgrade_backfills_only_accepted_members_with_editor(legacy_database):
    with legacy_database.engine.connect() as connection:
        actual = set(
            connection.execute(
                text(
                    "SELECT membership_id, agent_id, organization_id, access_role_id "
                    "FROM agent_access"
                )
            ).all()
        )

    assert_that(
        actual,
        equal_to(
            {
                (
                    legacy_database.member_membership,
                    legacy_database.agent_a,
                    legacy_database.org_a,
                    AGENT_EDITOR_ROLE_ID,
                ),
                (
                    legacy_database.member_membership,
                    legacy_database.deleted_agent_a,
                    legacy_database.org_a,
                    AGENT_EDITOR_ROLE_ID,
                ),
            }
        ),
    )


def test_upgrade_leaves_creator_unknown_when_legacy_schema_has_no_provenance(
    legacy_database,
):
    assert_that(
        legacy_database.pre_rbac_agent_columns,
        is_not(has_item("created_by_user_id")),
    )
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
            "(id, created_at, updated_at, organization_id, membership_id, "
            "agent_id, access_role_id) "
            "VALUES (:id, :now, :now, :org_id, :membership_id, :agent_id, :role_id)",
            {
                "id": uuid7(),
                "now": legacy_database.now,
                "org_id": legacy_database.org_b,
                "membership_id": legacy_database.member_membership,
                "agent_id": legacy_database.agent_b,
                "role_id": AGENT_EDITOR_ROLE_ID,
            },
        ),
        raises(IntegrityError),
    )


def test_agent_access_rejects_custom_role_from_another_organization(
    legacy_database,
):
    custom_role_id = _insert_custom_agent_access_role(
        legacy_database,
        legacy_database.org_b,
    )

    assert_that(
        calling(_execute).with_args(
            legacy_database.engine,
            "INSERT INTO agent_access "
            "(id, created_at, updated_at, organization_id, membership_id, "
            "agent_id, access_role_id) "
            "VALUES (:id, :now, :now, :org_id, :membership_id, :agent_id, :role_id)",
            {
                "id": uuid7(),
                "now": legacy_database.now,
                "org_id": legacy_database.org_a,
                "membership_id": legacy_database.owner_membership,
                "agent_id": legacy_database.agent_a,
                "role_id": custom_role_id,
            },
        ),
        raises(IntegrityError),
    )


def test_locked_roles_reject_mutation(legacy_database):
    mutations = (
        (
            "INSERT INTO roles (id, created_at, updated_at, name) "
            "VALUES (:id, now(), now(), :name)",
            {"id": uuid7(), "name": "CUSTOM"},
        ),
        (
            "UPDATE roles SET name = :name WHERE id = :id",
            {"name": "CHANGED", "id": MEMBER_ROLE_ID},
        ),
        (
            "DELETE FROM roles WHERE id = :id",
            {"id": MEMBER_ROLE_ID},
        ),
        (
            "INSERT INTO agent_access_roles "
            "(id, created_at, updated_at, organization_id, name, is_system) "
            "VALUES (:id, now(), now(), NULL, :name, true)",
            {"id": uuid7(), "name": "SYSTEM-CUSTOM"},
        ),
        (
            "UPDATE agent_access_roles SET name = :name WHERE id = :id",
            {"name": "CHANGED", "id": AGENT_EDITOR_ROLE_ID},
        ),
        (
            "DELETE FROM agent_access_roles WHERE id = :id",
            {"id": AGENT_EDITOR_ROLE_ID},
        ),
    )

    for statement, parameters in mutations:
        assert_that(
            calling(_execute).with_args(
                legacy_database.engine,
                statement,
                parameters,
            ),
            raises(IntegrityError),
        )


def test_custom_agent_access_role_scope_is_immutable(legacy_database):
    custom_role_id = _insert_custom_agent_access_role(
        legacy_database,
        legacy_database.org_b,
    )

    assert_that(
        calling(_execute).with_args(
            legacy_database.engine,
            "UPDATE agent_access_roles SET organization_id = :org_id "
            "WHERE id = :role_id",
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
            "roles": dict(
                connection.execute(
                    text("SELECT id, role::text FROM user_organization")
                ).all()
            ),
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
                    legacy_database.pending_membership: "MEMBER",
                },
                "enum_labels": ["ADMIN", "MEMBER", "OWNER"],
            }
        ),
    )
