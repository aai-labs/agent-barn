"""Add google_sheets to agent_secret provider check constraint.

Chains after AF-209's slack revision rather than running beside it. Both rewrite the
same constraint from their own snapshot of the allowed list, so as siblings whichever
ran second would drop the other's provider — and would fail outright if a row using it
already existed. Sequencing them makes each snapshot correct.

Revision ID: a3d7f5e91c62
Revises: 71a0d9a1a91d
"""

from alembic import op

revision: str = "a3d7f5e91c62"
down_revision: str | None = "71a0d9a1a91d"
branch_labels: str | None = None
depends_on: str | None = None

_OLD = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'gmail', 'google_calendar', 'zoho_mail', 'zoho_calendar', 'firecrawl', 'slack')"
)
_NEW = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'gmail', 'google_calendar', 'google_sheets', 'zoho_mail', 'zoho_calendar', "
    "'firecrawl', 'slack')"
)


def upgrade() -> None:
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _NEW)


def downgrade() -> None:
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _OLD)
