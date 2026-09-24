"""Add sharepoint to the agent_secret provider constraint.

Revision ID: e2b7c4d19a58
Revises: 4b4bb4af4d31

_OLD is copied verbatim from c9f1b30a7d42 (remove_legacy_google_providers), the most recent
revision to recreate the provider constraint — not reconstructed from an older one.
5e0adff0f5e2 exists because two branches each rebuilt this constraint from a stale base and
silently dropped a provider that was already in use.
"""

from alembic import op

revision: str = "e2b7c4d19a58"
down_revision: str | None = "4b4bb4af4d31"
branch_labels: str | None = None
depends_on: str | None = None

_OLD = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'zoho_mail', 'zoho_calendar', "
    "'firecrawl', 'slack', 'pipedrive', 'google_workspace')"
)
_NEW = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'zoho_mail', 'zoho_calendar', "
    "'firecrawl', 'slack', 'pipedrive', 'google_workspace', 'sharepoint')"
)


def upgrade() -> None:
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _NEW)


def downgrade() -> None:
    # Any sharepoint rows would violate the restored constraint; drop them first so the
    # downgrade is runnable rather than failing with a CheckViolation.
    op.execute("DELETE FROM agent_secret WHERE provider = 'sharepoint'")
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _OLD)
