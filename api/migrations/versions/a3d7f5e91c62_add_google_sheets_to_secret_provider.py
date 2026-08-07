"""Add google_sheets to agent_secret provider check constraint.

Descends from both current heads, so it doubles as the merge revision staging needs.

5e0adff0f5e2 (#109) and f6a7b8c9d0e1 (#110) merged within an hour of each other, each
adding migrations on its own line and neither reconciling the other, which leaves staging
with two heads and `alembic upgrade head` refusing to run. Taking both as parents repairs
that rather than adding a third head.

Only 5e0adff0f5e2 touches ck_agent_secret_provider, so the _OLD snapshot below still
matches what is on the table — every revision touching this constraint recreates it from
its own snapshot, which is exactly the collision 5e0adff0f5e2 had to repair between slack
and pipedrive.

Revision ID: a3d7f5e91c62
Revises: (5e0adff0f5e2, f6a7b8c9d0e1)
"""

from alembic import op

revision: str = "a3d7f5e91c62"
down_revision: tuple[str, str] = ("5e0adff0f5e2", "f6a7b8c9d0e1")
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
