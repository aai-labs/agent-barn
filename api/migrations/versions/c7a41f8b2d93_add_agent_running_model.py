"""Record the model an Agent actually started on.

`Agent.model` (and the Organization default it falls back to) describe what an Agent
*would* start on. A running pod is a different fact: the model is merged into
openclaw.json by the init script at container start and never re-read, so an Agent that
inherits keeps serving the default that was current when it started, however many times
the Organization changes that default afterwards.

Without this column the read model reported the freshly resolved value for a running
Agent, which is the value it will adopt on its next start — not the one it is serving.

Empty string means "not running", matching the sentinel `Agent.model` already uses.
No backfill: Agents running at deploy time report no pending switch until their next
start, which is the conservative direction — it under-reports rather than inventing a
model an Agent was never started on.

Revision ID: c7a41f8b2d93
Revises: b3d17c9a5e42
"""

import sqlalchemy as sa
from alembic import op

revision: str = "c7a41f8b2d93"
down_revision: str | None = "b3d17c9a5e42"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "agent",
        sa.Column("running_model", sa.String(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("agent", "running_model")
