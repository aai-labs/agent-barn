from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.events import ActorIdentity, ActorIdentityType, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import EVENT_REGISTRY, PLATFORM_TRIAL_SETTINGS_CHANGED
from api.domains.events.models import EventScope
from api.domains.events.repository import OutboxMessageRepository
from api.domains.onboarding.models import (
    TRIAL_SETTINGS_SUBJECT_DISPLAY,
    PlatformTrialSettings,
    TrialGrant,
    TrialSettingsRead,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

# Serializes trial settings changes, including creation of the singleton row.
_TRIAL_SETTINGS_LOCK = 732914106
# Serializes sign-ups' check against the cap on active trials.
_TRIAL_ADMISSION_LOCK = 732914107


@inject
@singleton
@dataclass
class TrialSettingsRepository:
    delegate: PostgresRepositoryDelegate
    outbox: OutboxMessageRepository

    def read(self, default_credit_usd: float) -> TrialSettingsRead:
        with Session(self.delegate.engine) as session:
            return self._current(session.get(PlatformTrialSettings, 1), default_credit_usd)

    @staticmethod
    def _current(row: PlatformTrialSettings | None, default_credit_usd: float) -> TrialSettingsRead:
        if row is None:
            return TrialSettingsRead(credit_usd=default_credit_usd)
        return TrialSettingsRead(
            credit_usd=row.credit_usd,
            agent_limit=row.agent_limit,
            max_active_trials=row.max_active_trials,
            updated_at=row.updated_at,
        )

    def lock_trial_admission(self, session: Session) -> None:
        """Held until the caller's transaction ends, so concurrent sign-ups count active
        trials one at a time and cannot overshoot the cap together."""
        session.connection().execute(sa.text(f"SELECT pg_advisory_xact_lock({_TRIAL_ADMISSION_LOCK})"))

    def set_settings(
        self,
        changes: Mapping[str, float | int | None],
        default_credit_usd: float,
        actor_id: UUID,
        actor_display: str,
    ) -> tuple[TrialSettingsRead, list[UUID]]:
        """Store the settings and stage one audit Event per setting that moved, in one
        commit. A setting saved at the value already in force writes nothing."""
        with Session(self.delegate.engine) as session:
            session.connection().execute(sa.text(f"SELECT pg_advisory_xact_lock({_TRIAL_SETTINGS_LOCK})"))
            row = session.get(PlatformTrialSettings, 1)
            current = self._current(row, default_credit_usd)
            moved = [
                (setting, getattr(current, setting), value)
                for setting, value in changes.items()
                if getattr(current, setting) != value
            ]
            if row and not moved:
                return current, []
            now = datetime.now(UTC)
            stored = current.model_copy(update={**dict(changes), "updated_at": now})
            session.merge(
                PlatformTrialSettings(
                    id=1,
                    credit_usd=stored.credit_usd,
                    agent_limit=stored.agent_limit,
                    max_active_trials=stored.max_active_trials,
                    updated_at=now,
                    updated_by=actor_id,
                )
            )
            correlation_id = uuid4()
            event_ids = []
            for setting, previous, value in moved:
                event = EVENT_REGISTRY.build_event(
                    event_name=PLATFORM_TRIAL_SETTINGS_CHANGED,
                    schema_version=1,
                    occurred_at=now,
                    event_scope=EventScope.PLATFORM,
                    organization_id=None,
                    actor=ActorIdentity(type=ActorIdentityType.USER, id=actor_id),
                    subject=SubjectIdentity(type=SubjectIdentityType.SYSTEM, id="platform-trial-settings"),
                    correlation_id=correlation_id,
                    payload={
                        "actor_user_id": actor_id,
                        "actor_display": actor_display,
                        "subject_display": TRIAL_SETTINGS_SUBJECT_DISPLAY,
                        "setting": setting,
                        "previous": None if previous is None else float(previous),
                        "current": None if value is None else float(value),
                    },
                )
                self.outbox.stage(session=session, registry=EVENT_REGISTRY, event=event)
                event_ids.append(event.event_id)
            ids = list(session.exec(select(EventDelivery.id).where(col(EventDelivery.event_id).in_(event_ids))))
            session.commit()
            return stored, ids

    def has_grant(self, email_hash: str, session: Session) -> bool:
        return session.get(TrialGrant, email_hash) is not None

    def record_grant(self, email_hash: str, session: Session) -> None:
        """Staged in the caller's transaction: the trial and its grant commit together."""
        session.add(TrialGrant(email_hash=email_hash, created_at=datetime.now(UTC)))
