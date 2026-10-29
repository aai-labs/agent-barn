"""Cancel stranded native chat gateway work without replay or schema contraction.

Revision ID: 72c4a9e1b6d8
Revises: 45bcefcb0749
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "72c4a9e1b6d8"
down_revision: str | Sequence[str] | None = "45bcefcb0749"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RETIRE_BATCH = sa.text("""
    WITH candidates AS (
        SELECT d.id
        FROM communication_delivery d
        JOIN communication_connection c ON c.id = d.connection_id
        WHERE c.platform_key IN ('slack', 'discord', 'telegram', 'teams')
          AND d.status IN ('PENDING', 'PROCESSING')
        ORDER BY d.id
        LIMIT 1000
        FOR UPDATE OF d
    ), retired AS (
        UPDATE communication_delivery d
        SET status = 'CANCELLED',
            completed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP,
            cancel_requested_at = COALESCE(d.cancel_requested_at, CURRENT_TIMESTAMP),
            claimed_at = NULL,
            lease_expires_at = NULL,
            awaiting_input = false,
            last_error_code = 'NATIVE_GATEWAY_RETIRED',
            last_error_message = 'Native chat gateway work was retired without replay.'
        FROM candidates
        WHERE d.id = candidates.id
        RETURNING d.id, d.organization_id, d.agent_id, d.connection_id, d.attempt_count
    )
    INSERT INTO communication_operation_journal
        (id, created_at, updated_at, organization_id, agent_id, connection_id,
         delivery_id, occurred_at, stage, attempt_number, error_code, error_summary)
    SELECT gen_random_uuid(), CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
           organization_id, agent_id, connection_id, id, CURRENT_TIMESTAMP,
           'policy_rejected', attempt_count, 'NATIVE_GATEWAY_RETIRED',
           'Native chat gateway work was retired without replay.'
    FROM retired
    RETURNING id
""")


def upgrade() -> None:
    # Use only existing status/stage values so readers predating this data
    # revision can still load the history during the pre-rollout migration hook.
    bind = op.get_bind()
    while bind.execute(_RETIRE_BATCH).first() is not None:
        pass


def downgrade() -> None:
    # Cancellation is intentional and irreversible: a schema downgrade must
    # never requeue retired provider work or erase the retirement history.
    pass
