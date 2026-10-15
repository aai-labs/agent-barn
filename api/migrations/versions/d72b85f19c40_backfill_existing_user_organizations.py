"""Give existing membership-free accounts their own Organization once.

Revision ID: d72b85f19c40
Revises: c61a94e72b30

Verified non-platform accounts that never self-signed up are eligible. Existing
Memberships (including invitations) and all self-signup accounts are untouched.
"""

import json
from uuid import uuid7

import sqlalchemy as sa
from alembic import op

revision = "d72b85f19c40"
down_revision = "c61a94e72b30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from api.core.config import get_config

    config = get_config()
    connection = op.get_bind()
    users = connection.execute(
        sa.text(
            'SELECT u.id, u.full_name FROM "user" u '
            "WHERE NOT u.is_platform_admin AND u.email_verified_at IS NOT NULL AND u.signed_up_at IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM user_organization m WHERE m.user_id = u.id) "
            "ORDER BY u.id FOR UPDATE OF u"
        )
    ).mappings()
    for user in users:
        words = (user["full_name"] or "").split()
        name = f"{words[0][:240]}'s Organization" if words else "My Organization"
        # Recheck Memberships after taking the User lock: a creation/invitation may
        # have committed while this migration was waiting for the same account.
        connection.execute(
            sa.text(
                "WITH inserted AS ("
                "INSERT INTO organization "
                "(id, created_at, updated_at, name, created_by_user_id, allowed_models, is_trial, "
                "llm_budget_usd, llm_budget_duration) "
                "SELECT :organization_id, now(), now(), :name, u.id, CAST(:models AS jsonb), false, :budget, '30d' "
                'FROM "user" u WHERE u.id = :user_id '
                "AND NOT EXISTS (SELECT 1 FROM user_organization m WHERE m.user_id = u.id) "
                "AND (SELECT count(*) FROM organization o WHERE o.created_by_user_id = u.id) < :creation_limit "
                "RETURNING id) "
                "INSERT INTO user_organization (id, created_at, updated_at, user_id, organization_id, role) "
                "SELECT :membership_id, now(), now(), :user_id, id, 'OWNER' FROM inserted"
            ),
            {
                "organization_id": uuid7(),
                "membership_id": uuid7(),
                "user_id": user["id"],
                "name": name,
                "models": json.dumps([config.agent_default_model.removeprefix("litellm/openrouter/")]),
                "budget": config.organization_default_llm_budget_usd,
                "creation_limit": config.organization_creation_limit,
            },
        )


def downgrade() -> None:
    # This is a data backfill. Organizations may now own user work, so retain them.
    pass
