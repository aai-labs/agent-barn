"""Add Event Delivery Monitor indexes (AF-247)

Revision ID: b7f3d8e1c4a9
Revises: 181dcfcc93ef
Create Date: 2026-07-31

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7f3d8e1c4a9"
down_revision: str | None = "181dcfcc93ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Per-state stale/oldest lookups (PENDING/created_at, ENQUEUED/enqueued_at,
    # PROCESSING/claimed_at) and status-aggregation counts for the summary endpoint.
    op.create_index(
        "ix_event_delivery_status_created_at",
        "event_delivery",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_event_delivery_status_enqueued_at",
        "event_delivery",
        ["status", "enqueued_at"],
    )
    op.create_index(
        "ix_event_delivery_status_claimed_at",
        "event_delivery",
        ["status", "claimed_at"],
    )
    # Deterministic explorer ordering by (created_at, delivery_id).
    op.create_index(
        "ix_event_delivery_created_at_id",
        "event_delivery",
        ["created_at", "id"],
    )
    # Organization-filtered explorer browsing without a full scan.
    op.create_index(
        "ix_event_delivery_organization_created_at",
        "event_delivery",
        ["organization_id", "created_at"],
    )
    # Case-insensitive prefix search (Organization name, event name, handler name).
    # text_pattern_ops keeps a left-anchored LIKE/ILIKE 'prefix%' index-friendly
    # regardless of the database's collation, unlike a plain btree index.
    op.execute(
        "CREATE INDEX ix_event_delivery_handler_name_lower_pattern "
        "ON event_delivery (lower(handler_name) text_pattern_ops)"
    )
    op.execute(
        "CREATE INDEX ix_event_outbox_message_event_name_lower_pattern "
        "ON event_outbox_message (lower(event_name) text_pattern_ops)"
    )
    op.execute("CREATE INDEX ix_organization_name_lower_pattern ON organization (lower(name) text_pattern_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_organization_name_lower_pattern")
    op.execute("DROP INDEX IF EXISTS ix_event_outbox_message_event_name_lower_pattern")
    op.execute("DROP INDEX IF EXISTS ix_event_delivery_handler_name_lower_pattern")
    op.drop_index("ix_event_delivery_organization_created_at", table_name="event_delivery")
    op.drop_index("ix_event_delivery_created_at_id", table_name="event_delivery")
    op.drop_index("ix_event_delivery_status_claimed_at", table_name="event_delivery")
    op.drop_index("ix_event_delivery_status_enqueued_at", table_name="event_delivery")
    op.drop_index("ix_event_delivery_status_created_at", table_name="event_delivery")
