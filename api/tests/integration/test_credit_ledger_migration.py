"""AF-381 migration: the credit ledger. Every Organization already on credit opens it with
its current ceiling, so the ledger adds up to the ceiling from the start; Organizations
on a renewing limit get no ledger. It downgrades cleanly and matches the models."""

from decimal import Decimal
from uuid import uuid7

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from hamcrest import assert_that, equal_to
from sqlalchemy import create_engine, inspect, text
from sqlmodel import SQLModel

# Every model module must be imported for the metadata comparison to see its tables.
import api.domains.organizations.models  # noqa: F401
from api.core.config import get_config
from api.tests.integration.test_trial_onboarding_migration import AF368_HEAD, scratch_database  # noqa: F401

AF381_LEDGER = "c5e2a7d91f04"
LEDGER = "organization_credit_grant"


def _insert_organization(connection, *, ceiling: float, window: str, is_trial: bool):
    organization_id = uuid7()
    connection.execute(
        text(
            "INSERT INTO organization (id, created_at, updated_at, name, allowed_models, llm_budget_usd, "
            "llm_budget_duration, is_trial) VALUES (:id, now(), now(), 'Existing Org', '[]', :ceiling, :window, "
            ":is_trial)"
        ),
        {"id": organization_id, "ceiling": ceiling, "window": window, "is_trial": is_trial},
    )
    return organization_id


def test_organizations_on_credit_open_their_ledger_with_their_ceiling(scratch_database):  # noqa: F811
    command.upgrade(scratch_database.config, AF368_HEAD)
    with scratch_database.engine.begin() as connection:
        trial = _insert_organization(connection, ceiling=10, window="once", is_trial=True)
        ended_trial = _insert_organization(connection, ceiling=40, window="once", is_trial=False)
        monthly = _insert_organization(connection, ceiling=100, window="30d", is_trial=False)

    command.upgrade(scratch_database.config, AF381_LEDGER)
    scratch_database.engine.dispose()

    with scratch_database.engine.connect() as connection:
        rows = connection.execute(text(f"SELECT organization_id, kind, credit_usd FROM {LEDGER}")).all()
    assert_that(
        sorted((row[0], row[1], row[2]) for row in rows),
        equal_to(sorted([(trial, "TRIAL", Decimal(10)), (ended_trial, "ADJUSTMENT", Decimal(40))])),
    )
    assert_that(monthly in {row[0] for row in rows}, equal_to(False))


def test_the_ledger_downgrades_cleanly_and_upgrades_again(scratch_database):  # noqa: F811
    command.upgrade(scratch_database.config, AF381_LEDGER)
    command.downgrade(scratch_database.config, AF368_HEAD)
    scratch_database.engine.dispose()
    assert_that(LEDGER in inspect(scratch_database.engine).get_table_names(), equal_to(False))

    command.upgrade(scratch_database.config, AF381_LEDGER)
    scratch_database.engine.dispose()
    assert_that(LEDGER in inspect(scratch_database.engine).get_table_names(), equal_to(True))


def test_the_migrated_schema_matches_the_models_for_af381():
    engine = create_engine(str(get_config().db_connection_url))
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), SQLModel.metadata)
    ours = [
        diff
        for diff in differences
        if any(
            name in repr(diff)
            for name in (
                LEDGER,
                "agent_limit",
                "trial_expired_at",
                "platform_organization_settings",
                "platform_provisioned_at",
            )
        )
    ]
    assert_that(ours, equal_to([]))


def test_trials_already_out_of_credit_are_expired_by_the_migration(scratch_database):  # noqa: F811
    """Out of credit is what the live alert said: it counts spend the proxy doesn't see,
    so a trial alerted at 100% is expired even when its snapshot alone reads under."""
    command.upgrade(scratch_database.config, "d8b3f1a6c925")
    with scratch_database.engine.begin() as connection:
        spent = _insert_organization(connection, ceiling=10, window="once", is_trial=True)
        spent_elsewhere = _insert_organization(connection, ceiling=10, window="once", is_trial=True)
        left = _insert_organization(connection, ceiling=10, window="once", is_trial=True)
        unobserved = _insert_organization(connection, ceiling=10, window="once", is_trial=True)
        ended = _insert_organization(connection, ceiling=10, window="once", is_trial=False)
        for organization_id, spend, alerted in (
            (spent, 10.5, 100),
            (spent_elsewhere, 6.0, 100),
            (left, 4.0, 80),
            (ended, 12.0, 100),
        ):
            connection.execute(
                text("UPDATE organization SET llm_spend_usd = :spend, llm_alerted_threshold = :alerted WHERE id = :id"),
                {"spend": spend, "alerted": alerted, "id": organization_id},
            )

    command.upgrade(scratch_database.config, "e4a9c2d7b318")
    scratch_database.engine.dispose()

    with scratch_database.engine.connect() as connection:
        expired = {
            row[0] for row in connection.execute(text("SELECT id FROM organization WHERE trial_expired_at IS NOT NULL"))
        }
    assert_that(expired, equal_to({spent, spent_elsewhere}))
    assert_that(unobserved in expired, equal_to(False))


def test_existing_accounts_that_did_not_sign_themselves_up_count_as_set_up_by_the_platform(scratch_database):  # noqa: F811
    """So nobody's behaviour changes: only new invitees create Organizations on credit."""
    command.upgrade(scratch_database.config, "a7d4e2c9b816")
    with scratch_database.engine.begin() as connection:
        ids = {}
        for name, signed_up in (("brought-in", False), ("signed-up", True)):
            ids[name] = uuid7()
            connection.execute(
                text(
                    'INSERT INTO "user" (id, created_at, updated_at, email, hashed_password, is_platform_admin, '
                    "security_stamp, signed_up_at) VALUES (:id, now(), now(), :email, 'x', false, 's', "
                    "CASE WHEN :signed_up THEN now() END)"
                ),
                {"id": ids[name], "email": f"{name}@example.com", "signed_up": signed_up},
            )

    command.upgrade(scratch_database.config, "b8e5f3a1c207")
    scratch_database.engine.dispose()

    with scratch_database.engine.connect() as connection:
        provisioned = {
            row[0]
            for row in connection.execute(text('SELECT id FROM "user" WHERE platform_provisioned_at IS NOT NULL'))
        }
    assert_that(provisioned, equal_to({ids["brought-in"]}))
