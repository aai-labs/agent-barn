"""init current schema

Revision ID: 8f3c2a7d9b10
Revises:
Create Date: 2026-04-22 12:45:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8f3c2a7d9b10"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

organization_role_enum = postgresql.ENUM(
    "ADMIN", "MEMBER", "OWNER", name="organizationrole", create_type=False
)


def upgrade() -> None:
    organization_role_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "organization",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.CheckConstraint("length(name) >= 3", name="check_name_length_min"),
        sa.CheckConstraint("length(name) <= 255", name="check_name_length_max"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organization_name", "organization", ["name"], unique=False)

    op.create_table(
        "user",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column(
            "is_superuser",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("security_stamp", sa.String(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_email", "user", ["email"], unique=True)
    op.create_index("ix_user_is_superuser", "user", ["is_superuser"], unique=False)

    op.create_table(
        "user_organization",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", organization_role_enum, nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_user_organization_one_owner_per_org",
        "user_organization",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("role = 'OWNER'"),
    )
    op.create_index(
        "uq_user_organization",
        "user_organization",
        ["user_id", "organization_id"],
        unique=True,
    )

    op.create_table(
        "refresh_token",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stamp", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_refresh_token_token", "refresh_token", ["token"], unique=False)

    op.create_table(
        "password_reset_token",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_used", sa.Boolean(), nullable=False),
        sa.Column("jti", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("password_reset_token")

    op.drop_index("ix_refresh_token_token", table_name="refresh_token")
    op.drop_table("refresh_token")

    op.drop_index("uq_user_organization", table_name="user_organization")
    op.drop_index(
        "uq_user_organization_one_owner_per_org", table_name="user_organization"
    )
    op.drop_table("user_organization")

    op.drop_index("ix_user_is_superuser", table_name="user")
    op.drop_index("ix_user_email", table_name="user")
    op.drop_table("user")

    op.drop_index("ix_organization_name", table_name="organization")
    op.drop_table("organization")

    organization_role_enum.drop(op.get_bind(), checkfirst=True)
