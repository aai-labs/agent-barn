"""index agent_chat_message and tool_call for platform-wide time ranges

The Platform View stats surface (AF-256) reads both telemetry tables over a
trailing window across every Agent. Every pre-existing index on both tables is
prefixed by agent_id, so none of them can seek to a time range — the planner
either seq-scans the table or walks an entire index and discards non-matches.

Both new indexes lead with occurred_at for the range predicate, then carry the
remaining columns each query projects so the reads stay index-only:

- agent_chat_message: direction for the inbound/outbound split, agent_id for the
  distinct-active-Agents query. Without agent_id that query seq-scans, because an
  index scan plus a heap fetch per row costs more than reading the table.
- tool_call: agent_id for the same distinct query, and organization_id because
  tool_call carries its own denormalised org rather than joining Agent — without
  it an Organization-filtered read drops to a seq scan (measured 1,583 buffers
  against 145 with the column included).

Built without CONCURRENTLY, matching every other migration in this repo. That
takes a SHARE lock and blocks INSERTs on the ingest write path for the duration
of the build (~0.75us/row). If these tables grow large enough for that stall to
drop telemetry, recreate them concurrently outside a migration.

Revision ID: c4d1e8f2a730
Revises: 8c68a090f9c7
Create Date: 2026-08-10 17:05:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d1e8f2a730"
down_revision: str | Sequence[str] | None = "8c68a090f9c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_agent_chat_message_occurred_at_direction",
        "agent_chat_message",
        ["occurred_at", "direction", "agent_id"],
    )
    op.create_index(
        "ix_tool_call_occurred_at_agent",
        "tool_call",
        ["occurred_at", "agent_id", "organization_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tool_call_occurred_at_agent", table_name="tool_call")
    op.drop_index(
        "ix_agent_chat_message_occurred_at_direction",
        table_name="agent_chat_message",
    )
