"""The migrations that create the Tier catalog and put Organizations on it, run against a
database of their own."""

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from hamcrest import assert_that, equal_to
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from api.domains.tiers.models import SEED_TIERS

PRE_MIGRATION_REVISION = "c8e41f7a2d96"
TIER_CATALOG_REVISION = "55e07653f502"
FREE_REPLACES_TRIAL_REVISION = "86bca32c95be"
SUBSCRIPTIONS_REVISION = "38de1199ae19"
_SUSPENSION_COLUMNS = {
    "agent": {"suspended_at", "suspension_reason", "memory_suspended_at", "memory_suspension_reason"},
    "communication_connection": {"suspended_at", "suspension_reason"},
    "agent_webhook": {"suspended_at", "suspension_reason"},
}
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture
def database_before_tiers(monkeypatch):
    source_url = make_url(os.environ["DB_CONNECTION_URL"])
    database_name = f"tiers_{uuid7().hex}"
    admin_engine = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))

    target_url = source_url.set(database=database_name)
    monkeypatch.setenv("ALEMBIC_DB_URL", target_url.render_as_string(False))
    config = Config(ALEMBIC_INI)
    command.upgrade(config, PRE_MIGRATION_REVISION)
    engine = create_engine(target_url)
    try:
        yield SimpleNamespace(config=config, engine=engine)
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                    " WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f'DROP DATABASE "{database_name}"'))
        admin_engine.dispose()


def _columns(engine, table: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table)}


def _insert(connection, **overrides):
    values = {
        "id": uuid7(),
        "key": f"tier_{uuid7().hex[:8]}",
        "name": f"Tier {uuid7().hex[:8]}",
        "activation": "paid",
        "enabled": False,
        "price_usd": 10,
        "monthly_usage_usd": 10,
        "one_time_credit_usd": 0,
        "agent_limit": 1,
        "contact_url": None,
        **overrides,
    }
    connection.execute(
        text(
            "INSERT INTO tier (id, created_at, updated_at, key, name, activation, enabled, price_usd,"
            " monthly_usage_usd, one_time_credit_usd, agent_limit, contact_url)"
            " VALUES (:id, now(), now(), :key, :name, :activation, :enabled, :price_usd, :monthly_usage_usd,"
            " :one_time_credit_usd, :agent_limit, :contact_url)"
        ),
        values,
    )


def test_the_migration_seeds_the_catalog_as_the_models_describe_it_all_switched_off(database_before_tiers):
    database = database_before_tiers

    command.upgrade(database.config, TIER_CATALOG_REVISION)

    with database.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, key, name, activation, enabled, price_usd, monthly_usage_usd, one_time_credit_usd,"
                " agent_limit, allowed_platform_keys, features, contact_url FROM tier ORDER BY sort_order"
            )
        ).all()
    assert_that(
        [
            (
                row.id,
                row.key,
                row.name,
                row.activation,
                row.price_usd,
                row.monthly_usage_usd,
                row.one_time_credit_usd,
                row.agent_limit,
                row.allowed_platform_keys,
                row.features,
                row.contact_url,
            )
            for row in rows
        ],
        equal_to(
            [
                (
                    seed["id"],
                    seed["key"],
                    seed["name"],
                    seed["activation"],
                    seed["price_usd"],
                    seed["monthly_usage_usd"],
                    seed["one_time_credit_usd"],
                    seed["agent_limit"],
                    seed["allowed_platform_keys"],
                    seed["features"],
                    seed["contact_url"],
                )
                for seed in SEED_TIERS
            ]
        ),
    )
    assert_that([row.enabled for row in rows], equal_to([False] * len(SEED_TIERS)))


def test_the_grace_period_defaults_to_a_week(database_before_tiers):
    database = database_before_tiers
    command.upgrade(database.config, TIER_CATALOG_REVISION)

    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO platform_billing_settings (id, payments_enabled, min_purchase_usd, max_purchase_usd,"
                " purchase_fee_percent, updated_at) VALUES (1, false, 5, 500, 0, now())"
            )
        )
        grace_days = connection.execute(text("SELECT payment_grace_days FROM platform_billing_settings")).scalar()
    assert_that(grace_days, equal_to(7))


@pytest.mark.parametrize(
    "overrides",
    [
        {"activation": "free", "price_usd": 0, "monthly_usage_usd": 0},  # a second Free
        {"activation": "none", "price_usd": 0, "monthly_usage_usd": 0, "agent_limit": 0},  # a second none
        {"price_usd": 0},  # a paid Tier for nothing
        {"activation": "contact", "monthly_usage_usd": 0},  # contact-only without a link
        {"activation": "contact", "contact_url": "https://example.com"},  # contact-only granting monthly usage
        {"agent_limit": 0},  # a Tier that runs nothing
        {"activation": "trial"},  # an activation nobody knows
    ],
)
def test_the_database_refuses_a_tier_that_does_not_hold_together(database_before_tiers, overrides):
    database = database_before_tiers
    command.upgrade(database.config, TIER_CATALOG_REVISION)

    with pytest.raises(IntegrityError), database.engine.begin() as connection:
        _insert(connection, **overrides)


def test_the_migration_downgrades_cleanly(database_before_tiers):
    database = database_before_tiers
    command.upgrade(database.config, TIER_CATALOG_REVISION)

    command.downgrade(database.config, PRE_MIGRATION_REVISION)

    assert_that(inspect(database.engine).has_table("tier"), equal_to(False))
    assert_that("payment_grace_days" in _columns(database.engine, "platform_billing_settings"), equal_to(False))
    assert_that({"tier_id", "tier_assigned_by_platform"} & _columns(database.engine, "organization"), equal_to(set()))
    for table, columns in _SUSPENSION_COLUMNS.items():
        assert_that(columns & _columns(database.engine, table), equal_to(set()))
    with database.engine.begin() as connection:
        remaining = connection.execute(text("SELECT count(*) FROM permissions WHERE key = 'tier_hold.manage'")).scalar()
    assert_that(remaining, equal_to(0))


def _organization(connection, name: str = "Acme"):
    organization_id = uuid7()
    connection.execute(
        text(
            "INSERT INTO organization (id, created_at, updated_at, name, allowed_models, is_trial, llm_budget_usd,"
            " llm_budget_duration) VALUES (:id, now(), now(), :name, '[]', false, 100, '30d')"
        ),
        {"id": organization_id, "name": name},
    )
    return organization_id


def test_existing_organizations_stay_off_any_tier(database_before_tiers):
    database = database_before_tiers
    with database.engine.begin() as connection:
        organization_id = _organization(connection)

    command.upgrade(database.config, TIER_CATALOG_REVISION)

    with database.engine.begin() as connection:
        row = connection.execute(
            text("SELECT tier_id, tier_assigned_by_platform FROM organization WHERE id = :id"), {"id": organization_id}
        ).one()
    assert_that(tuple(row), equal_to((None, False)))


def test_a_tier_an_organization_is_on_cannot_be_deleted(database_before_tiers):
    database = database_before_tiers
    command.upgrade(database.config, TIER_CATALOG_REVISION)
    free_id = next(seed["id"] for seed in SEED_TIERS if seed["key"] == "free")
    with database.engine.begin() as connection:
        organization_id = _organization(connection)
        connection.execute(
            text("UPDATE organization SET tier_id = :tier WHERE id = :id"), {"tier": free_id, "id": organization_id}
        )

    with pytest.raises(IntegrityError), database.engine.begin() as connection:
        connection.execute(text("DELETE FROM tier WHERE id = :id"), {"id": free_id})


def test_nothing_is_suspended_and_owners_may_choose_what_stays_held(database_before_tiers):
    database = database_before_tiers
    command.upgrade(database.config, TIER_CATALOG_REVISION)

    for table, columns in _SUSPENSION_COLUMNS.items():
        assert_that(columns <= _columns(database.engine, table), equal_to(True))
    with database.engine.begin() as connection:
        key = connection.execute(
            text("SELECT key FROM permissions WHERE id = 'f236e2c1-a221-559e-946b-9c25232caa30'")
        ).scalar()
    assert_that(key, equal_to("tier_hold.manage"))


def _trial_settings(connection, *, signup: bool, credit: float, agent_limit: int) -> None:
    connection.execute(
        text(
            "INSERT INTO platform_trial_settings (id, self_signup_enabled, credit_usd, agent_limit, updated_at)"
            " VALUES (1, :signup, :credit, :limit, now())"
        ),
        {"signup": signup, "credit": credit, "limit": agent_limit},
    )


def test_free_replacing_the_trial_moves_the_trial_settings_and_trials_onto_free(database_before_tiers):
    database = database_before_tiers
    command.upgrade(database.config, TIER_CATALOG_REVISION)
    with database.engine.begin() as connection:
        _trial_settings(connection, signup=True, credit=15, agent_limit=2)
        trial = _organization(connection, "A trial")
        connection.execute(text("UPDATE organization SET is_trial = true WHERE id = :id"), {"id": trial})
        ordinary = _organization(connection, "Ordinary")

    command.upgrade(database.config, FREE_REPLACES_TRIAL_REVISION)

    with database.engine.begin() as connection:
        free = connection.execute(
            text("SELECT one_time_credit_usd, agent_limit, enabled FROM tier WHERE key = 'free'")
        ).one()
        rows = {
            row.id: row
            for row in connection.execute(text("SELECT id, tier_id, tier_holds_due_at FROM organization")).all()
        }
    assert_that((float(free.one_time_credit_usd), free.agent_limit, free.enabled), equal_to((15.0, 2, True)))
    assert_that(str(rows[trial].tier_id), equal_to(next(str(s["id"]) for s in SEED_TIERS if s["key"] == "free")))
    assert_that(rows[trial].tier_holds_due_at is not None, equal_to(True))
    assert_that((rows[ordinary].tier_id, rows[ordinary].tier_holds_due_at), equal_to((None, None)))
    assert_that({"credit_usd", "agent_limit"} & _columns(database.engine, "platform_trial_settings"), equal_to(set()))


def test_free_replacing_the_trial_downgrades_with_the_settings_back(database_before_tiers):
    database = database_before_tiers
    command.upgrade(database.config, TIER_CATALOG_REVISION)
    with database.engine.begin() as connection:
        _trial_settings(connection, signup=True, credit=15, agent_limit=2)
    command.upgrade(database.config, FREE_REPLACES_TRIAL_REVISION)

    command.downgrade(database.config, TIER_CATALOG_REVISION)

    with database.engine.begin() as connection:
        settings = connection.execute(text("SELECT credit_usd, agent_limit FROM platform_trial_settings")).one()
    assert_that((settings.credit_usd, settings.agent_limit), equal_to((15.0, 2)))
    assert_that("tier_holds_due_at" in _columns(database.engine, "organization"), equal_to(False))


def test_the_subscriptions_migration_adds_the_table_and_the_credit_kinds(database_before_tiers):
    database = database_before_tiers
    command.upgrade(database.config, SUBSCRIPTIONS_REVISION)

    with database.engine.begin() as connection:
        kinds = set(connection.execute(text("SELECT unnest(enum_range(NULL::credit_grant_kind))::text")).scalars())
    assert_that({"TIER_CREDIT", "ALLOWANCE", "ALLOWANCE_EXPIRY"} <= kinds, equal_to(True))
    assert_that(
        {"scheduled_tier_id", "provider_schedule_id", "activated_at"}
        <= _columns(database.engine, "organization_subscription"),
        equal_to(True),
    )

    command.downgrade(database.config, FREE_REPLACES_TRIAL_REVISION)

    assert_that(inspect(database.engine).has_table("organization_subscription"), equal_to(False))
