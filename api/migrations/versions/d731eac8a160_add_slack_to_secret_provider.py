"""Add slack to agent_secret provider check constraint.

Revision ID: d731eac8a160
Revises: 181dcfcc93ef

Includes 'pipedrive' too: on environments where the sibling branch
6c23680e1076 (add pipedrive) already ran and inserted pipedrive rows before
this branch caught up, recreating the constraint without pipedrive fails
with a CheckViolation against that existing data.
"""

from alembic import op

revision: str = "d731eac8a160"
down_revision: str | None = "181dcfcc93ef"
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
