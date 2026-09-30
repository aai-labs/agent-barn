"""Remove the retired bundled Slack Platform Skill.

Slack remains a supported communication platform and Agent Secret provider.  This
migration removes only the obsolete ``aai-slack`` Skill lineage, whose instructions
were incorrectly surfaced as an assignable Skill requiring a Slack credential.

The Skill's own drafts, versions, and files cascade from the lineage.  References
from Templates and Agent Template Overrides are cleared first because those link
tables deliberately restrict Skill deletion.  Agent assignments cascade with the
lineage, matching the existing retirement behavior for obsolete bundled Skills.

Downgrade cannot restore the deleted Skill content; a future replacement must be
introduced as a new bundled Skill definition.

Revision ID: b7c9d1e3f5a7
Revises: af0a523a3dd6
"""

from alembic import op

revision: str = "b7c9d1e3f5a7"
down_revision: str | None = "af0a523a3dd6"
branch_labels: str | None = None
depends_on: str | None = None

_RETIRED_SKILL_IDS = """
    SELECT id FROM skill
    WHERE slug = 'aai-slack'
      AND organization_id IS NULL
      AND agent_id IS NULL
      AND source = 'aai_cli'
"""

_RESTRICTING_SKILL_LINK_TABLES = (
    "agent_template_skill",
    "platform_template_skill",
    "platform_template_draft_skill",
    "agent_template_override_draft_skill",
    "agent_template_override_version_skill",
)


def upgrade() -> None:
    for table in _RESTRICTING_SKILL_LINK_TABLES:
        op.execute(f"DELETE FROM {table} WHERE skill_id IN ({_RETIRED_SKILL_IDS})")
    op.execute(f"DELETE FROM skill WHERE id IN ({_RETIRED_SKILL_IDS})")


def downgrade() -> None:
    # The bundled files and metadata are intentionally not recreated on downgrade.
    pass
