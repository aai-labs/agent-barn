"""Add google_workspace to agent_secret provider check constraint.

Chains off 8c68a090f9c7, the merge of the 4a7c2e9f1b63 and a3d7f5e91c62 heads. That
merge is a no-op and 4a7c2e9f1b63 does not touch this constraint, so the last revision
to recreate ck_agent_secret_provider is still a3d7f5e91c62 and the _OLD snapshot below
matches what is on the table. Every revision touching this constraint recreates it from
its own snapshot, which is exactly the collision 5e0adff0f5e2 had to repair between
slack and pipedrive.

Revision ID: b7e2c4d81f39
Revises: 8c68a090f9c7
"""

from alembic import op

revision: str = "b7e2c4d81f39"
down_revision: str = "8c68a090f9c7"
branch_labels: str | None = None
depends_on: str | None = None

_OLD = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'gmail', 'google_calendar', 'google_sheets', 'zoho_mail', 'zoho_calendar', "
    "'firecrawl', 'slack', 'pipedrive')"
)
_NEW = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'gmail', 'google_calendar', 'google_sheets', 'zoho_mail', 'zoho_calendar', "
    "'firecrawl', 'slack', 'pipedrive', 'google_workspace')"
)


def upgrade() -> None:
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _NEW)


def downgrade() -> None:
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _OLD)
