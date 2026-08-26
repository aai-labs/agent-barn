"""Remove the per-service Google providers (gmail, google_calendar, google_sheets).

Superseded by google_workspace, where one gog credential covers Gmail, Calendar, Drive
and Sheets under a single consent. The code for these providers is gone — no enum
member, content model, aai-cli profile, skill, validator, OAuth scope set, or UI entry —
so their rows are unreadable (``SecretProvider('gmail')`` now raises) as well as unusable.
This deletes them.

Two classes of row have to go, in this order:

* ``agent_secret`` / ``shared_credential`` rows naming a removed provider. These are the
  credentials themselves. They are deliberately *not* converted to google_workspace: the
  account email gog keys tokens by was never captured (the granted scopes never included
  ``openid email``), and the calendar credential only ever held a ~1h access token with
  no refresh token. Affected agents must reconnect through Google Workspace.
* ``skill`` rows whose ``required_providers`` name a removed provider (the seeded Gmail
  and Google Sheets aai-cli skills). ``Skill.required_providers`` is typed
  ``list[SecretProvider]``, so leaving these would break skill loading outright, not just
  leave dead data. ``agent_skill`` cascades; the template/override link tables are
  RESTRICT, so their rows are cleared first.

The check constraint is recreated last, from the snapshot b7e2c4d81f39 left on the table
(0e48aaf59368 is a no-op merge and does not touch it), minus the three values. Deleting
before tightening matters: the constraint would otherwise fail against the very rows it
is meant to outlaw.

Downgrade restores the old constraint but **cannot restore the deleted rows** — the
credentials are gone and must be reconnected.

Revision ID: c9f1b30a7d42
Revises: 0e48aaf59368
"""

from alembic import op

revision: str = "c9f1b30a7d42"
down_revision: str = "0e48aaf59368"
branch_labels: str | None = None
depends_on: str | None = None

_RETIRED = ("gmail", "google_calendar", "google_sheets")
_RETIRED_SQL = ", ".join(f"'{provider}'" for provider in _RETIRED)

# Snapshot as left by b7e2c4d81f39 (the last revision to recreate this constraint).
_OLD = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'gmail', 'google_calendar', 'google_sheets', 'zoho_mail', 'zoho_calendar', "
    "'firecrawl', 'slack', 'pipedrive', 'google_workspace')"
)
_NEW = (
    "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
    "'zoho_mail', 'zoho_calendar', "
    "'firecrawl', 'slack', 'pipedrive', 'google_workspace')"
)

# Link tables that reference skill.id with ON DELETE RESTRICT; cleared before the skills
# themselves. agent_skill is ON DELETE CASCADE and needs no explicit statement.
_RESTRICTING_SKILL_LINK_TABLES = (
    "agent_template_skill",
    "platform_template_skill",
    "platform_template_draft_skill",
    "agent_template_override_draft_skill",
    "agent_template_override_version_skill",
)

_RETIRED_SKILL_IDS = f"""
    SELECT id FROM skill
    WHERE EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(required_providers::jsonb) AS provider
        WHERE provider IN ({_RETIRED_SQL})
    )
"""


def upgrade() -> None:
    op.execute(f"DELETE FROM agent_secret WHERE provider IN ({_RETIRED_SQL})")
    op.execute(f"DELETE FROM shared_credential WHERE provider IN ({_RETIRED_SQL})")

    for table in _RESTRICTING_SKILL_LINK_TABLES:
        op.execute(f"DELETE FROM {table} WHERE skill_id IN ({_RETIRED_SKILL_IDS})")
    op.execute(f"DELETE FROM skill WHERE id IN ({_RETIRED_SKILL_IDS})")

    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _NEW)


def downgrade() -> None:
    # Restores the constraint only. The deleted credentials and skills are unrecoverable.
    op.drop_constraint("ck_agent_secret_provider", "agent_secret", type_="check")
    op.create_check_constraint("ck_agent_secret_provider", "agent_secret", _OLD)
