"""add organization value settings

Revision ID: 1045836844da
Revises: 39ea6a8e2fe4
Create Date: 2026-09-29

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "1045836844da"
down_revision: str | None = "39ea6a8e2fe4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organization_value_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hourly_rate_usd", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", name="uq_organization_value_settings_organization_id"),
        sa.CheckConstraint(
            "hourly_rate_usd IS NULL OR hourly_rate_usd >= 0",
            name="ck_organization_value_settings_hourly_rate_usd",
        ),
    )
    op.create_table(
        "organization_outcome_minutes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outcome_type", sa.String(length=64), nullable=False),
        sa.Column("minutes_saved", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "outcome_type",
            name="uq_organization_outcome_minutes_organization_id_outcome_type",
        ),
        sa.CheckConstraint("minutes_saved > 0", name="ck_organization_outcome_minutes_minutes_saved"),
    )


def downgrade() -> None:
    op.drop_table("organization_outcome_minutes")
    op.drop_table("organization_value_settings")
