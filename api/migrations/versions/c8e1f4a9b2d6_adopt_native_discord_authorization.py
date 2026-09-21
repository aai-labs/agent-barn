"""adopt Hermes-native Discord authorization settings

Revision ID: c8e1f4a9b2d6
Revises: b6d4f2a8c913
Create Date: 2026-09-17 00:00:00.000000

Discord's native Hermes adapter has global user, role, and channel gates. It
does not have Agent Barn's separate guild and DM policies. Existing settings
therefore become the native shape. Ambiguous legacy policies remain closed
rather than broadening access during migration.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "c8e1f4a9b2d6"
down_revision: str | None = "b6d4f2a8c913"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE communication_connection
            SET
                settings = jsonb_strip_nulls(jsonb_build_object(
                    'allowed_channel_ids', COALESCE((settings::jsonb)->'allowed_channel_ids', '[]'::jsonb),
                    'allowed_user_ids', COALESCE((settings::jsonb)->'allowed_user_ids', '[]'::jsonb),
                    'allowed_role_ids', COALESCE((settings::jsonb)->'allowed_role_ids', '[]'::jsonb),
                    'allow_all_users', CASE
                        WHEN COALESCE(((settings::jsonb)->>'allow_all_users')::boolean, false) THEN true
                        WHEN (settings::jsonb)->>'group_policy' = 'open'
                         AND (settings::jsonb)->>'dm_policy' = 'open'
                         AND COALESCE(jsonb_array_length((settings::jsonb)->'allowed_channel_ids'), 0) = 0
                         AND COALESCE(jsonb_array_length((settings::jsonb)->'allowed_user_ids'), 0) = 0
                         AND COALESCE(jsonb_array_length((settings::jsonb)->'allowed_role_ids'), 0) = 0
                        THEN true
                        ELSE false
                    END,
                    'require_mention', COALESCE(((settings::jsonb)->>'require_mention')::boolean, true),
                    'home_channel_id', (settings::jsonb)->'home_channel_id'
                ))::json,
                schema_version = 2
            WHERE platform_key = 'discord'
            """
        )
    )


def downgrade() -> None:
    # Guild and separate DM policy values have no Hermes-native representation.
    # Restore the former closed defaults rather than silently broadening access.
    op.execute(
        sa.text(
            """
            UPDATE communication_connection
            SET
                settings = ((settings::jsonb) || jsonb_build_object(
                    'guild_ids', '[]'::jsonb,
                    'group_policy', 'allowlist',
                    'dm_policy', 'off'
                ))::json,
                schema_version = 1
            WHERE platform_key = 'discord'
            """
        )
    )
