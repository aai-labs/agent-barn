"""remove zoho tool integration providers

Revision ID: a85f48650d6a
Revises: 59bd5956b22a
Create Date: 2026-09-03

Zoho Mail and Zoho Calendar are removed as tool Integrations. Zoho Calendar was never
functional — its CalDAV verbs (PROPFIND, REPORT) were never carried by any transport we
shipped, and it was already disabled in the UI. Zoho Mail is removed alongside it.

Any ``agent_secret`` or ``shared_credential`` row still carrying these providers would
raise ``ValueError`` when agent start coerces the stored string back to
``SecretProvider``, so the rows are removed rather than left to break a start.
"""

import sqlalchemy as sa
from alembic import op

revision = "a85f48650d6a"
down_revision = "59bd5956b22a"
branch_labels = None
depends_on = None

_PROVIDERS = ("zoho_mail", "zoho_calendar")


def upgrade() -> None:
    # agent_secret rows may point at a shared_credential (content NULL) rather than hold
    # their own ciphertext, so clear the dependants before the credentials they restrict.
    op.execute(
        sa.text("DELETE FROM agent_secret WHERE provider IN :providers").bindparams(
            sa.bindparam("providers", value=_PROVIDERS, expanding=True)
        )
    )
    op.execute(
        sa.text("DELETE FROM shared_credential WHERE provider IN :providers").bindparams(
            sa.bindparam("providers", value=_PROVIDERS, expanding=True)
        )
    )


def downgrade() -> None:
    # The deleted credentials are unrecoverable; re-adding the enum members is a code
    # change, not a data one.
    pass
