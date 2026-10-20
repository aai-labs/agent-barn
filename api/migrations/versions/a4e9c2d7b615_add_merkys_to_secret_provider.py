"""Add merkys to the agent_secret provider constraint.

Revision ID: a4e9c2d7b615
Revises: 49e4d8bea6de

_OLD is copied verbatim from 8e5c1f3a9b27 (add_gmail_app_password_to_secret_provider), the
most recent revision to recreate the provider constraint — not reconstructed from an older one.
5e0adff0f5e2 exists because two branches each rebuilt this constraint from a stale base and
silently dropped a provider that was already in use.
"""

from alembic import op

revision: str = "a4e9c2d7b615"
down_revision: str | None = "49e4d8bea6de"
branch_labels: str | None = None
depends_on: str | None = None

_OLD = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'zoho_mail', 'zoho_calendar', "
    "'firecrawl', 'slack', 'pipedrive', 'google_workspace', 'sharepoint', 'apollo', 'gmail', "
    "'gmail_app_password')"
)
_NEW = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'zoho_mail', 'zoho_calendar', "
    "'firecrawl', 'slack', 'pipedrive', 'google_workspace', 'sharepoint', 'apollo', 'gmail', "
    "'gmail_app_password', 'merkys')"
)


def upgrade() -> None:
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _NEW)


def downgrade() -> None:
    # Any merkys rows would violate the restored constraint; drop them first so the
    # downgrade is runnable rather than failing with a CheckViolation.
    op.execute("DELETE FROM agent_secret WHERE provider = 'merkys'")
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _OLD)
