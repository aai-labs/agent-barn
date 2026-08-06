"""Add google_sheets to agent_secret provider check constraint.

Chains after 5e0adff0f5e2 rather than running beside it. Every revision touching this
constraint drops and recreates it from its own snapshot of the allowed list, so siblings
silently drop each other's providers — which is exactly what 5e0adff0f5e2 had to repair
between slack and pipedrive. Sequencing keeps each snapshot correct.

Revision ID: a3d7f5e91c62
Revises: 5e0adff0f5e2
"""

from alembic import op

revision: str = "a3d7f5e91c62"
down_revision: str | None = "5e0adff0f5e2"
branch_labels: str | None = None
depends_on: str | None = None

_OLD = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'gmail', 'google_calendar', 'zoho_mail', 'zoho_calendar', 'firecrawl', 'slack', 'pipedrive')"
)
_NEW = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'gmail', 'google_calendar', 'google_sheets', 'zoho_mail', 'zoho_calendar', "
    "'firecrawl', 'slack', 'pipedrive')"
)


def upgrade() -> None:
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _NEW)


def downgrade() -> None:
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _OLD)
