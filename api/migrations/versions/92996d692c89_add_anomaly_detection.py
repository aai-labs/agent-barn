"""Add anomaly detection: the Organization opt-in, per-Agent overrides, the first-use
ledger, the check's read cursors and the Anomaly records

Revision ID: 92996d692c89
Revises: b7e2c41d9a63
Create Date: 2026-11-16

Organizations opt in (`organization_anomaly_settings.enabled`, no row means off). A
periodic check compares each Agent's activity with its own last fourteen days and
records what was unusual in `agent_anomaly`. `agent_activity_seen` keeps when each
tool, integration, action and destination host was first and last used, and
`agent_anomaly_state` how far the check has read. Every Agent-scoped table names the
Agent and its Organization together, so a row cannot pair an Agent with another
Organization.

The Organization Permissions `anomaly.read` and `anomaly.manage` let Owners and Admins
see Anomalies and change an Agent's normal.
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import SchemaItem

revision: str = "92996d692c89"
down_revision: str | Sequence[str] | None = "b7e2c41d9a63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen here rather than imported: a migration must keep meaning what it meant when
# it shipped, whatever the catalogue in code says later.
_PERMISSIONS = (
    (UUID("6508f7e2-8def-5582-92bd-88cde6051e36"), "anomaly.read"),
    (UUID("3daa360b-a401-5882-9d4b-f6230ed2b217"), "anomaly.manage"),
)
_SENSITIVITIES = ("LOW", "NORMAL", "HIGH")
_SEEN_KINDS = ("TOOL", "INTEGRATION", "INTEGRATION_ACTION", "DESTINATION")
_SIGNALS = (
    "LLM_TOKENS_PER_HOUR",
    "LLM_CALLS_PER_HOUR",
    "TOOL_CALLS_PER_HOUR",
    "TOOL_ERROR_RATE",
    "WRITES_PER_HOUR",
    "LLM_TOKENS_CAP",
    "LLM_CALLS_CAP",
    "NEW_TOOL",
    "NEW_INTEGRATION",
    "NEW_INTEGRATION_ACTION",
    "NEW_DESTINATION",
)
_CLASSIFICATION_STATES = ("STATISTICS_ONLY", "CLASSIFIED")


def _check_in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organization.id", ondelete="CASCADE"),
            nullable=False,
        ),
    ]


def _agent_columns(table: str) -> list[SchemaItem]:
    return [
        *_base_columns(),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name=f"fk_{table}_agent_organization",
            ondelete="CASCADE",
        ),
    ]


def _with_catalogue_unlocked(statement: sa.TextClause, **params: object) -> None:
    """The Permission catalogue is immutable by trigger; a migration is the one place
    allowed to change it, and it locks it again in the same transaction."""
    op.execute("ALTER TABLE permissions DISABLE TRIGGER trg_permission_catalogue_immutability")
    op.get_bind().execute(statement, params)
    op.execute("ALTER TABLE permissions ENABLE TRIGGER trg_permission_catalogue_immutability")


def upgrade() -> None:
    op.create_table(
        "organization_anomaly_settings",
        *_base_columns(),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("organization_id", name="uq_organization_anomaly_settings_organization_id"),
    )
    op.create_table(
        "agent_anomaly_override",
        *_agent_columns("agent_anomaly_override"),
        sa.Column("sensitivity", sa.String(length=16), nullable=False),
        sa.Column("max_llm_tokens_per_hour", sa.Integer(), nullable=True),
        sa.Column("max_llm_calls_per_hour", sa.Integer(), nullable=True),
        sa.UniqueConstraint("agent_id", name="uq_agent_anomaly_override_agent_id"),
        sa.CheckConstraint(_check_in("sensitivity", _SENSITIVITIES), name="check_agent_anomaly_override_sensitivity"),
        sa.CheckConstraint(
            "max_llm_tokens_per_hour IS NULL OR max_llm_tokens_per_hour > 0",
            name="check_agent_anomaly_override_tokens_cap_positive",
        ),
        sa.CheckConstraint(
            "max_llm_calls_per_hour IS NULL OR max_llm_calls_per_hour > 0",
            name="check_agent_anomaly_override_calls_cap_positive",
        ),
    )
    op.create_table(
        "agent_activity_seen",
        *_agent_columns("agent_activity_seen"),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("agent_id", "kind", "subject", name="uq_agent_activity_seen_agent_kind_subject"),
        sa.CheckConstraint(_check_in("kind", _SEEN_KINDS), name="check_agent_activity_seen_kind"),
    )
    op.create_table(
        "agent_anomaly_state",
        *_agent_columns("agent_anomaly_state"),
        sa.Column("tool_calls_read_through", sa.DateTime(timezone=True), nullable=True),
        sa.Column("business_actions_read_through", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("agent_id", name="uq_agent_anomaly_state_agent_id"),
    )
    op.create_table(
        "agent_anomaly",
        *_agent_columns("agent_anomaly"),
        sa.Column("signal", sa.String(length=40), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("observed_value", sa.Float(), nullable=False),
        sa.Column("usual_value", sa.Float(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("classification_state", sa.String(length=32), nullable=False),
        sa.Column("classification_category", sa.Text(), nullable=True),
        sa.Column("classification_severity", sa.Float(), nullable=True),
        sa.Column("classification", JSONB(), nullable=True),
        sa.CheckConstraint(_check_in("signal", _SIGNALS), name="check_agent_anomaly_signal"),
        sa.CheckConstraint(
            _check_in("classification_state", _CLASSIFICATION_STATES),
            name="check_agent_anomaly_classification_state",
        ),
    )
    op.create_index(
        "uq_agent_anomaly_ongoing",
        "agent_anomaly",
        ["agent_id", "signal", sa.text("coalesce(subject, '')")],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_index("ix_agent_anomaly_agent_started", "agent_anomaly", ["agent_id", "started_at"])

    for permission_id, key in _PERMISSIONS:
        _with_catalogue_unlocked(
            sa.text(
                "INSERT INTO permissions (id, created_at, updated_at, key) "
                "VALUES (:id, now(), now(), :key) ON CONFLICT DO NOTHING"
            ),
            id=permission_id,
            key=key,
        )


def downgrade() -> None:
    for permission_id, _key in reversed(_PERMISSIONS):
        _with_catalogue_unlocked(sa.text("DELETE FROM permissions WHERE id = :id"), id=permission_id)
    op.drop_index("ix_agent_anomaly_agent_started", table_name="agent_anomaly")
    op.drop_index("uq_agent_anomaly_ongoing", table_name="agent_anomaly")
    for table in (
        "agent_anomaly",
        "agent_anomaly_state",
        "agent_activity_seen",
        "agent_anomaly_override",
        "organization_anomaly_settings",
    ):
        op.drop_table(table)
