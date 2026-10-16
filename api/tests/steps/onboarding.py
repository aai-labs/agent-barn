"""Persisted platform signup policy for onboarding scenarios."""

from datetime import UTC, datetime

from sqlmodel import Session

from api.domains.onboarding.models import PlatformTrialSettings
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


def trial_settings_are_configured(*, enabled: bool = True, credit: float = 10):
    def step(context):
        delegate = context.injector.get(PostgresRepositoryDelegate)
        with Session(delegate.engine) as session:
            session.add(
                PlatformTrialSettings(self_signup_enabled=enabled, credit_usd=credit, updated_at=datetime.now(UTC))
            )
            session.commit()

    return step
