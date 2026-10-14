import hashlib
from dataclasses import dataclass

from injector import inject, singleton
from sqlmodel import Session

from api.core.config import Config
from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher
from api.domains.onboarding.models import TrialSettingsRead, TrialSettingsUpdate
from api.domains.onboarding.repository import TrialSettingsRepository
from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.platform_admin.service import PlatformAdminService


@inject
@singleton
@dataclass
class TrialSettingsService:
    """The platform's trial settings. Its own service, depending on nothing but the
    repository, platform authority and Organization lookups, so sign-up can read the
    credit without pulling in the rest of onboarding."""

    repository: TrialSettingsRepository
    authority: PlatformAdminService
    config: Config
    dispatcher: EventDeliveryDispatcher
    organizations: OrganizationLookupService

    def credit_usd(self) -> float:
        """The credit a new trial Organization starts with."""
        return self.repository.read(self.config.trial_default_credit_usd).credit_usd

    def agent_limit(self) -> int:
        """How many Agents a Trial Organization may run."""
        return self.repository.read(self.config.trial_default_credit_usd).agent_limit

    def trials_full(self, session: Session) -> bool:
        """Whether a new trial would exceed the cap on active trials. Takes a lock held
        until `session` commits, so call it in the transaction that creates the trial."""
        self.repository.lock_trial_admission(session)
        cap = self.repository.read(self.config.trial_default_credit_usd).max_active_trials
        return cap is not None and self.organizations.count_trials() >= cap

    def read(self, context: CurrentUserContext) -> TrialSettingsRead:
        self.authority.require_platform_admin(context.user)
        return self._with_active_trials(self.repository.read(self.config.trial_default_credit_usd))

    def update(self, data: TrialSettingsUpdate, context: CurrentUserContext) -> TrialSettingsRead:
        self.authority.require_platform_admin(context.user)
        result, delivery_ids = self.repository.set_settings(
            data.changes(),
            self.config.trial_default_credit_usd,
            context.user.id,
            context.user.full_name or context.user.email,
        )
        self.dispatcher.enqueue_immediate(delivery_ids)
        return self._with_active_trials(result)

    def _with_active_trials(self, settings: TrialSettingsRead) -> TrialSettingsRead:
        return settings.model_copy(update={"active_trials": self.organizations.count_trials()})

    @staticmethod
    def email_hash(email: str) -> str:
        return hashlib.sha256(email.strip().lower().encode()).hexdigest()

    def has_had_trial(self, email: str, session: Session) -> bool:
        return self.repository.has_grant(self.email_hash(email), session)

    def record_trial(self, email: str, session: Session) -> None:
        self.repository.record_grant(self.email_hash(email), session)
