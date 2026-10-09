"""Track integration generations and bind gateway tokens to their credential source.

Revision ID: 90f1a42d98bc
Revises: 7f20a9c813de
"""

import json

import sqlalchemy as sa
from alembic import op
from api.core.config import get_config
from api.infrastructure.crypto import decrypt_token, encrypt_token

revision = "90f1a42d98bc"
down_revision = "7f20a9c813de"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_integration_isolation", sa.Column("source", sa.String(30), nullable=False, server_default="agent_secret")
    )
    op.drop_constraint("uq_agent_integration_isolation", "agent_integration_isolation", type_="unique")
    op.create_unique_constraint(
        "uq_agent_integration_isolation", "agent_integration_isolation", ["agent_id", "provider", "source"]
    )
    op.create_table(
        "agent_integration_runtime",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agent.id", ondelete="CASCADE"), nullable=False),
        sa.Column("generation", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("bindings", sa.JSON(), nullable=False),
        sa.Column("previous_bindings", sa.JSON(), nullable=False),
        sa.UniqueConstraint("agent_id", name="uq_agent_integration_runtime"),
    )
    op.add_column("gateway_token", sa.Column("binding_id", sa.Uuid(), nullable=True))
    op.add_column("gateway_token", sa.Column("generation", sa.Uuid(), nullable=True))
    op.add_column("gateway_token", sa.Column("source", sa.String(30), nullable=False, server_default="agent_secret"))
    op.execute("""
        UPDATE gateway_token t SET binding_id = s.id
        FROM agent_secret s WHERE s.agent_id = t.agent_id AND s.provider = t.provider
    """)


def downgrade() -> None:
    bind = op.get_bind()
    for bindings in bind.execute(
        sa.text(
            "SELECT bindings FROM agent_integration_runtime WHERE state IN ('preparing', 'provisioned', 'ready', 'stopping')"
        )
    ).scalars():
        if bindings.get("sharepoint", {}).get("isolated"):
            raise RuntimeError("Stop isolated SharePoint Agents before downgrading integration generations")
    grants = bind.execute(
        sa.text("SELECT id, content FROM agent_secret WHERE provider = 'sharepoint' AND content IS NOT NULL")
    ).all()
    if grants:
        key = get_config().agent_token_encryption_key
        if not key:
            raise RuntimeError("AGENT_TOKEN_ENCRYPTION_KEY is required to downgrade SharePoint broker metadata")
        for binding_id, ciphertext in grants:
            payload = json.loads(decrypt_token(ciphertext, key))
            # Keep the latest rotated grant; earlier strict schemas reject broker fields.
            for field in ("broker_access_token", "broker_expires_at", "store_revision", "subject_id"):
                payload.pop(field, None)
            bind.execute(
                sa.text("UPDATE agent_secret SET content = :content WHERE id = :id"),
                {"id": binding_id, "content": encrypt_token(json.dumps(payload), key)},
            )
    op.execute("DELETE FROM agent_integration_isolation WHERE source != 'agent_secret'")
    op.drop_constraint("uq_agent_integration_isolation", "agent_integration_isolation", type_="unique")
    op.drop_column("agent_integration_isolation", "source")
    op.create_unique_constraint(
        "uq_agent_integration_isolation", "agent_integration_isolation", ["agent_id", "provider"]
    )
    op.drop_column("gateway_token", "source")
    op.drop_column("gateway_token", "generation")
    op.drop_column("gateway_token", "binding_id")
    op.drop_table("agent_integration_runtime")
