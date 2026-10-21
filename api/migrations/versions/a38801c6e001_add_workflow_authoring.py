"""Agent-owned workflow definitions, immutable versions.

Revision ID: a38801c6e001
Revises: c42e91b7a603
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "a38801c6e001"
down_revision = "c42e91b7a603"
branch_labels = None
depends_on = None


def base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "workflow",
        *base_columns(),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agent.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("revision >= 1", name="ck_workflow_revision"),
    )
    op.create_index("ix_workflow_agent_id", "workflow", ["agent_id"])
    op.create_table(
        "workflow_version",
        *base_columns(),
        sa.Column("workflow_id", sa.Uuid(), sa.ForeignKey("workflow.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("snapshot", JSONB, nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.UniqueConstraint("workflow_id", "number", name="uq_workflow_version_number"),
        sa.CheckConstraint("number >= 1", name="ck_workflow_version_number"),
    )
    op.create_index("ix_workflow_version_workflow_id", "workflow_version", ["workflow_id"])
    # Deletion is permitted only for the owning aggregate's hard purge. Provenance
    # may be nulled by User deletion, but snapshot/identity/number cannot change.
    op.execute("""CREATE FUNCTION protect_workflow_version() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF EXISTS (SELECT 1 FROM workflow WHERE id = OLD.workflow_id) THEN
                    RAISE EXCEPTION 'Workflow versions are immutable';
                END IF;
                RETURN OLD;
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id OR NEW.workflow_id IS DISTINCT FROM OLD.workflow_id
                OR NEW.number IS DISTINCT FROM OLD.number OR NEW.snapshot IS DISTINCT FROM OLD.snapshot
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR (NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id AND NEW.created_by_user_id IS NOT NULL)
            THEN RAISE EXCEPTION 'Workflow versions are immutable'; END IF;
            RETURN NEW;
        END $$""")
    op.execute(
        "CREATE TRIGGER workflow_version_immutable BEFORE UPDATE OR DELETE ON workflow_version FOR EACH ROW EXECUTE FUNCTION protect_workflow_version()"
    )


def downgrade() -> None:
    op.drop_table("workflow_version")
    op.execute("DROP FUNCTION protect_workflow_version()")
    op.drop_table("workflow")
