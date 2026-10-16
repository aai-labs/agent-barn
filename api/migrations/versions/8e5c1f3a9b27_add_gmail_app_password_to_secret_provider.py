"""Add gmail_app_password to the agent_secret provider constraint.

Revision ID: 8e5c1f3a9b27
Revises: a78bcde4b918

_OLD is copied verbatim from 4b9e2d7c1a35 (add_gmail_to_secret_provider), the most recent
revision to recreate the provider constraint — not reconstructed from an older one.
"""

from alembic import op

revision: str = "8e5c1f3a9b27"
down_revision: str | None = "a78bcde4b918"
branch_labels: str | None = None
depends_on: str | None = None

_OLD = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'zoho_mail', 'zoho_calendar', "
    "'firecrawl', 'slack', 'pipedrive', 'google_workspace', 'sharepoint', 'apollo', 'gmail')"
)
_NEW = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'zoho_mail', 'zoho_calendar', "
    "'firecrawl', 'slack', 'pipedrive', 'google_workspace', 'sharepoint', 'apollo', 'gmail', "
    "'gmail_app_password')"
)


def upgrade() -> None:
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _NEW)


def downgrade() -> None:
    # Any gmail_app_password rows would violate the restored constraint; drop them first so
    # the downgrade is runnable rather than failing with a CheckViolation.
    op.execute("DELETE FROM agent_secret WHERE provider = 'gmail_app_password'")
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _OLD)
