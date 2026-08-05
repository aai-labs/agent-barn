"""add self-service Organization provenance and scoped security audit

Revision ID: 2a4f6c8e1b30
Revises: 181dcfcc93ef
Create Date: 2026-07-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2a4f6c8e1b30"
down_revision: str | None = "181dcfcc93ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organization",
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_organization_created_by_user",
        "organization",
        "user",
        ["created_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_organization_created_by_user_id",
        "organization",
        ["created_by_user_id"],
        unique=False,
    )
    op.execute(
        sa.text(
            """
            UPDATE organization AS organization
            SET created_by_user_id = owner_membership.user_id
            FROM user_organization AS owner_membership
            WHERE owner_membership.organization_id = organization.id
              AND owner_membership.role = 'OWNER'
            """
        )
    )

    for table_name in ("event_outbox_message", "event_delivery"):
        op.add_column(
            table_name,
            sa.Column(
                "event_scope",
                sa.String(length=32),
                nullable=False,
                server_default="ORGANIZATION",
            ),
        )
        op.alter_column(table_name, "event_scope", server_default=None)
        op.alter_column(
            table_name,
            "organization_id",
            existing_type=sa.Uuid(),
            nullable=True,
        )
        op.create_check_constraint(
            f"ck_{table_name}_scope_organization",
            table_name,
            "(event_scope = 'ORGANIZATION' AND organization_id IS NOT NULL) "
            "OR (event_scope = 'PLATFORM' AND organization_id IS NULL)",
        )

    op.create_index(
        "ix_event_outbox_message_scope_occurred",
        "event_outbox_message",
        ["event_scope", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_event_delivery_scope_status",
        "event_delivery",
        ["event_scope", "status"],
        unique=False,
    )
    op.create_table(
        "security_audit_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_scope", sa.String(length=32), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("actor_display", sa.String(length=320), nullable=True),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("subject_display", sa.String(length=320), nullable=True),
        sa.Column("reason", sa.String(length=1000), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_security_audit_record_event_id"),
    )
    op.create_index(
        "ix_security_audit_record_scope_occurred",
        "security_audit_record",
        ["event_scope", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_security_audit_record_organization_occurred",
        "security_audit_record",
        ["organization_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_security_audit_record_subject",
        "security_audit_record",
        ["subject_type", "subject_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_security_audit_record_subject", table_name="security_audit_record")
    op.drop_index(
        "ix_security_audit_record_organization_occurred",
        table_name="security_audit_record",
    )
    op.drop_index(
        "ix_security_audit_record_scope_occurred",
        table_name="security_audit_record",
    )
    op.drop_table("security_audit_record")
    op.execute("DELETE FROM event_delivery WHERE event_scope = 'PLATFORM'")
    op.execute("DELETE FROM event_outbox_message WHERE event_scope = 'PLATFORM'")
    op.drop_index("ix_event_delivery_scope_status", table_name="event_delivery")
    op.drop_index(
        "ix_event_outbox_message_scope_occurred",
        table_name="event_outbox_message",
    )
    for table_name in ("event_delivery", "event_outbox_message"):
        op.drop_constraint(
            f"ck_{table_name}_scope_organization",
            table_name,
            type_="check",
        )
        op.alter_column(
            table_name,
            "organization_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )
        op.drop_column(table_name, "event_scope")

    op.drop_index("ix_organization_created_by_user_id", table_name="organization")
    op.drop_constraint(
        "fk_organization_created_by_user",
        "organization",
        type_="foreignkey",
    )
    op.drop_column("organization", "created_by_user_id")
