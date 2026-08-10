"""Add pipedrive to agent_secret provider check constraint.

Revision ID: 6c23680e1076
Revises: 96333a5d58e4

Includes 'slack' too: on environments where the sibling branch d731eac8a160
(add slack) already ran and inserted slack rows before this branch caught
up, recreating the constraint without slack fails with a CheckViolation
against that existing data.
"""

from alembic import op

revision: str = "6c23680e1076"
down_revision: str | None = "96333a5d58e4"
branch_labels: str | None = None
depends_on: str | None = None

_OLD = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'gmail', 'google_calendar', 'zoho_mail', 'zoho_calendar', 'firecrawl')"
)
_NEW = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'gmail', 'google_calendar', 'zoho_mail', 'zoho_calendar', 'firecrawl', 'slack', 'pipedrive')"
)


def upgrade() -> None:
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _NEW)


def downgrade() -> None:
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _OLD)
