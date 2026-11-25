from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field as SqlField

from api.domains.anomalies.detection import RateSignal, Sensitivity
from api.infrastructure.postgres.models import BaseModel


class AnomalySignal(StrEnum):
    LLM_TOKENS_PER_HOUR = RateSignal.LLM_TOKENS_PER_HOUR.value
    LLM_CALLS_PER_HOUR = RateSignal.LLM_CALLS_PER_HOUR.value
    TOOL_CALLS_PER_HOUR = RateSignal.TOOL_CALLS_PER_HOUR.value
    TOOL_ERROR_RATE = RateSignal.TOOL_ERROR_RATE.value
    LLM_ERROR_RATE = RateSignal.LLM_ERROR_RATE.value
    WRITES_PER_HOUR = RateSignal.WRITES_PER_HOUR.value
    # Over an Owner- or Admin-set hard cap, whatever the baseline says.
    LLM_TOKENS_CAP = "LLM_TOKENS_CAP"
    LLM_CALLS_CAP = "LLM_CALLS_CAP"
    # Not seen in the Agent's baseline window.
    NEW_TOOL = "NEW_TOOL"
    NEW_INTEGRATION = "NEW_INTEGRATION"
    NEW_INTEGRATION_ACTION = "NEW_INTEGRATION_ACTION"
    NEW_DESTINATION = "NEW_DESTINATION"


class SeenKind(StrEnum):
    """What an Agent's first-use ledger records."""

    TOOL = "TOOL"
    INTEGRATION = "INTEGRATION"
    # `<integration> <verb>`, e.g. "crm delete" next to "crm read".
    INTEGRATION_ACTION = "INTEGRATION_ACTION"
    # A host, never a full URL: arguments can carry customer data.
    DESTINATION = "DESTINATION"


NEW_SIGNAL_BY_KIND: dict[SeenKind, AnomalySignal] = {
    SeenKind.TOOL: AnomalySignal.NEW_TOOL,
    SeenKind.INTEGRATION: AnomalySignal.NEW_INTEGRATION,
    SeenKind.INTEGRATION_ACTION: AnomalySignal.NEW_INTEGRATION_ACTION,
    SeenKind.DESTINATION: AnomalySignal.NEW_DESTINATION,
}


class ClassificationState(StrEnum):
    """Whether a decision model has judged the Anomaly yet.

    A new Anomaly starts STATISTICS_ONLY. The check then asks the decision model about it
    once; an answer fills in the classification columns and moves it to CLASSIFIED, a
    failure leaves it as it is.
    """

    STATISTICS_ONLY = "STATISTICS_ONLY"
    CLASSIFIED = "CLASSIFIED"


def _agent_in_organization(table: str) -> sa.ForeignKeyConstraint:
    """The Agent must belong to the row's Organization."""
    return sa.ForeignKeyConstraint(
        ["agent_id", "organization_id"],
        ["agent.id", "agent.organization_id"],
        name=f"fk_{table}_agent_organization",
        ondelete="CASCADE",
    )


def _check_in(column: str, values: type[StrEnum]) -> str:
    allowed = ", ".join(f"'{value.value}'" for value in values)
    return f"{column} IN ({allowed})"


class OrganizationAnomalySettings(BaseModel, table=True):
    """Whether an Organization has turned anomaly detection on. No row means off."""

    __tablename__: str = "organization_anomaly_settings"
    __table_args__ = (sa.UniqueConstraint("organization_id", name="uq_organization_anomaly_settings_organization_id"),)

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    enabled: bool = SqlField(default=False, nullable=False)


class AgentAnomalyOverride(BaseModel, table=True):
    """An Owner's or Admin's adjustments to one Agent's learned normal. No row means
    normal sensitivity and no hard caps."""

    __tablename__: str = "agent_anomaly_override"
    __table_args__ = (
        _agent_in_organization("agent_anomaly_override"),
        sa.UniqueConstraint("agent_id", name="uq_agent_anomaly_override_agent_id"),
        sa.CheckConstraint(_check_in("sensitivity", Sensitivity), name="check_agent_anomaly_override_sensitivity"),
        sa.CheckConstraint(
            "max_llm_tokens_per_hour IS NULL OR max_llm_tokens_per_hour > 0",
            name="check_agent_anomaly_override_tokens_cap_positive",
        ),
        sa.CheckConstraint(
            "max_llm_calls_per_hour IS NULL OR max_llm_calls_per_hour > 0",
            name="check_agent_anomaly_override_calls_cap_positive",
        ),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    agent_id: UUID = SqlField(nullable=False)
    sensitivity: str = SqlField(default=Sensitivity.NORMAL.value, nullable=False, max_length=16)
    max_llm_tokens_per_hour: int | None = SqlField(default=None, nullable=True)
    max_llm_calls_per_hour: int | None = SqlField(default=None, nullable=True)


class AgentActivitySeen(BaseModel, table=True):
    """When an Agent first and last used a tool, integration, action or destination.

    Kept up to date a little at a time by the check, so first use is a lookup rather
    than a re-read of fourteen days of tool calls.
    """

    __tablename__: str = "agent_activity_seen"
    __table_args__ = (
        _agent_in_organization("agent_activity_seen"),
        sa.UniqueConstraint("agent_id", "kind", "subject", name="uq_agent_activity_seen_agent_kind_subject"),
        sa.CheckConstraint(_check_in("kind", SeenKind), name="check_agent_activity_seen_kind"),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    agent_id: UUID = SqlField(nullable=False)
    kind: str = SqlField(nullable=False, max_length=32)
    subject: str = SqlField(nullable=False, sa_type=sa.Text)
    first_seen_at: datetime = SqlField(sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False))
    last_seen_at: datetime = SqlField(sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False))


class AgentAnomalyState(BaseModel, table=True):
    """How far the check has read an Agent's tool calls and Business Actions.

    The cursors follow insertion time (`created_at`), not `occurred_at`, so rows that
    arrive late are still read once. No row means the Agent has not been read yet: the
    next check fills its ledger from its baseline window without flagging anything.
    """

    __tablename__: str = "agent_anomaly_state"
    __table_args__ = (
        _agent_in_organization("agent_anomaly_state"),
        sa.UniqueConstraint("agent_id", name="uq_agent_anomaly_state_agent_id"),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    agent_id: UUID = SqlField(nullable=False)
    tool_calls_read_through: datetime | None = SqlField(
        default=None, sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True)
    )
    business_actions_read_through: datetime | None = SqlField(
        default=None, sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True)
    )


class AgentAnomaly(BaseModel, table=True):
    """Something an Agent did that was unusual for it.

    A rate or cap Anomaly stays one row while the deviation lasts (`ended_at` NULL)
    and ends once a check no longer sees it. A first-use Anomaly is a single moment, so
    it starts and ends together.
    """

    __tablename__: str = "agent_anomaly"
    __table_args__ = (
        _agent_in_organization("agent_anomaly"),
        sa.CheckConstraint(_check_in("signal", AnomalySignal), name="check_agent_anomaly_signal"),
        sa.CheckConstraint(
            _check_in("classification_state", ClassificationState), name="check_agent_anomaly_classification_state"
        ),
        # At most one ongoing Anomaly per Agent, signal and subject.
        sa.Index(
            "uq_agent_anomaly_ongoing",
            "agent_id",
            "signal",
            sa.text("coalesce(subject, '')"),
            unique=True,
            postgresql_where=sa.text("ended_at IS NULL"),
        ),
        sa.Index("ix_agent_anomaly_agent_started", "agent_id", "started_at"),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    agent_id: UUID = SqlField(nullable=False)
    signal: str = SqlField(nullable=False, max_length=40)
    # The tool, integration, action or host for first-use signals; NULL for rates.
    subject: str | None = SqlField(default=None, nullable=True, sa_type=sa.Text)
    observed_value: float = SqlField(nullable=False)
    usual_value: float | None = SqlField(default=None, nullable=True)
    threshold: float | None = SqlField(default=None, nullable=True)
    started_at: datetime = SqlField(sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False))
    last_observed_at: datetime = SqlField(sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False))
    ended_at: datetime | None = SqlField(default=None, sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True))
    classification_state: str = SqlField(
        default=ClassificationState.STATISTICS_ONLY.value, nullable=False, max_length=32
    )
    classification_category: str | None = SqlField(default=None, nullable=True, sa_type=sa.Text)
    classification_severity: float | None = SqlField(default=None, nullable=True)
    # The model's full answer (probabilities and the like), kept as it came.
    classification: dict[str, Any] | None = SqlField(default=None, sa_column=sa.Column(JSONB, nullable=True))


class AnomalyDetectionSettingsRead(PydanticBaseModel):
    enabled: bool
    can_manage: bool
    updated_at: datetime | None


class AnomalyDetectionSettingsUpdate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class AnomalyClassificationRead(PydanticBaseModel):
    """What the decision model made of an Anomaly."""

    category: str
    # LOW, MEDIUM, HIGH or CRITICAL.
    severity: str
    # How likely the activity is really unusual for the Agent, rather than noise.
    unusual_probability: float | None


class AgentAnomalyRead(PydanticBaseModel):
    id: UUID
    signal: AnomalySignal
    subject: str | None
    observed_value: float
    usual_value: float | None
    threshold: float | None
    started_at: datetime
    last_observed_at: datetime
    ended_at: datetime | None
    classification_state: ClassificationState
    # None until the Anomaly is classified.
    classification: AnomalyClassificationRead | None


class AgentAnomalyOverrideRead(PydanticBaseModel):
    sensitivity: Sensitivity
    max_llm_tokens_per_hour: int | None
    max_llm_calls_per_hour: int | None


# The cap columns are 32-bit integers.
MAX_HOURLY_CAP = 2**31 - 1


class AgentAnomalyOverrideUpdate(PydanticBaseModel):
    """A full replacement: omitted caps are cleared."""

    model_config = ConfigDict(extra="forbid")

    sensitivity: Sensitivity = Sensitivity.NORMAL
    max_llm_tokens_per_hour: int | None = Field(default=None, gt=0, le=MAX_HOURLY_CAP)
    max_llm_calls_per_hour: int | None = Field(default=None, gt=0, le=MAX_HOURLY_CAP)


class RateBaselineRead(PydanticBaseModel):
    signal: RateSignal
    usual: float
    # What a check would flag above, at the Agent's current sensitivity.
    threshold: float
    active_hours: int


class AgentNormalBehaviourRead(PydanticBaseModel):
    detection_enabled: bool
    # Nothing is flagged until the Agent has been active on enough days.
    enough_history: bool
    active_days: int
    rates: list[RateBaselineRead] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    integrations: list[str] = Field(default_factory=list)
    integration_actions: list[str] = Field(default_factory=list)
    destinations: list[str] = Field(default_factory=list)
    override: AgentAnomalyOverrideRead
    can_manage: bool


class AnomalyAlertEmailReceipt(BaseModel, table=True):
    """Idempotency record: a recipient was already emailed for an alert's Event Delivery.

    Same shape and reasoning as the Agent lifecycle receipt: one delivery fans out to
    several recipients, and a retry must only email the ones that were not reached.
    """

    __tablename__: str = "anomaly_alert_email_receipt"
    __table_args__ = (
        sa.UniqueConstraint("delivery_id", "recipient_email", name="uq_anomaly_alert_email_receipt_delivery_recipient"),
    )

    delivery_id: UUID = SqlField(foreign_key="event_delivery.id", nullable=False, ondelete="CASCADE", index=True)
    recipient_email: str = SqlField(nullable=False, max_length=320)
