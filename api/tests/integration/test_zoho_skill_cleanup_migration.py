"""Retired bundled Skills must not break reads after their provider is removed."""

import importlib
import os
from uuid import uuid7

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from hamcrest import assert_that, equal_to
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from starlette.testclient import TestClient

from api.domains.skills.models import SkillSummaryRead
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, use_org_for_auth
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

migration = importlib.import_module("api.migrations.versions.b91a73e42c60_remove_unused_zoho_skill")


@pytest.fixture
def connection():
    engine = create_engine(os.environ["DB_CONNECTION_URL"])
    with engine.connect() as connection, connection.begin():
        yield connection
        connection.rollback()
    engine.dispose()


def seed_skill(connection, *, slug="aai-zoho-mail", source="aai_cli", provider="zoho_mail"):
    skill_id, version_id = uuid7(), uuid7()
    connection.execute(
        text("""
            INSERT INTO skill (id, created_at, updated_at, name, slug, root_dir, entry_path, source, required_providers)
            VALUES (:id, now(), now(), :slug, :slug, :slug, 'SKILL.md', :source, CAST(:providers AS json))
        """),
        {"id": skill_id, "slug": slug, "source": source, "providers": f'["{provider}"]'},
    )
    connection.execute(
        text("""
            INSERT INTO skill_version (id, created_at, updated_at, skill_id, version, required_providers)
            VALUES (:id, now(), now(), :skill_id, 1, CAST(:providers AS json))
        """),
        {"id": version_id, "skill_id": skill_id, "providers": f'["{provider}"]'},
    )
    connection.execute(
        text("""
            INSERT INTO skill_file (id, created_at, updated_at, skill_version_id, path, content)
            VALUES (:id, now(), now(), :version_id, 'SKILL.md', '# Instructions')
        """),
        {"id": uuid7(), "version_id": version_id},
    )
    return skill_id, version_id


def summaries(connection):
    return connection.execute(text("SELECT s.*, 1 AS version, false AS has_draft FROM skill s")).mappings().all()


def upgrade(connection):
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()


def create_client(context):
    context.client = TestClient(context.app, raise_server_exceptions=False)


def test_cleanup_removes_obsolete_skill_and_restores_summary_serialization(connection):
    skill_id, version_id = seed_skill(connection)
    seed_skill(connection, slug="supported-skill", provider="github")
    with pytest.raises(ValidationError, match="required_providers"):
        for row in summaries(connection):
            SkillSummaryRead.model_validate(dict(row))

    upgrade(connection)

    for row in summaries(connection):
        SkillSummaryRead.model_validate(dict(row))
    assert_that(
        connection.execute(text("SELECT count(*) FROM skill WHERE id=:id"), {"id": skill_id}).scalar(), equal_to(0)
    )
    assert_that(
        connection.execute(text("SELECT count(*) FROM skill_version WHERE id=:id"), {"id": version_id}).scalar(),
        equal_to(0),
    )
    assert_that(
        connection.execute(
            text("SELECT count(*) FROM skill_file WHERE skill_version_id=:id"), {"id": version_id}
        ).scalar(),
        equal_to(0),
    )


def test_cleanup_is_a_noop_without_the_retired_builtin_and_preserves_custom_skills(connection):
    skill_id, _ = seed_skill(connection, source="custom", provider="github")

    upgrade(connection)
    upgrade(connection)

    assert_that(
        connection.execute(text("SELECT count(*) FROM skill WHERE id=:id"), {"id": skill_id}).scalar(), equal_to(1)
    )


@pytest.mark.parametrize("table", ["skill_version", "skill_draft"])
def test_cleanup_refuses_to_delete_a_fork_source(connection, table):
    skill_id, _ = seed_skill(connection)
    fork_id, fork_version_id = seed_skill(connection, slug="fork", source="custom", provider="github")
    if table == "skill_version":
        connection.execute(
            text("UPDATE skill_version SET source_skill_id=:source, source_skill_version=1 WHERE id=:id"),
            {"source": skill_id, "id": fork_version_id},
        )
    else:
        connection.execute(
            text(
                "INSERT INTO skill_draft (id, created_at, updated_at, skill_id, source_skill_id, source_skill_version, required_providers) VALUES (:id, now(), now(), :skill_id, :source, 1, '[]'::json)"
            ),
            {"id": uuid7(), "skill_id": fork_id, "source": skill_id},
        )

    with pytest.raises(RuntimeError, match="still referenced"):
        upgrade(connection)

    assert_that(
        connection.execute(text("SELECT count(*) FROM skill WHERE id=:id"), {"id": skill_id}).scalar(), equal_to(1)
    )


def test_organization_skill_endpoint_recovers_after_cleanup():
    with given(
        [
            set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_client,
            database_repo_is_ready(),
            database_is_clean(),
            there_is_an_organization_with_user_and_access_token(),
            use_org_for_auth(),
        ]
    ) as context:
        client = context.client
        url = f"/api/v1/organizations/{context.organization.id}/skills?page=1&page_size=15"
        headers = {"Authorization": f"Bearer {context.access_token}"}
        with context.postgres_delegate.engine.begin() as connection:
            seed_skill(connection)
            seed_skill(connection, slug="supported-skill", provider="github")

        with when("the retired provider metadata is listed"):
            response = client.get(url, headers=headers)
        with then("the original request fails with HTTP 500"):
            assert_that(response.status_code, equal_to(500))

        with when("the upgrade cleans up the retired skill"):
            with context.postgres_delegate.engine.begin() as connection:
                upgrade(connection)
            response = client.get(url, headers=headers)
        with then("the same request returns the supported skill"):
            assert_that(response.status_code, equal_to(200))
            assert_that([item["slug"] for item in response.json()["items"]], equal_to(["supported-skill"]))
