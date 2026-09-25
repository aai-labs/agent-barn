"""add honcho usage event

Revision ID: b3f1c07d92ae
Revises: 87ec190e0f7d
Create Date: 2026-09-03

Honcho sends every model call to LiteLLM on one service credential and carries no
workspace identity on the request, so LiteLLM cannot split that spend. Its
telemetry does name the workspace and count tokens; these rows hold that, and the
token shares divide LiteLLM's authoritative total for Honcho's key.
"""

import sqlalchemy as sa
from alembic import op

revision = "b3f1c07d92ae"
down_revision = "87ec190e0f7d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "honcho_usage_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("workspace_name", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("call_purpose", sa.String(length=100), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # Honcho retries a failed batch, so the same CloudEvent can arrive twice;
        # counting it twice would skew every workspace's share.
        sa.UniqueConstraint("event_id", name="uq_honcho_usage_event_event_id"),
    )
    # Reads are always "totals per workspace over a window", never a scan.
    op.create_index(
        "ix_honcho_usage_event_workspace_occurred",
        "honcho_usage_event",
        ["workspace_name", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_honcho_usage_event_workspace_occurred", table_name="honcho_usage_event")
    op.drop_table("honcho_usage_event")
