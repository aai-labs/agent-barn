"""Retired bundled Skills must not break reads after their provider is removed."""

import importlib
import json
import os
from datetime import UTC, datetime
from uuid import uuid7

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from hamcrest import assert_that, equal_to
from pydantic import ValidationError
from sqlalchemy import MetaData, Table, create_engine, text
from starlette.testclient import TestClient

from api.domains.agents.models import Agent
from api.domains.organizations.models import Organization
from api.domains.skills.models import SkillSummaryRead
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, use_org_for_auth
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

migration = importlib.import_module("api.migrations.versions.b91a73e42c60_remove_unused_zoho_skill")
metadata_migration = importlib.import_module(
    "api.migrations.versions.c42e91b7a603_remove_retired_skill_provider_requirements"
)


@pytest.fixture
def connection():
    engine = create_engine(os.environ["DB_CONNECTION_URL"])
    with engine.connect() as connection, connection.begin():
        yield connection
        connection.rollback()
    engine.dispose()


def seed_skill(connection, *, slug="aai-zoho-mail", source="aai_cli", provider="zoho_mail", providers=None):
    skill_id, version_id = uuid7(), uuid7()
    provider_json = json.dumps(providers if providers is not None else [provider])
    connection.execute(
        text("""
            INSERT INTO skill (id, created_at, updated_at, name, slug, root_dir, entry_path, source, required_providers)
            VALUES (:id, now(), now(), :slug, :slug, :slug, 'SKILL.md', :source, CAST(:providers AS json))
        """),
        {"id": skill_id, "slug": slug, "source": source, "providers": provider_json},
    )
    connection.execute(
        text("""
            INSERT INTO skill_version (id, created_at, updated_at, skill_id, version, required_providers)
            VALUES (:id, now(), now(), :skill_id, 1, CAST(:providers AS json))
        """),
        {"id": version_id, "skill_id": skill_id, "providers": provider_json},
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


def upgrade(connection, revision=migration):
    with Operations.context(MigrationContext.configure(connection)):
        revision.upgrade()


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
def test_cleanup_preserves_a_fork_source_and_repairs_its_metadata(connection, table):
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

    upgrade(connection)
    upgrade(connection, metadata_migration)

    assert_that(
        connection.execute(text("SELECT count(*) FROM skill WHERE id=:id"), {"id": skill_id}).scalar(), equal_to(1)
    )
    for row in summaries(connection):
        SkillSummaryRead.model_validate(dict(row))


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
            seed_skill(connection, slug="custom-mail", source="custom", providers=["google_workspace", "slack"])

        with when("the retired provider metadata is listed"):
            response = client.get(url, headers=headers)
        with then("the original request fails with HTTP 500"):
            assert_that(response.status_code, equal_to(500))

        with when("the upgrade cleans up the retired skill"):
            with context.postgres_delegate.engine.begin() as connection:
                upgrade(connection)
                upgrade(connection, metadata_migration)
            response = client.get(url, headers=headers)
        with then("the same request returns the supported skill"):
            assert_that(response.status_code, equal_to(200))
            assert_that(
                sorted(item["slug"] for item in response.json()["items"]),
                equal_to(["custom-mail", "supported-skill"]),
            )


@pytest.mark.parametrize("scope", ["platform", "organization", "agent"])
def test_metadata_cleanup_preserves_content_and_references_in_every_scope(connection, scope):
    providers = ["github", "zoho_mail", "google_workspace", "slack", "zoho_calendar", "github"]
    expected = ["github", "google_workspace", "github"]
    skill_id, _ = seed_skill(connection, slug="custom-retired", source="custom", providers=providers)
    if scope != "platform":
        organization = Organization(name="Migration Test Organization")
        connection.execute(
            Table("organization", MetaData(), autoload_with=connection).insert(), organization.model_dump()
        )
        agent_id = None
        if scope == "agent":
            agent = Agent(name="Retained Agent", organization_id=organization.id, deleted_at=datetime.now(UTC))
            connection.execute(Table("agent", MetaData(), autoload_with=connection).insert(), agent.model_dump())
            agent_id = agent.id
        connection.execute(
            text("UPDATE skill SET organization_id=:org, agent_id=:agent WHERE id=:id"),
            {"id": skill_id, "org": organization.id, "agent": agent_id},
        )
        if agent_id:
            connection.execute(
                text(
                    "INSERT INTO agent_skill (id, created_at, updated_at, agent_id, skill_id, pinned_version) VALUES (:id, now(), now(), :agent, :skill, 1)"
                ),
                {"id": uuid7(), "agent": agent_id, "skill": skill_id},
            )
    draft_id = uuid7()
    connection.execute(
        text(
            "INSERT INTO skill_draft (id, created_at, updated_at, skill_id, required_providers) VALUES (:id, now(), now(), :skill, CAST(:providers AS json))"
        ),
        {"id": draft_id, "skill": skill_id, "providers": json.dumps(providers)},
    )
    connection.execute(
        text(
            "INSERT INTO skill_draft_file (id, created_at, updated_at, skill_draft_id, path, content) VALUES (:id, now(), now(), :draft, 'SKILL.md', '# Draft content')"
        ),
        {"id": uuid7(), "draft": draft_id},
    )
    _, fork_version_id = seed_skill(connection, slug="fork", source="custom", provider="github")
    connection.execute(
        text("UPDATE skill_version SET source_skill_id=:source, source_skill_version=1 WHERE id=:id"),
        {"source": skill_id, "id": fork_version_id},
    )
    tables = ["skill", "skill_version", "skill_draft", "skill_file", "skill_draft_file", "agent_skill"]
    before = {
        table: [dict(row) for row in connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()]
        for table in tables
    }

    upgrade(connection, metadata_migration)
    upgrade(connection, metadata_migration)

    for table in tables:
        after = [dict(row) for row in connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()]
        expected_rows = [
            {
                **row,
                "required_providers": [
                    p for p in row["required_providers"] if p not in ("zoho_mail", "zoho_calendar", "slack")
                ],
            }
            if "required_providers" in row
            else row
            for row in before[table]
        ]
        assert_that(after, equal_to(expected_rows), table)
    assert_that(
        connection.execute(text("SELECT required_providers FROM skill WHERE id=:id"), {"id": skill_id}).scalar(),
        equal_to(expected),
    )


@pytest.mark.parametrize(
    "providers, expected",
    [
        ([], []),
        (["github", "google_workspace"], ["github", "google_workspace"]),
        (["future_provider"], ["future_provider"]),
        (["future_provider", "slack"], ["future_provider"]),
        (["zoho_mail"], []),
        (["zoho_calendar"], []),
        (["slack"], []),
    ],
)
def test_metadata_cleanup_removes_only_retired_providers(connection, providers, expected):
    skill_id, _ = seed_skill(connection, slug="unaffected", source="custom", providers=providers)
    before = dict(connection.execute(text("SELECT * FROM skill WHERE id=:id"), {"id": skill_id}).mappings().one())

    upgrade(connection, metadata_migration)

    after = dict(connection.execute(text("SELECT * FROM skill WHERE id=:id"), {"id": skill_id}).mappings().one())
    assert_that(after, equal_to({**before, "required_providers": expected}))
