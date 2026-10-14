"""Remove retired Zoho and Slack tool provider requirements from retained Skills.

Revision ID: c42e91b7a603
Revises: b91a73e42c60
"""

from alembic import op

revision = "c42e91b7a603"
down_revision = "b91a73e42c60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("skill", "skill_version", "skill_draft"):
        # Historical snapshots need the same repair as lineage metadata. Content,
        # pins, provenance, and timestamps remain unchanged. Preserve list order.
        op.execute(f"""
            UPDATE {table}
            SET required_providers = COALESCE(
                (
                    SELECT json_agg(provider ORDER BY position)
                    FROM json_array_elements_text(required_providers)
                        WITH ORDINALITY AS requirements(provider, position)
                    WHERE provider NOT IN ('zoho_mail', 'zoho_calendar', 'slack')
                ),
                '[]'::json
            )
            WHERE required_providers::jsonb ?| ARRAY['zoho_mail', 'zoho_calendar', 'slack']
        """)


def downgrade() -> None:
    # Removed requirements cannot be reconstructed, and their providers are retired.
    pass
