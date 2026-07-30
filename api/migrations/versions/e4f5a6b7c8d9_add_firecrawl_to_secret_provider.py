"""Add firecrawl to agent_secret provider check constraint.

Revision ID: e4f5a6b7c8d9
Revises: a7b8c9d0e1f2
"""

from typing import Union

from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

_OLD = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'gmail', 'google_calendar', 'zoho_mail', 'zoho_calendar')"
)
_NEW = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'gmail', 'google_calendar', 'zoho_mail', 'zoho_calendar', 'firecrawl')"
)


def upgrade() -> None:
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _NEW)


def downgrade() -> None:
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _OLD)
