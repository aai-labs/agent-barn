"""Shared SSH credentials, same-tenant assignments and per-generation runtime identity."""

import sqlalchemy as sa
from alembic import op

revision = "a193d7f0c284"
down_revision = "22b93965859f"
branch_labels = None
depends_on = None


def _base():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "ssh_credential",
        *_base(),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("private_key_encrypted", sa.String(), nullable=False),
        sa.Column("public_key", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.String(100), nullable=False),
        sa.Column("algorithm", sa.String(40), nullable=False),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("servers", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.UniqueConstraint("id", "organization_id", name="uq_ssh_credential_tenant"),
        sa.UniqueConstraint("organization_id", "fingerprint", name="uq_ssh_credential_fingerprint"),
        sa.UniqueConstraint("organization_id", "name", name="uq_ssh_credential_name"),
        sa.CheckConstraint("mode IN ('restricted', 'unrestricted')", name="ck_ssh_credential_mode"),
        sa.CheckConstraint("origin IN ('import', 'generate')", name="ck_ssh_credential_origin"),
        sa.CheckConstraint("revision > 0", name="ck_ssh_credential_revision"),
    )
    op.create_index("ix_ssh_credential_organization_id", "ssh_credential", ["organization_id"])
    op.create_table(
        "agent_ssh_credential",
        *_base(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("credential_id", sa.Uuid(), nullable=False),
        sa.UniqueConstraint("agent_id", "credential_id", name="uq_agent_ssh_credential"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"], ["agent.id", "agent.organization_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["credential_id", "organization_id"],
            ["ssh_credential.id", "ssh_credential.organization_id"],
            ondelete="RESTRICT",
        ),
    )
    for column in ("agent_id", "organization_id", "credential_id"):
        op.create_index("ix_agent_ssh_credential_" + column, "agent_ssh_credential", [column])
    op.create_table(
        "ssh_runtime_credential",
        *_base(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64)),
        sa.Column("generation", sa.Uuid()),
        sa.Column("applied", sa.JSON(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("agent_id", name="uq_ssh_runtime_agent"),
        sa.UniqueConstraint("token_hash", name="uq_ssh_runtime_token"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"], ["agent.id", "agent.organization_id"], ondelete="CASCADE"
        ),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM ssh_credential)")):
        raise RuntimeError("Detach and delete SSH credentials explicitly before downgrading")
    op.drop_table("ssh_runtime_credential")
    op.drop_table("agent_ssh_credential")
    op.drop_table("ssh_credential")
