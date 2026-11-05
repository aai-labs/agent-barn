from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from hamcrest import assert_that, equal_to, has_length, none, not_none
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel

from api.domains.personas.models import AgentPersona, AgentPersonaVersion
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector
from api.tests.integration.test_rbac_schema import isolated_database  # noqa: F401
from api.tests.steps.agent import there_is_an_agent
from api.tests.steps.database import database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization

PERSONA_TABLES = {"agent_persona", "agent_persona_version"}
PREVIOUS_HEAD = "3680352c132d"

_GIVEN = [prepare_injector(), database_repo_is_ready(), there_is_an_organization(), there_is_an_agent()]


def _save(context, *rows):
    with Session(context.postgres_delegate.engine, expire_on_commit=False) as session:
        for row in rows:
            session.add(row)
        session.commit()
    return rows[0] if len(rows) == 1 else rows


def _get(context, model, row_id):
    with Session(context.postgres_delegate.engine) as session:
        return session.get(model, row_id)


def _persona(context, key="sales", agent_id=None, organization_id=None, **fields) -> AgentPersona:
    return AgentPersona(
        organization_id=organization_id or context.organization.id,
        agent_id=agent_id or context.agent.id,
        key=key,
        display_name=key.title(),
        current_version=1,
        **fields,
    )


def _version(context, persona, version=1, organization_id=None, **fields) -> AgentPersonaVersion:
    return AgentPersonaVersion(
        organization_id=organization_id or context.organization.id,
        persona_id=persona.id,
        version=version,
        soul_md="# Soul",
        identity_md="# Identity",
        **fields,
    )


def test_a_persona_is_stored_with_its_defaults():
    with given(_GIVEN) as context:
        persona = _save(context, _persona(context))

        found = _get(context, AgentPersona, persona.id)

        assert found is not None
        assert_that(found.key, equal_to("sales"))
        assert_that(found.current_version, equal_to(1))
        assert_that(found.emoji, none())
        assert_that(found.deleted_at, none())


def test_a_key_is_unique_within_an_agent():
    with given(_GIVEN) as context:
        _save(context, _persona(context))

        with pytest.raises(IntegrityError):
            _save(context, _persona(context))


def test_a_deleted_personas_key_stays_taken():
    with given(_GIVEN) as context:
        _save(context, _persona(context, deleted_at=datetime.now(UTC)))

        with pytest.raises(IntegrityError):
            _save(context, _persona(context))


def test_two_agents_can_use_the_same_key():
    with given(_GIVEN) as context:
        first = _save(context, _persona(context))
        there_is_an_agent(name="Other Agent")(context)

        second = _save(context, _persona(context))

        assert_that(second.agent_id == first.agent_id, equal_to(False))


def test_a_key_longer_than_the_session_id_budget_is_refused_by_the_database():
    with given(_GIVEN) as context:
        _save(context, _persona(context, key="k" * 40))

        with pytest.raises(Exception, match="value too long"):
            _save(context, _persona(context, key="k" * 41))


def test_a_persona_cannot_name_another_organizations_agent():
    with given(_GIVEN) as context:
        agent_id = context.agent.id
        there_is_an_organization(name="Other Organization")(context)

        with pytest.raises(IntegrityError):
            _save(context, _persona(context, agent_id=agent_id))


def test_a_version_number_is_unique_within_a_persona():
    with given(_GIVEN) as context:
        persona = _save(context, _persona(context))
        _save(context, _version(context, persona))

        with pytest.raises(IntegrityError):
            _save(context, _version(context, persona))


def test_a_version_cannot_name_another_organizations_persona():
    with given(_GIVEN) as context:
        persona = _save(context, _persona(context))
        there_is_an_organization(name="Other Organization")(context)

        with pytest.raises(IntegrityError):
            _save(context, _version(context, persona))


def test_deleting_an_agent_removes_its_personas_and_their_versions():
    with given(_GIVEN) as context:
        persona = _save(context, _persona(context))
        version = _save(context, _version(context, persona))

        with context.postgres_delegate.engine.begin() as connection:
            connection.execute(text("DELETE FROM agent WHERE id = :id"), {"id": context.agent.id})

        assert_that(_get(context, AgentPersona, persona.id), none())
        assert_that(_get(context, AgentPersonaVersion, version.id), none())


def test_the_author_foreign_key_sets_null_on_delete():
    with given(_GIVEN) as context:
        with context.postgres_delegate.engine.connect() as connection:
            action = connection.execute(
                text(
                    "SELECT confdeltype FROM pg_constraint "
                    "WHERE conrelid = 'agent_persona_version'::regclass AND conname LIKE '%author_user_id%'"
                )
            ).scalar_one()

        assert_that(action, equal_to("n"))


def test_the_migration_matches_the_models_and_downgrades_cleanly(isolated_database):  # noqa: F811
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(isolated_database)
    try:
        assert_that(PERSONA_TABLES <= set(inspect(engine).get_table_names()), equal_to(True))

        def only_persona_tables(object_, name, type_, reflected, compare_to):
            table = name if type_ == "table" else object_.table.name
            return table in PERSONA_TABLES

        with engine.connect() as connection:
            drift = compare_metadata(
                MigrationContext.configure(
                    connection, opts={"include_object": only_persona_tables, "compare_type": True}
                ),
                SQLModel.metadata,
            )
        database_wide_enums = "change_enum_variants"
        assert_that([diff for diff in drift if diff[0] != database_wide_enums], has_length(0))
        assert_that(inspect(engine).get_pk_constraint("agent_persona"), not_none())

        command.downgrade(config, PREVIOUS_HEAD)
        assert_that(PERSONA_TABLES & set(inspect(engine).get_table_names()), equal_to(set()))

        command.upgrade(config, "head")
        assert_that(PERSONA_TABLES <= set(inspect(engine).get_table_names()), equal_to(True))
    finally:
        engine.dispose()
