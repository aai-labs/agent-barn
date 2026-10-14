"""Remove the retired, unused bundled Zoho Mail Skill.

Revision ID: b91a73e42c60
Revises: 0d612dc60e9a
"""

import sqlalchemy as sa
from alembic import op

revision = "b91a73e42c60"
down_revision = "0d612dc60e9a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    skill_ids = (
        connection.execute(
            sa.text("""
            SELECT id FROM skill
            WHERE slug = 'aai-zoho-mail' AND source = 'aai_cli'
              AND organization_id IS NULL AND agent_id IS NULL
            FOR UPDATE
        """)
        )
        .scalars()
        .all()
    )
    for skill_id in skill_ids:
        # Lock the published sources too, so new pins/forks cannot race the checks.
        connection.execute(
            sa.text("SELECT id FROM skill_version WHERE skill_id = :id FOR UPDATE"),
            {"id": skill_id},
        ).all()
        for table, column in (
            ("agent_skill", "skill_id"),
            ("agent_template_skill", "skill_id"),
            ("platform_template_skill", "skill_id"),
            ("agent_template_override_draft_skill", "skill_id"),
            ("agent_template_override_version_skill", "skill_id"),
            ("skill_version", "source_skill_id"),
            ("skill_draft", "source_skill_id"),
        ):
            if connection.execute(
                sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE {column} = :id)"),
                {"id": skill_id},
            ).scalar_one():
                # Keep referenced content and pins. The next migration repairs its
                # retired provider metadata without deleting the lineage.
                break
        else:
            # Only this unused built-in lineage and its owned versions/files/draft cascade.
            connection.execute(sa.text("DELETE FROM skill WHERE id = :id"), {"id": skill_id})


def downgrade() -> None:
    # Retired content is not recreated: its provider no longer exists in the API.
    pass
