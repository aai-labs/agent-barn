"""add agent personas

Revision ID: b7d2e94c1a30
Revises: 3680352c132d
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op

revision = "b7d2e94c1a30"
down_revision = "3680352c132d"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "agent_persona",
        sa.Column("id", sa.Uuid(), primary_key=True),
        *_timestamps(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("emoji", sa.String(length=16), nullable=True),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_persona_agent_organization",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("agent_id", "key", name="uq_agent_persona_agent_key"),
        sa.UniqueConstraint("id", "organization_id", name="uq_agent_persona_id_organization"),
        sa.UniqueConstraint("id", "agent_id", name="uq_agent_persona_id_agent"),
    )
    op.create_index("ix_agent_persona_organization", "agent_persona", ["organization_id"])

    op.create_table(
        "agent_persona_version",
        sa.Column("id", sa.Uuid(), primary_key=True),
        *_timestamps(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("soul_md", sa.Text(), nullable=False),
        sa.Column("identity_md", sa.Text(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["persona_id", "organization_id"],
            ["agent_persona.id", "agent_persona.organization_id"],
            name="fk_agent_persona_version_persona_organization",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("persona_id", "version", name="uq_agent_persona_version_persona_version"),
    )
    op.create_index("ix_agent_persona_version_organization", "agent_persona_version", ["organization_id"])


def downgrade() -> None:
    op.drop_table("agent_persona_version")
    op.drop_table("agent_persona")
