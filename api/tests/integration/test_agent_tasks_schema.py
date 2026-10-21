"""AF-411 Agent Task tables: the migration round-trips, the schema matches the models, and
the database keeps Tasks inside their Agent's Organization and removes their children."""

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid7

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from hamcrest import assert_that, calling, equal_to, raises
from sqlalchemy import create_engine, func, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, col, select

from api.core.config import get_config
from api.domains.agent_tasks.models import AgentTask, AgentTaskFile, AgentTaskFileChunk, AgentTaskNote
from api.domains.rbac.catalog import (
    AGENT_EDITOR_ROLE_ID,
    AGENT_OWNER_ROLE_ID,
    AGENT_VIEWER_ROLE_ID,
    PERMISSION_ID_BY_KEY,
    PermissionKey,
)
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    there_is_an_agent_in_another_org,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization

PRE_AF411_REVISION = "a4e9c2d7b615"
AF411_TASK_TABLES_REVISION = "b7d4e1a9c362"
AF411_TASK_READ_REVISION = "d2f8a6c41e07"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
AF411_TABLES = ("agent_task", "agent_task_note", "agent_task_file", "agent_task_file_chunk")

_GIVEN = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization(),
]


@pytest.fixture
def scratch_database(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"af411_{uuid7().hex}"
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


def _task_tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names()) & set(AF411_TABLES)


def _status_enum_exists(engine) -> bool:
    with engine.connect() as connection:
        return connection.execute(text("SELECT 1 FROM pg_type WHERE typname = 'agenttaskstatus'")).first() is not None


def test_agent_task_tables_downgrade_cleanly_and_upgrade_again(scratch_database):
    command.upgrade(scratch_database.config, AF411_TASK_TABLES_REVISION)
    assert_that(_task_tables(scratch_database.engine), equal_to(set(AF411_TABLES)))

    command.downgrade(scratch_database.config, PRE_AF411_REVISION)
    scratch_database.engine.dispose()
    assert_that(
        (_task_tables(scratch_database.engine), _status_enum_exists(scratch_database.engine)),
        equal_to((set(), False)),
    )

    command.upgrade(scratch_database.config, AF411_TASK_TABLES_REVISION)
    scratch_database.engine.dispose()
    assert_that(_task_tables(scratch_database.engine), equal_to(set(AF411_TABLES)))


def _task_read_grants(engine) -> tuple[bool, set]:
    task_read_id = PERMISSION_ID_BY_KEY[PermissionKey.TASK_READ]
    with engine.connect() as connection:
        permission = connection.execute(
            text("SELECT 1 FROM permissions WHERE id = :id AND key = 'task.read'").bindparams(id=task_read_id)
        ).first()
        roles = connection.execute(
            text("SELECT role_id FROM agent_access_role_permissions WHERE permission_id = :id").bindparams(
                id=task_read_id
            )
        ).scalars()
        return permission is not None, set(roles)


def test_task_read_is_granted_to_every_system_role_and_removed_on_downgrade(scratch_database):
    command.upgrade(scratch_database.config, AF411_TASK_READ_REVISION)
    assert_that(
        _task_read_grants(scratch_database.engine),
        equal_to((True, {AGENT_VIEWER_ROLE_ID, AGENT_EDITOR_ROLE_ID, AGENT_OWNER_ROLE_ID})),
    )

    command.downgrade(scratch_database.config, AF411_TASK_TABLES_REVISION)
    scratch_database.engine.dispose()
    assert_that(_task_read_grants(scratch_database.engine), equal_to((False, set())))


def test_the_migrated_schema_matches_the_agent_task_models():
    engine = create_engine(str(get_config().db_connection_url))
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), SQLModel.metadata)
    ours = [diff for diff in differences if "agent_task" in repr(diff) or "agenttaskstatus" in repr(diff)]

    assert_that(ours, equal_to([]))


def test_a_task_cannot_belong_to_an_agent_in_another_organization():
    with given([*_GIVEN, there_is_an_agent_in_another_org()]) as context:
        with when("a Task names this Organization but the other Organization's Agent"):
            task = AgentTask(
                organization_id=context.organization.id,
                agent_id=context.other_org_agent.id,
                title="Reconcile invoices",
            )

            def insert():
                with Session(context.postgres_delegate.engine) as session:
                    session.add(task)
                    session.commit()

            with then("the database rejects it"):
                assert_that(calling(insert), raises(IntegrityError))


def test_an_empty_file_is_rejected():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        with Session(context.postgres_delegate.engine) as session:
            task = AgentTask(organization_id=context.organization.id, agent_id=context.agent.id, title="Report")
            session.add(task)
            session.commit()
            task_id = task.id

        with when("a File records zero bytes"):
            empty = AgentTaskFile(
                organization_id=context.organization.id,
                task_id=task_id,
                filename="empty.txt",
                content_type="text/plain",
                size_bytes=0,
            )

            def insert():
                with Session(context.postgres_delegate.engine) as session:
                    session.add(empty)
                    session.commit()

            with then("the database rejects it"):
                assert_that(calling(insert), raises(IntegrityError))


def test_deleting_a_task_removes_its_notes_files_and_chunks():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        engine = context.postgres_delegate.engine
        with Session(engine) as session:
            task = AgentTask(organization_id=context.organization.id, agent_id=context.agent.id, title="Report")
            session.add(task)
            session.flush()
            session.add(AgentTaskNote(task_id=task.id, body="Started"))
            stored = AgentTaskFile(
                organization_id=context.organization.id,
                task_id=task.id,
                filename="report.csv",
                content_type="text/csv",
                size_bytes=3,
            )
            session.add(stored)
            session.flush()
            session.add(AgentTaskFileChunk(file_id=stored.id, sequence=0, data=b"a,b"))
            session.commit()
            task_id = task.id

        with when("the Task row is deleted"):
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM agent_task WHERE id = :id"), {"id": task_id})

            with then("no note, file or chunk is left behind"):
                with Session(engine) as session:
                    left = (
                        session.scalar(select(func.count()).select_from(AgentTaskNote)),
                        session.scalar(
                            select(func.count()).select_from(AgentTaskFile).where(col(AgentTaskFile.task_id) == task_id)
                        ),
                        session.scalar(select(func.count()).select_from(AgentTaskFileChunk)),
                    )
                assert_that(left, equal_to((0, 0, 0)))
