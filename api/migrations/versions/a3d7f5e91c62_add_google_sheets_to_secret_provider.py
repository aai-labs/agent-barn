"""Add google_sheets to agent_secret provider check constraint.

Chains off 3df7fef61316, staging's merge of the 5e0adff0f5e2 (#109) and f6a7b8c9d0e1
(#110) heads. That merge is a no-op and f6a7b8c9d0e1 does not touch this constraint, so
the last revision to recreate ck_agent_secret_provider is still 5e0adff0f5e2 and the _OLD
snapshot below matches what is on the table. Every revision touching this constraint
recreates it from its own snapshot, which is exactly the collision 5e0adff0f5e2 had to
repair between slack and pipedrive.

Revision ID: a3d7f5e91c62
Revises: 3df7fef61316
"""

from alembic import op

revision: str = "a3d7f5e91c62"
down_revision: str = "3df7fef61316"
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
