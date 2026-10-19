"""Add gmail to the agent_secret provider constraint.

Revision ID: 4b9e2d7c1a35
Revises: b3d8e1f4a6c2

Gmail returns as a read-only aai-cli integration beside Google Workspace. c9f1b30a7d42
removed the old per-service gmail provider and deleted its rows; this only allows the
value again.

_OLD is copied verbatim from f6c2a8d41b73 (add_apollo_to_secret_provider), the most recent
revision to recreate the provider constraint — not reconstructed from an older one.
5e0adff0f5e2 exists because two branches each rebuilt this constraint from a stale base and
silently dropped a provider that was already in use.
"""

from alembic import op

revision: str = "4b9e2d7c1a35"
down_revision: str | None = "b3d8e1f4a6c2"
branch_labels: str | None = None
depends_on: str | None = None

_OLD = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'zoho_mail', 'zoho_calendar', "
    "'firecrawl', 'slack', 'pipedrive', 'google_workspace', 'sharepoint', 'apollo')"
)
_NEW = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'zoho_mail', 'zoho_calendar', "
    "'firecrawl', 'slack', 'pipedrive', 'google_workspace', 'sharepoint', 'apollo', 'gmail')"
)


def upgrade() -> None:
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _NEW)


def downgrade() -> None:
    # Any gmail rows would violate the restored constraint; drop them first so the
    # downgrade is runnable rather than failing with a CheckViolation.
    op.execute("DELETE FROM agent_secret WHERE provider = 'gmail'")
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _OLD)
