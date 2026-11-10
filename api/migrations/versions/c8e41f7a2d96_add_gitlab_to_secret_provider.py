"""Add gitlab to the agent_secret provider constraint.

Revision ID: c8e41f7a2d96
Revises: c84888d0018a

_OLD is copied verbatim from a4e9c2d7b615 (add_merkys_to_secret_provider), the most recent
revision to recreate the provider constraint — not reconstructed from an older one.
"""

from alembic import op

revision: str = "c8e41f7a2d96"
down_revision: str | None = "c84888d0018a"
branch_labels: str | None = None
depends_on: str | None = None

_OLD = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'zoho_mail', 'zoho_calendar', "
    "'firecrawl', 'slack', 'pipedrive', 'google_workspace', 'sharepoint', 'apollo', 'gmail', "
    "'gmail_app_password', 'merkys')"
)
_NEW = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'zoho_mail', 'zoho_calendar', "
    "'firecrawl', 'slack', 'pipedrive', 'google_workspace', 'sharepoint', 'apollo', 'gmail', "
    "'gmail_app_password', 'merkys', 'gitlab')"
)


def upgrade() -> None:
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _NEW)


def downgrade() -> None:
    # Any gitlab rows would violate the restored constraint; drop them first so the
    # downgrade is runnable rather than failing with a CheckViolation.
    op.execute("DELETE FROM agent_secret WHERE provider = 'gitlab'")
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _OLD)
