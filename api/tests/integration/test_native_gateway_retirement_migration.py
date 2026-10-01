import importlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4, uuid7

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, Table, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlmodel import Session, select

from api.domains.agents.models import Agent
from api.domains.communications.models import (
    CommunicationConnection,
    CommunicationDelivery,
    CommunicationDeliveryStatus,
    CommunicationDirection,
    CommunicationJournalEntry,
    CommunicationJournalStage,
)
from api.domains.conversations.models import AgentChatMessage
from api.domains.organizations.models import Organization

PREVIOUS_REVISION = "45bcefcb0749"
REVISION = "72c4a9e1b6d8"


@pytest.fixture
def retirement_database(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"native_retirement_{uuid7().hex}"
    admin = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    target_url = source_url.set(database=database_name)
    monkeypatch.setenv("ALEMBIC_DB_URL", target_url.render_as_string(False))
    config = Config(Path(__file__).resolve().parents[2] / "alembic.ini")
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(target_url)
    try:
        yield SimpleNamespace(config=config, engine=engine)
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": database_name},
            )
            connection.execute(text(f'DROP DATABASE "{database_name}"'))
        admin.dispose()


def seed(engine, *, bulk=False):
    now = datetime.now(UTC)
    table = Table("communication_connection", MetaData(), autoload_with=engine)
    with Session(engine) as session:
        organizations = [Organization(name="Retirement A"), Organization(name="Retirement B")]
        session.add_all(organizations)
        session.flush()
        rows = []
        for organization in organizations:
            agent = Agent(name="Historical Agent", organization_id=organization.id, deleted_at=now)
            session.add(agent)
            session.flush()
            for platform in ("slack", "discord", "telegram", "teams", "web", "email"):
                connection = CommunicationConnection(
                    organization_id=organization.id,
                    agent_id=agent.id,
                    platform_key=platform,
                    display_name=platform,
                    credentials_encrypted="historical-credentials",
                    settings={"historical": "policy"},
                    credential_fingerprint=uuid4().hex,
                    credential_scope_key="historical",
                    retired_at=now if platform == "discord" else None,
                    enabled=platform != "telegram",
                )
                session.connection().execute(
                    table.insert().values(**connection.model_dump(), driver_key_encrypted="historical-driver")
                )
                session.flush()
                for direction in CommunicationDirection:
                    for status in CommunicationDeliveryStatus:
                        message = AgentChatMessage(
                            agent_id=agent.id,
                            connection_id=connection.id,
                            openclaw_msg_id=uuid4().hex,
                            session_key="historical-session",
                            channel_id="historical-channel",
                            content="preserved message",
                            occurred_at=now - timedelta(days=1),
                            direction=direction.value,
                        )
                        session.add(message)
                        session.flush()
                        delivery = CommunicationDelivery(
                            organization_id=organization.id,
                            agent_id=agent.id,
                            connection_id=connection.id,
                            message_id=message.id,
                            direction=direction,
                            status=status,
                            idempotency_key=uuid4().hex,
                            ordering_key="historical-order",
                            attempt_count=3,
                            available_at=now - timedelta(days=1),
                            claimed_at=now - timedelta(hours=1),
                            lease_expires_at=now + timedelta(hours=1),
                            awaiting_input=True,
                            completed_at=now - timedelta(hours=2)
                            if status
                            not in {CommunicationDeliveryStatus.PENDING, CommunicationDeliveryStatus.PROCESSING}
                            else None,
                            last_error_code="HISTORICAL_FAILURE",
                            last_error_message="preserved failure",
                            provider_message_id="preserved-provider-id",
                            submission_key=uuid4().hex,
                            request_digest="d" * 64,
                            envelope={"historical": "preserved payload"},
                        )
                        session.add(delivery)
                        session.flush()
                        session.add(
                            CommunicationJournalEntry(
                                organization_id=organization.id,
                                agent_id=agent.id,
                                connection_id=connection.id,
                                delivery_id=delivery.id,
                                occurred_at=now - timedelta(days=1),
                                stage=CommunicationJournalStage.QUEUED,
                            )
                        )
                        rows.append((platform, status, delivery.model_dump()))
        if bulk:
            template = session.get(CommunicationDelivery, rows[0][2]["id"])
            assert template is not None
            for _ in range(1001):
                data = template.model_dump()
                data.update(id=uuid7(), idempotency_key=uuid4().hex, submission_key=uuid4().hex)
                delivery = CommunicationDelivery(**data)
                session.add(delivery)
                rows.append(("slack", CommunicationDeliveryStatus.PENDING, delivery.model_dump()))
        session.commit()
        return rows


def connection_history(engine):
    table = Table("communication_connection", MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        return {row["id"]: dict(row) for row in connection.execute(table.select()).mappings()}


def test_migration_cancels_only_native_live_work_and_preserves_history(retirement_database):
    database = retirement_database
    originals = seed(database.engine, bulk=True)
    schema = inspect(database.engine).get_columns("communication_connection")
    original_connections = connection_history(database.engine)
    with Session(database.engine) as session:
        messages = {row.id: row.model_dump() for row in session.exec(select(AgentChatMessage)).all()}
        prior_journal_ids = {row.id for row in session.exec(select(CommunicationJournalEntry)).all()}
    command.upgrade(database.config, REVISION)
    with Session(database.engine) as session:
        for platform, old_status, original in originals:
            delivery = session.get(CommunicationDelivery, original["id"])
            assert delivery is not None
            changed = platform in {"slack", "discord", "telegram", "teams"} and old_status in {
                CommunicationDeliveryStatus.PENDING,
                CommunicationDeliveryStatus.PROCESSING,
            }
            if changed:
                assert delivery.status == CommunicationDeliveryStatus.CANCELLED
                assert delivery.completed_at is not None
                assert delivery.cancel_requested_at is not None
                assert delivery.claimed_at is None and delivery.lease_expires_at is None
                assert delivery.awaiting_input is False
                assert delivery.last_error_code == "NATIVE_GATEWAY_RETIRED"
                for field in (
                    "envelope",
                    "message_id",
                    "provider_message_id",
                    "submission_key",
                    "request_digest",
                    "attempt_count",
                    "available_at",
                ):
                    assert getattr(delivery, field) == original[field]
            else:
                assert delivery.model_dump() == original
        assert connection_history(database.engine) == original_connections
        assert {row.id: row.model_dump() for row in session.exec(select(AgentChatMessage)).all()} == messages
        entries = session.exec(select(CommunicationJournalEntry)).all()
        assert prior_journal_ids.issubset({row.id for row in entries})
        retirement = [row for row in entries if row.error_code == "NATIVE_GATEWAY_RETIRED"]
        expected = {
            original["id"]
            for platform, status, original in originals
            if platform in {"slack", "discord", "telegram", "teams"}
            and status in {CommunicationDeliveryStatus.PENDING, CommunicationDeliveryStatus.PROCESSING}
        }
        assert {row.delivery_id for row in retirement} == expected
        assert len(retirement) == len(expected)
        assert all(
            row.stage == CommunicationJournalStage.POLICY_REJECTED and row.disposition is None for row in retirement
        )
        after = {row.id: row.model_dump() for row in session.exec(select(CommunicationDelivery)).all()}
        after_journal = {row.id: row.model_dump() for row in entries}
    migration = importlib.import_module("api.migrations.versions.72c4a9e1b6d8_retire_native_gateway_work")
    with database.engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    command.downgrade(database.config, PREVIOUS_REVISION)
    command.upgrade(database.config, REVISION)
    with Session(database.engine) as session:
        assert {row.id: row.model_dump() for row in session.exec(select(CommunicationDelivery)).all()} == after
        assert {
            row.id: row.model_dump() for row in session.exec(select(CommunicationJournalEntry)).all()
        } == after_journal
    assert [column["name"] for column in inspect(database.engine).get_columns("communication_connection")] == [
        column["name"] for column in schema
    ]


def test_retirement_rolls_back_delivery_changes_when_journaling_fails(retirement_database):
    database = retirement_database
    originals = seed(database.engine)
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE communication_operation_journal ADD CONSTRAINT reject_retirement_test CHECK (error_code IS DISTINCT FROM 'NATIVE_GATEWAY_RETIRED')"
            )
        )
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        command.upgrade(database.config, REVISION)
    with Session(database.engine) as session:
        for _, _, original in originals:
            delivery = session.get(CommunicationDelivery, original["id"])
            assert delivery is not None
            assert delivery.model_dump() == original
        assert not any(
            entry.error_code == "NATIVE_GATEWAY_RETIRED"
            for entry in session.exec(select(CommunicationJournalEntry)).all()
        )
    with database.engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PREVIOUS_REVISION
