"""add_skill_table_and_rework_agent_skill

Revision ID: 032ff9a474bb
Revises: d4e5f6a7b8c9
Create Date: 2026-06-11 14:21:35.719971

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "032ff9a474bb"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "skill",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("required_providers", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("zip_content", sa.LargeBinary(), nullable=False),
        sa.Column("tools_pointer", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "name", name="uq_skill_organization_name"),
    )
    op.create_index("ix_skill_organization_id", "skill", ["organization_id"], unique=False)

    op.execute("DELETE FROM agent_skill")
    op.add_column("agent_skill", sa.Column("skill_id", sa.Uuid(), nullable=False))
    op.drop_constraint("uq_agent_skill_agent_file_path", "agent_skill", type_="unique")
    op.drop_constraint("ck_agent_skill_source", "agent_skill", type_="check")
    op.create_unique_constraint("uq_agent_skill_agent_skill", "agent_skill", ["agent_id", "skill_id"])
    op.create_foreign_key(
        "fk_agent_skill_skill_id",
        "agent_skill",
        "skill",
        ["skill_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("agent_skill", "source")
    op.drop_column("agent_skill", "skill_name")
    op.drop_column("agent_skill", "skill_file_path")
    op.drop_column("agent_skill", "skill_content")


def downgrade() -> None:
    op.drop_constraint("fk_agent_skill_skill_id", "agent_skill", type_="foreignkey")
    op.drop_constraint("uq_agent_skill_agent_skill", "agent_skill", type_="unique")
    op.drop_column("agent_skill", "skill_id")

    op.add_column(
        "agent_skill",
        sa.Column("source", sa.VARCHAR(), nullable=False, server_default="aai_cli"),
    )
    op.add_column(
        "agent_skill",
        sa.Column("skill_name", sa.VARCHAR(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "agent_skill",
        sa.Column(
            "skill_file_path",
            sa.VARCHAR(length=1024),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "agent_skill",
        sa.Column("skill_content", sa.TEXT(), nullable=False, server_default=""),
    )
    op.create_unique_constraint("uq_agent_skill_agent_file_path", "agent_skill", ["agent_id", "skill_file_path"])
    op.create_check_constraint("ck_agent_skill_source", "agent_skill", "source IN ('aai_cli', 'custom')")

    op.drop_index("ix_skill_organization_id", table_name="skill")
    op.drop_table("skill")
