"""reconcile agent_secret provider check constraint after slack and pipedrive merge

Both d731eac8a160 (add slack) and 6c23680e1076 (add pipedrive) independently
dropped and recreated ck_agent_secret_provider from the same 9-provider base,
each adding only its own value. In the merged history, 6c23680e1076 runs after
d731eac8a160 and clobbers it, silently dropping 'slack' from the constraint.
This re-creates it with every current SecretProvider value.

Revision ID: 5e0adff0f5e2
Revises: 717d83f33baf
Create Date: 2026-08-06 11:45:17.442254

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5e0adff0f5e2"
down_revision: str | Sequence[str] | None = "717d83f33baf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'gmail', 'google_calendar', 'zoho_mail', 'zoho_calendar', 'firecrawl', 'pipedrive')"
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
