import hashlib
from dataclasses import dataclass

from fastapi import HTTPException, status
from injector import inject, singleton
from sqlmodel import Session

from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher
from api.domains.onboarding.exceptions import TrialSignupCreditRequired
from api.domains.onboarding.models import TrialSettingsRead, TrialSettingsUpdate
from api.domains.onboarding.repository import TrialSettingsRepository
from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.platform_admin.service import PlatformAdminService

_GMAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})


@inject
@singleton
@dataclass
class TrialSettingsService:
    """The platform's trial settings. Its own service, depending on nothing but the
    repository, platform authority and Organization lookups, so sign-up can read the
    credit without pulling in the rest of onboarding."""

    repository: TrialSettingsRepository
    authority: PlatformAdminService
    dispatcher: EventDeliveryDispatcher
    organizations: OrganizationLookupService

    def signup_settings(self, session: Session) -> TrialSettingsRead:
        """Read signup policy and credit together, held stable through trial creation."""
        return self.repository.read_for_signup(session)

    def signup_policy(self) -> TrialSettingsRead:
        """Signup policy and trial credit as they stand, for a member creating an
        Organization rather than signing up."""
        return self.repository.read()

    def agent_limit(self) -> int:
        """How many Agents a Trial Organization may run."""
        return self.repository.read().agent_limit

    def trials_full(self, session: Session) -> bool:
        """Whether a new trial would exceed the cap on active trials. Takes a lock held
        until `session` commits, so call it in the transaction that creates the trial."""
        self.repository.lock_trial_admission(session)
        cap = self.repository.read().max_active_trials
        return cap is not None and self.organizations.count_trials() >= cap

    def read(self, context: CurrentUserContext) -> TrialSettingsRead:
        self.authority.require_platform_admin(context.user)
        return self._with_active_trials(self.repository.read())

    def update(self, data: TrialSettingsUpdate, context: CurrentUserContext) -> TrialSettingsRead:
        self.authority.require_platform_admin(context.user)
        try:
            result, delivery_ids = self.repository.set_settings(
                data.changes(),
                context.user.id,
                context.user.full_name or context.user.email,
            )
        except TrialSignupCreditRequired as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
        self.dispatcher.enqueue_immediate(delivery_ids)
        return self._with_active_trials(result)

    def _with_active_trials(self, settings: TrialSettingsRead) -> TrialSettingsRead:
        return settings.model_copy(update={"active_trials": self.organizations.count_trials()})

    @staticmethod
    def inbox(email: str) -> str:
        """The inbox an address delivers to, so its free variants count as one: a `+tag`
        is dropped on any address, and Gmail also ignores dots and answers to
        googlemail.com."""
        local, _, domain = email.strip().lower().rpartition("@")
        local = local.split("+", 1)[0]
        if domain in _GMAIL_DOMAINS:
            local, domain = local.replace(".", ""), "gmail.com"
        return f"{local}@{domain}"

    @classmethod
    def email_hash(cls, email: str) -> str:
        return hashlib.sha256(cls.inbox(email).encode()).hexdigest()

    @staticmethod
    def _legacy_email_hash(email: str) -> str:
        """How grants were keyed before addresses were normalised: lowercased only."""
        return hashlib.sha256(email.strip().lower().encode()).hexdigest()

    def has_had_trial(self, email: str, session: Session) -> bool:
        return self.repository.has_grant(self.email_hash(email), session) or self.repository.has_grant(
            self._legacy_email_hash(email), session
        )

    def record_trial(self, email: str, session: Session) -> None:
        self.repository.record_grant(self.email_hash(email), session)
