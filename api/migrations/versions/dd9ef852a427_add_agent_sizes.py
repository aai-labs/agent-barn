"""Add the Agent Size catalog, seeded with the size every Agent runs on today

Revision ID: dd9ef852a427
Revises: 3bbf2465b9cb
Create Date: 2026-10-22

Agent Sizes, PR 1: a platform-managed catalog of the CPU and memory an Agent's container runs
with. One row is seeded, "Standard", as the default, with the values the builders hard-coded
until now (requests 320Mi / 50m, limits 1Gi / 500m), so every Agent keeps exactly the
resources it had. Requests and limits are stored apart: the namespace quota binds on
requests.memory, so the request decides how many Agents fit and the limit how far one may grow.

The database keeps the catalog usable on its own: positive requests no larger than their
limits, unique names, at most one default (a partial unique index), and a default that is
always enabled. No Agent column is added here; Agents gain a size of their own in a later PR.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dd9ef852a427"
down_revision: str | Sequence[str] | None = "3bbf2465b9cb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "agent_sizes"
_STANDARD_ID = "00000000-0000-7000-8000-00000000a51e"
_MIB = 1024**2
_GIB = 1024**3


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False, unique=True),
        sa.Column("cpu_request_millicores", sa.Integer(), nullable=False),
        sa.Column("cpu_limit_millicores", sa.Integer(), nullable=False),
        sa.Column("memory_request_bytes", sa.BigInteger(), nullable=False),
        sa.Column("memory_limit_bytes", sa.BigInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("cpu_request_millicores > 0", name="ck_agent_sizes_cpu_request_positive"),
        sa.CheckConstraint(
            "cpu_request_millicores <= cpu_limit_millicores", name="ck_agent_sizes_cpu_request_le_limit"
        ),
        sa.CheckConstraint("memory_request_bytes > 0", name="ck_agent_sizes_memory_request_positive"),
        sa.CheckConstraint("memory_request_bytes <= memory_limit_bytes", name="ck_agent_sizes_memory_request_le_limit"),
        sa.CheckConstraint("enabled OR NOT is_default", name="ck_agent_sizes_default_enabled"),
    )
    op.create_index(
        "uq_agent_sizes_default",
        _TABLE,
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.execute(
        sa.text(
            f"""
            INSERT INTO {_TABLE} (
                id, created_at, updated_at, name,
                cpu_request_millicores, cpu_limit_millicores,
                memory_request_bytes, memory_limit_bytes,
                enabled, is_default, sort_order
            ) VALUES (
                '{_STANDARD_ID}', now(), now(), 'Standard',
                50, 500, {320 * _MIB}, {1 * _GIB},
                true, true, 0
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_index("uq_agent_sizes_default", table_name=_TABLE)
    op.drop_table(_TABLE)
