"""AF-453 anomaly detection tables: the migration round-trips and seeds its Permissions,
the schema matches the models, and the database keeps every row inside its Agent's
Organization and at most one ongoing Anomaly per Agent, signal and subject."""

import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid7

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from hamcrest import assert_that, calling, equal_to, raises
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, func, select

from api.core.config import get_config
from api.domains.anomalies.models import AgentAnomaly, AgentAnomalyOverride, AnomalySignal
from api.domains.rbac.catalog import PERMISSION_ID_BY_KEY, PermissionKey
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

PRE_AF453_REVISION = "b7e2c41d9a63"
AF453_REVISION = "92996d692c89"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
AF453_TABLES = {
    "organization_anomaly_settings",
    "agent_anomaly_override",
    "agent_activity_seen",
    "agent_anomaly_state",
    "agent_anomaly",
}
# AF-464: who was already emailed for an alert delivery.
AF464_TABLES = {"anomaly_alert_email_receipt"}
AF464_REVISION = "2180817c8927"
# AF-464: whether an Organization emails its alerts.
AF464_ALERTS_REVISION = "4010f1f2d1f1"
AF453_PERMISSIONS = (PermissionKey.ANOMALY_READ, PermissionKey.ANOMALY_MANAGE)

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
    database_name = f"af453_{uuid7().hex}"
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


def _anomaly_tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names()) & AF453_TABLES


def _seeded_permissions(engine) -> set[str]:
    ids = [PERMISSION_ID_BY_KEY[key] for key in AF453_PERMISSIONS]
    with engine.connect() as connection:
        return set(
            connection.execute(text("SELECT key FROM permissions WHERE id = ANY(:ids)").bindparams(ids=ids)).scalars()
        )


def test_the_migration_creates_the_tables_and_permissions_and_removes_them_on_downgrade(scratch_database):
    command.upgrade(scratch_database.config, AF453_REVISION)
    assert_that(
        (_anomaly_tables(scratch_database.engine), _seeded_permissions(scratch_database.engine)),
        equal_to((AF453_TABLES, {"anomaly.read", "anomaly.manage"})),
    )

    command.downgrade(scratch_database.config, PRE_AF453_REVISION)
    scratch_database.engine.dispose()
    assert_that(
        (_anomaly_tables(scratch_database.engine), _seeded_permissions(scratch_database.engine)),
        equal_to((set(), set())),
    )

    command.upgrade(scratch_database.config, AF453_REVISION)
    scratch_database.engine.dispose()
    assert_that(_anomaly_tables(scratch_database.engine), equal_to(AF453_TABLES))


def test_the_migrated_schema_matches_the_anomaly_models():
    engine = create_engine(str(get_config().db_connection_url))
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), SQLModel.metadata)
    ours = [diff for diff in differences if any(table in repr(diff) for table in AF453_TABLES | AF464_TABLES)]

    assert_that(ours, equal_to([]))


def _insert(context, row) -> None:
    with Session(context.postgres_delegate.engine) as session:
        session.add(row)
        session.commit()


def _anomaly(context, *, agent_id=None, organization_id=None, ended_at=None) -> AgentAnomaly:
    now = datetime.now(UTC)
    return AgentAnomaly(
        organization_id=organization_id or context.organization.id,
        agent_id=agent_id or context.agent.id,
        signal=AnomalySignal.TOOL_CALLS_PER_HOUR.value,
        observed_value=400,
        usual_value=100,
        threshold=150,
        started_at=now,
        last_observed_at=now,
        ended_at=ended_at,
    )


def test_an_override_cannot_pair_an_agent_with_another_organization():
    with given([*_GIVEN, there_is_an_agent_in_another_org()]) as context:
        with when("an override names this Organization but the other Organization's Agent"):
            override = AgentAnomalyOverride(
                organization_id=context.organization.id, agent_id=context.other_org_agent.id
            )

            with then("the database rejects it"):
                assert_that(calling(_insert).with_args(context, override), raises(IntegrityError))


def test_an_anomaly_cannot_pair_an_agent_with_another_organization():
    with given([*_GIVEN, there_is_an_agent_in_another_org()]) as context:
        anomaly = _anomaly(context, agent_id=context.other_org_agent.id)

        assert_that(calling(_insert).with_args(context, anomaly), raises(IntegrityError))


def test_an_agent_has_at_most_one_ongoing_anomaly_per_signal_and_subject():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        _insert(context, _anomaly(context))

        assert_that(calling(_insert).with_args(context, _anomaly(context)), raises(IntegrityError))


def test_ended_anomalies_do_not_block_a_new_ongoing_one():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        _insert(context, _anomaly(context, ended_at=datetime.now(UTC)))

        with when("the same signal deviates again"):
            _insert(context, _anomaly(context))

        with then("both are kept"):
            with Session(context.postgres_delegate.engine) as session:
                count = session.exec(select(func.count()).select_from(AgentAnomaly)).one()
            assert_that(count, equal_to(2))


def test_a_hard_cap_must_be_positive():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        override = AgentAnomalyOverride(
            organization_id=context.organization.id, agent_id=context.agent.id, max_llm_calls_per_hour=0
        )

        assert_that(calling(_insert).with_args(context, override), raises(IntegrityError))


def test_the_alert_receipt_migration_creates_its_table_and_removes_it_on_downgrade(scratch_database):
    def tables() -> set[str]:
        scratch_database.engine.dispose()
        return set(inspect(scratch_database.engine).get_table_names()) & AF464_TABLES

    command.upgrade(scratch_database.config, AF464_REVISION)
    assert_that(tables(), equal_to(AF464_TABLES))

    command.downgrade(scratch_database.config, AF453_REVISION)
    assert_that(tables(), equal_to(set()))


def test_the_alerts_migration_keeps_existing_organizations_alerted_and_removes_it_on_downgrade(scratch_database):
    def alerts_column() -> list[dict]:
        scratch_database.engine.dispose()
        columns = inspect(scratch_database.engine).get_columns("organization_anomaly_settings")
        return [column for column in columns if column["name"] == "alerts_enabled"]

    command.upgrade(scratch_database.config, AF464_ALERTS_REVISION)
    (column,) = alerts_column()
    assert_that(column["default"], equal_to("true"))

    command.downgrade(scratch_database.config, AF464_REVISION)
    assert_that(alerts_column(), equal_to([]))
