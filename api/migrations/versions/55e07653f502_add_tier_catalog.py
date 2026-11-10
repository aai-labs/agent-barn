"""Add the Tier catalog, seeded from the public pricing page, and the payment grace period

Revision ID: 55e07653f502
Revises: c8e41f7a2d96
Create Date: 2026-11-08

Tiers, PR 1: a platform-managed catalog of what an Organization may use and what it pays.
Five rows are seeded, all switched off: Free, Cloud Tier 1, Cloud Tier 2, the contact-only
Supervised Pilot, and the system's `none` Tier for an Organization with no Tier it may use.
Nothing reads the catalog yet: no Organization is on a Tier, so behavior is unchanged.

The database keeps each Tier coherent on its own: a paid Tier has a price and is the only
kind granting monthly usage, Free and none cost nothing, a contact-only Tier has a link, none
grants nothing and is never offered, and there is one Free and one none.

`platform_billing_settings.payment_grace_days` is how long a past-due subscription keeps its
Tier; nothing reads it until subscriptions arrive.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "55e07653f502"
down_revision: str | Sequence[str] | None = "c8e41f7a2d96"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "tier"
_ALL_FEATURES = [
    "custom_agents",
    "integrations",
    "templates_and_skills",
    "workflows",
    "agent_webhooks",
    "agent_memory",
    "team",
    "priority_support",
]
_SEEDS = (
    {
        "id": "00000000-0000-7000-8000-0000000071e0",
        "key": "free",
        "name": "Free",
        "tagline": "A premade agent on Telegram, and nothing else.",
        "activation": "free",
        "sort_order": 10,
        "price_usd": "0",
        "price_note": None,
        "monthly_usage_usd": "0",
        "one_time_credit_usd": "10",
        "agent_limit": 1,
        "allowed_platform_keys": ["agentbarn_telegram", "web"],
        "features": ["team"],
        "contact_url": None,
    },
    {
        "id": "00000000-0000-7000-8000-0000000071e1",
        "key": "cloud_1",
        "name": "Cloud Tier 1",
        "tagline": "Full platform access with $20 of usage every month.",
        "activation": "paid",
        "sort_order": 20,
        "price_usd": "20",
        "price_note": "per month",
        "monthly_usage_usd": "20",
        "one_time_credit_usd": "10",
        "agent_limit": 1,
        "allowed_platform_keys": None,
        "features": [feature for feature in _ALL_FEATURES if feature != "priority_support"],
        "contact_url": None,
    },
    {
        "id": "00000000-0000-7000-8000-0000000071e2",
        "key": "cloud_2",
        "name": "Cloud Tier 2",
        "tagline": "Full platform access with $100 of usage every month.",
        "activation": "paid",
        "sort_order": 30,
        "price_usd": "100",
        "price_note": "per month",
        "monthly_usage_usd": "100",
        "one_time_credit_usd": "10",
        "agent_limit": 4,
        "allowed_platform_keys": None,
        "features": _ALL_FEATURES,
        "contact_url": None,
    },
    {
        "id": "00000000-0000-7000-8000-0000000071e3",
        "key": "pilot",
        "name": "Supervised Pilot",
        "tagline": "One workflow scoped and put in front of real work over one week, with daily support.",
        "activation": "contact",
        "sort_order": 40,
        "price_usd": "500",
        "price_note": "per one-week pilot",
        "monthly_usage_usd": "0",
        "one_time_credit_usd": "0",
        "agent_limit": 4,
        "allowed_platform_keys": None,
        "features": _ALL_FEATURES,
        "contact_url": "https://agentbarn.dev/pricing",
    },
    {
        "id": "00000000-0000-7000-8000-0000000071ff",
        "key": "none",
        "name": "No tier",
        "tagline": "An Organization with no Tier it may use: no Agents, no features.",
        "activation": "none",
        "sort_order": 1000,
        "price_usd": "0",
        "price_note": None,
        "monthly_usage_usd": "0",
        "one_time_credit_usd": "0",
        "agent_limit": 0,
        "allowed_platform_keys": [],
        "features": [],
        "contact_url": None,
    },
)


def _money(name: str) -> sa.Column:
    return sa.Column(name, sa.Numeric(10, 2), nullable=False, server_default="0")


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False, unique=True),
        sa.Column("name", sa.String(length=64), nullable=False, unique=True),
        sa.Column("tagline", sa.String(length=200), nullable=True),
        sa.Column("activation", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        _money("price_usd"),
        sa.Column("price_note", sa.String(length=64), nullable=True),
        _money("monthly_usage_usd"),
        _money("one_time_credit_usd"),
        sa.Column("agent_limit", sa.Integer(), nullable=False),
        sa.Column("allowed_platform_keys", JSONB(), nullable=True),
        sa.Column("features", JSONB(), nullable=False, server_default="[]"),
        sa.Column("contact_url", sa.String(length=500), nullable=True),
        sa.CheckConstraint("activation IN ('free', 'paid', 'contact', 'none')", name="ck_tier_activation_known"),
        sa.CheckConstraint("price_usd >= 0", name="ck_tier_price_non_negative"),
        sa.CheckConstraint("monthly_usage_usd >= 0", name="ck_tier_monthly_usage_non_negative"),
        sa.CheckConstraint("one_time_credit_usd >= 0", name="ck_tier_one_time_credit_non_negative"),
        sa.CheckConstraint("agent_limit >= 0", name="ck_tier_agent_limit_non_negative"),
        sa.CheckConstraint("activation <> 'paid' OR price_usd > 0", name="ck_tier_paid_has_price"),
        sa.CheckConstraint("activation IN ('paid', 'contact') OR price_usd = 0", name="ck_tier_unpaid_costs_nothing"),
        sa.CheckConstraint("activation = 'paid' OR monthly_usage_usd = 0", name="ck_tier_monthly_usage_only_paid"),
        sa.CheckConstraint("activation <> 'contact' OR contact_url IS NOT NULL", name="ck_tier_contact_has_url"),
        sa.CheckConstraint("activation = 'none' OR agent_limit >= 1", name="ck_tier_runs_an_agent"),
        sa.CheckConstraint(
            "activation <> 'none' OR (NOT enabled AND agent_limit = 0 AND one_time_credit_usd = 0)",
            name="ck_tier_none_grants_nothing",
        ),
    )
    op.create_index(
        "uq_tier_system_activation",
        _TABLE,
        ["activation"],
        unique=True,
        postgresql_where=sa.text("activation IN ('free', 'none')"),
    )
    insert = sa.text(
        f"""
        INSERT INTO {_TABLE} (
            id, created_at, updated_at, key, name, tagline, activation, enabled, sort_order,
            price_usd, price_note, monthly_usage_usd, one_time_credit_usd, agent_limit,
            allowed_platform_keys, features, contact_url
        ) VALUES (
            :id, now(), now(), :key, :name, :tagline, :activation, false, :sort_order,
            CAST(:price_usd AS numeric), :price_note, CAST(:monthly_usage_usd AS numeric),
            CAST(:one_time_credit_usd AS numeric), :agent_limit,
            CAST(:allowed_platform_keys AS jsonb), CAST(:features AS jsonb), :contact_url
        )
        """
    )
    for seed in _SEEDS:
        platforms = seed["allowed_platform_keys"]
        op.execute(
            insert.bindparams(
                **{
                    **seed,
                    "allowed_platform_keys": None if platforms is None else json.dumps(platforms),
                    "features": json.dumps(seed["features"]),
                }
            )
        )

    op.add_column(
        "platform_billing_settings",
        sa.Column("payment_grace_days", sa.Integer(), nullable=False, server_default="7"),
    )
    op.create_check_constraint(
        "ck_platform_billing_settings_grace_days_range",
        "platform_billing_settings",
        "payment_grace_days >= 0 AND payment_grace_days <= 60",
    )


def downgrade() -> None:
    op.drop_constraint("ck_platform_billing_settings_grace_days_range", "platform_billing_settings", type_="check")
    op.drop_column("platform_billing_settings", "payment_grace_days")
    op.drop_index("uq_tier_system_activation", table_name=_TABLE)
    op.drop_table(_TABLE)
