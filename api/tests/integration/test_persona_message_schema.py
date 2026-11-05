import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from hamcrest import assert_that, contains_string, equal_to, has_length, none
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel

from api.domains.communications.models import CommunicationConnection
from api.domains.conversations.models import AgentChatMessage, ConversationType, MessageDirection
from api.domains.personas.models import AgentPersona
from api.domains.web_chat.models import WebChatThread
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector
from api.tests.integration.test_rbac_schema import isolated_database  # noqa: F401
from api.tests.steps.agent import there_is_an_agent
from api.tests.steps.database import database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization

TABLES_REVISION = "b7d2e94c1a30"
COLUMNS_REVISION = "c1a84f7e2b60"
FK_NAME = "fk_agent_chat_message_persona"
MESSAGE_INDEX = "ix_agent_chat_message_persona"
APPS = [
    "api.api_app",
    "api.communications_app",
    "api.gateway_app",
    "api.ingest_app",
    "api.memory_app",
    "api.memory_runtime_app",
    "api.worker_app",
    "api.sync_engine_main",
]

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


def _persona(context, key="sales", agent_id=None) -> AgentPersona:
    return _save(
        context,
        AgentPersona(
            organization_id=context.organization.id,
            agent_id=agent_id or context.agent.id,
            key=key,
            display_name=key.title(),
            current_version=1,
        ),
    )


def _connection(context, agent_id=None) -> CommunicationConnection:
    return _save(
        context,
        CommunicationConnection(
            organization_id=context.organization.id,
            agent_id=agent_id or context.agent.id,
            platform_key="web",
            display_name="Web Chat",
            enabled=True,
            schema_version=1,
            settings={},
            credentials_encrypted="encrypted",
        ),
    )


def _message(context, connection, persona_id: UUID | None = None, agent_id=None) -> AgentChatMessage:
    return AgentChatMessage(
        agent_id=agent_id or context.agent.id,
        connection_id=connection.id,
        openclaw_msg_id=str(uuid4()),
        session_key="session",
        channel_id="user",
        thread_id="main",
        direction=MessageDirection.INBOUND,
        conversation_type=ConversationType.DM,
        content="hello",
        occurred_at=datetime.now(UTC),
        persona_id=persona_id,
    )


def _thread(connection, persona_id: UUID | None = None, thread_id="main") -> WebChatThread:
    return WebChatThread(connection_id=connection.id, channel_id="user", thread_id=thread_id, persona_id=persona_id)


def test_messages_and_threads_default_to_the_default_persona():
    with given(_GIVEN) as context:
        connection = _connection(context)
        message = _save(context, _message(context, connection))
        thread = _save(context, _thread(connection))

        found_message = _get(context, AgentChatMessage, message.id)
        found_thread = _get(context, WebChatThread, thread.id)

        assert found_message is not None and found_thread is not None
        assert_that(found_message.persona_id, none())
        assert_that(found_thread.persona_id, none())


def test_a_message_can_belong_to_a_persona_of_its_agent():
    with given(_GIVEN) as context:
        persona = _persona(context)
        message = _save(context, _message(context, _connection(context), persona.id))

        found = _get(context, AgentChatMessage, message.id)

        assert found is not None
        assert_that(found.persona_id, equal_to(persona.id))


def test_a_message_cannot_belong_to_another_agents_persona():
    with given(_GIVEN) as context:
        first_agent = context.agent.id
        connection = _connection(context)
        there_is_an_agent(name="Other Agent")(context)
        other_persona = _persona(context)

        with pytest.raises(IntegrityError):
            _save(context, _message(context, connection, other_persona.id, agent_id=first_agent))


def test_a_persona_with_messages_cannot_be_removed_on_its_own():
    with given(_GIVEN) as context:
        persona = _persona(context)
        _save(context, _message(context, _connection(context), persona.id))

        with pytest.raises(IntegrityError), context.postgres_delegate.engine.begin() as connection:
            connection.execute(text("DELETE FROM agent_persona WHERE id = :id"), {"id": persona.id})


def test_a_persona_with_threads_cannot_be_removed_on_its_own():
    with given(_GIVEN) as context:
        persona = _persona(context)
        _save(context, _thread(_connection(context), persona.id))

        with pytest.raises(IntegrityError), context.postgres_delegate.engine.begin() as connection:
            connection.execute(text("DELETE FROM agent_persona WHERE id = :id"), {"id": persona.id})


def test_the_default_and_each_persona_can_have_a_thread_of_the_same_name():
    with given(_GIVEN) as context:
        connection = _connection(context)
        sales = _persona(context, "sales")
        lawyer = _persona(context, "lawyer")

        _save(context, _thread(connection), _thread(connection, sales.id), _thread(connection, lawyer.id))


def test_the_default_cannot_have_two_threads_of_the_same_name():
    with given(_GIVEN) as context:
        connection = _connection(context)
        _save(context, _thread(connection))

        with pytest.raises(IntegrityError):
            _save(context, _thread(connection))


def test_a_persona_cannot_have_two_threads_of_the_same_name():
    with given(_GIVEN) as context:
        connection = _connection(context)
        persona = _persona(context)
        _save(context, _thread(connection, persona.id))

        with pytest.raises(IntegrityError):
            _save(context, _thread(connection, persona.id))


def test_deleting_an_organization_with_persona_messages_and_threads_succeeds():
    with given(_GIVEN) as context:
        connection = _connection(context)
        persona = _persona(context)
        message = _save(context, _message(context, connection, persona.id))
        thread = _save(context, _thread(connection, persona.id))

        with context.postgres_delegate.engine.begin() as sql:
            sql.execute(text("DELETE FROM organization WHERE id = :id"), {"id": context.organization.id})

        assert_that(_get(context, AgentPersona, persona.id), none())
        assert_that(_get(context, AgentChatMessage, message.id), none())
        assert_that(_get(context, WebChatThread, thread.id), none())


def test_deleting_an_agent_with_persona_messages_and_threads_succeeds():
    with given(_GIVEN) as context:
        connection = _connection(context)
        persona = _persona(context)
        message = _save(context, _message(context, connection, persona.id))

        with context.postgres_delegate.engine.begin() as sql:
            sql.execute(text("DELETE FROM agent WHERE id = :id"), {"id": context.agent.id})

        assert_that(_get(context, AgentPersona, persona.id), none())
        assert_that(_get(context, AgentChatMessage, message.id), none())


def test_the_foreign_key_is_validated_and_the_index_is_partial_and_valid():
    with given(_GIVEN) as context:
        with context.postgres_delegate.engine.connect() as connection:
            validated = connection.execute(
                text("SELECT convalidated FROM pg_constraint WHERE conname = :name"), {"name": FK_NAME}
            ).scalar_one()
            valid = connection.execute(
                text("SELECT indisvalid FROM pg_index WHERE indexrelid = CAST(:name AS regclass)"),
                {"name": MESSAGE_INDEX},
            ).scalar_one()
            definition = connection.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"), {"name": MESSAGE_INDEX}
            ).scalar_one()

        assert_that(validated, equal_to(True))
        assert_that(valid, equal_to(True))
        assert_that(definition, contains_string("(persona_id, agent_id) WHERE (persona_id IS NOT NULL)"))


@pytest.mark.parametrize("app", APPS)
def test_every_app_can_resolve_the_new_foreign_keys(app):
    script = (
        f"import {app}\n"
        "from sqlalchemy.orm import configure_mappers\n"
        "from sqlmodel import SQLModel\n"
        "configure_mappers()\n"
        "for name in ('agent_chat_message', 'web_chat_thread'):\n"
        "    table = SQLModel.metadata.tables.get(name)\n"
        "    if table is None:\n"
        "        continue\n"
        "    for key in table.foreign_keys:\n"
        "        key.column\n"
    )
    root = Path(__file__).resolve().parents[3]
    env = {**os.environ, "PYTHONPATH": str(root)}
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=root, env=env, capture_output=True, text=True, check=False
    )
    assert_that(result.stderr[-1500:] if result.returncode else "", equal_to(""))


def test_the_migrations_match_the_models_for_messages_and_threads():
    def only_changed_tables(object_, name, type_, reflected, compare_to):
        table = name if type_ == "table" else object_.table.name
        return table in {"agent_chat_message", "web_chat_thread"}

    with given(_GIVEN) as context, context.postgres_delegate.engine.connect() as connection:
        drift = compare_metadata(
            MigrationContext.configure(connection, opts={"include_object": only_changed_tables, "compare_type": False}),
            SQLModel.metadata,
        )

    database_wide_enums = "change_enum_variants"
    assert_that([diff for diff in drift if diff[0] != database_wide_enums], has_length(0))


def _config() -> Config:
    return Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))


def _state(engine) -> tuple:
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        validated = connection.execute(
            text("SELECT convalidated FROM pg_constraint WHERE conname = :name"), {"name": FK_NAME}
        ).scalar_one_or_none()
        valid = connection.execute(
            text("SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = :name"),
            {"name": MESSAGE_INDEX},
        ).scalar_one_or_none()
    return version, validated, valid


def test_the_first_step_leaves_the_key_unvalidated_and_the_second_completes_it(isolated_database):  # noqa: F811
    config = _config()
    command.upgrade(config, COLUMNS_REVISION)
    engine = create_engine(isolated_database)
    try:
        assert_that(_state(engine), equal_to((COLUMNS_REVISION, False, None)))

        command.upgrade(config, "head")

        version, validated, valid = _state(engine)
        assert_that(version == COLUMNS_REVISION, equal_to(False))
        assert_that((validated, valid), equal_to((True, True)))
    finally:
        engine.dispose()


def test_the_second_step_recovers_from_an_index_left_invalid_by_a_cancelled_build(isolated_database):  # noqa: F811
    config = _config()
    command.upgrade(config, COLUMNS_REVISION)
    engine = create_engine(isolated_database)
    try:
        with engine.begin() as connection:
            connection.execute(text(f"CREATE INDEX {MESSAGE_INDEX} ON agent_chat_message (created_at)"))
            connection.execute(
                text("UPDATE pg_index SET indisvalid = false WHERE indexrelid = CAST(:name AS regclass)"),
                {"name": MESSAGE_INDEX},
            )
        assert_that(_state(engine)[2], equal_to(False))

        command.upgrade(config, "head")

        assert_that(_state(engine)[1:], equal_to((True, True)))
        with engine.connect() as connection:
            definition = connection.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"), {"name": MESSAGE_INDEX}
            ).scalar_one()
        assert_that(definition, contains_string("persona_id"))
    finally:
        engine.dispose()


def test_downgrade_with_persona_rows_keeps_messages_and_restores_the_old_constraint(isolated_database):  # noqa: F811
    config = _config()
    command.upgrade(config, "head")
    engine = create_engine(isolated_database)
    agent, connection_id, persona = uuid4(), uuid4(), uuid4()
    try:
        with engine.begin() as sql:
            sql.execute(text("SET LOCAL session_replication_role = replica"))
            sql.execute(
                text(
                    "INSERT INTO agent_chat_message (id, created_at, updated_at, agent_id, connection_id, "
                    "openclaw_msg_id, session_key, channel_id, thread_id, direction, conversation_type, content, "
                    "occurred_at, persona_id) VALUES (:id, now(), now(), :agent, :connection, :msg, 's', 'user', "
                    "'main', 'INBOUND', 'DM', 'hello', now(), :persona)"
                ),
                {"id": uuid4(), "agent": agent, "connection": connection_id, "msg": "m1", "persona": persona},
            )
            for persona_id in (None, persona):
                sql.execute(
                    text(
                        "INSERT INTO web_chat_thread (id, created_at, updated_at, connection_id, channel_id, "
                        "thread_id, persona_id) VALUES (:id, now(), now(), :connection, 'user', 'main', :persona)"
                    ),
                    {"id": uuid4(), "connection": connection_id, "persona": persona_id},
                )

        command.downgrade(config, TABLES_REVISION)

        with engine.connect() as sql:
            messages = sql.execute(text("SELECT content FROM agent_chat_message")).all()
            threads = sql.execute(text("SELECT thread_id FROM web_chat_thread")).all()
            constraint = sql.execute(
                text("SELECT 1 FROM pg_constraint WHERE conname = 'uq_web_chat_thread_connection_channel_thread'")
            ).all()
            columns = sql.execute(
                text(
                    "SELECT table_name FROM information_schema.columns WHERE column_name = 'persona_id' "
                    "AND table_name IN ('agent_chat_message', 'web_chat_thread')"
                )
            ).all()
        assert_that(messages, has_length(1))
        assert_that(threads, has_length(1))
        assert_that(constraint, has_length(1))
        assert_that(columns, has_length(0))

        command.upgrade(config, "head")
        assert_that(_state(engine)[1:], equal_to((True, True)))
    finally:
        engine.dispose()
