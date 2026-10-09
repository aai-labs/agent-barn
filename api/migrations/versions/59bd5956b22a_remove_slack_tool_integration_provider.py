"""remove slack tool integration provider

Revision ID: 59bd5956b22a
Revises: c50f6d65b1b7
Create Date: 2026-09-02

Slack reaches agents as a Communication Platform Plugin, not as a tool Integration, so
``SecretProvider.SLACK`` no longer exists. Any ``agent_secret`` row still carrying
``provider = 'slack'`` would raise ``ValueError`` when agent start coerces the stored
string back to the enum, so the rows are removed rather than left to break a start.

This deletes credential material. It is the intended outcome: the Slack tool Integration
has no runtime that could use these tokens, and the equivalent credential for Slack now
lives on a Communication Connection, which this migration does not touch.
"""

import sqlalchemy as sa
from alembic import op

revision = "59bd5956b22a"
down_revision = "c50f6d65b1b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM agent_secret WHERE provider = 'slack'"))
    # Slack was never shared-credential eligible, so shared_credential needs no sweep.
    # Defensive anyway: an imported or hand-edited row would break the same way.
    op.execute(sa.text("DELETE FROM shared_credential WHERE provider = 'slack'"))


def downgrade() -> None:
    # The deleted credentials are unrecoverable; re-adding the enum member is a code
    # change, not a data one.
    pass
