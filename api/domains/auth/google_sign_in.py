"""Signing in with Google, and self-signup through it (AF-368).

The browser is sent to Google with a signed ``state`` and comes back to the callback,
which redeems the code, finds or creates the account, and starts a session the same way
password login does (a refresh-token cookie the web app trades for an access token).

The ``state`` carries a nonce that is also set as a cookie on the browser that started,
and the callback requires both to match. Without that binding, anyone could sign a
victim in to the attacker's account by handing them a callback link (login CSRF). The
cookie is single-use, so a callback cannot be replayed either.

A first sign-in creates the User, their trial Organization and their Owner Membership
in one transaction. Google has verified the address, so the account starts verified.
"""

import logging
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid7

import jwt
from injector import inject, singleton
from jwt.exceptions import InvalidTokenError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from api.core.config import Config
from api.domains.agent_settings.models import OrganizationAgentSettings
from api.domains.auth.hashing import hash_text
from api.domains.auth.models import CredentialClass, TokenData
from api.domains.auth.repository import PasswordResetTokenRepository
from api.domains.auth.service import JWT_ENCODING_ALGORITHM, AuthService
from api.domains.onboarding.settings_service import TrialSettingsService
from api.domains.organizations.llm_budget_service import OrganizationLlmBudgetService
from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.exceptions import EmailTakenHTTPException
from api.domains.users.models import User
from api.domains.users.organization_users.models import OrganizationRole, OrganizationUser
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.domains.users.repository import UserRepository
from api.infrastructure.google.identity import (
    GoogleIdentity,
    GoogleIdentityClient,
    GoogleIdentityError,
    GoogleIdentityUnavailable,
)
from api.infrastructure.litellm.client import ONE_OFF_BUDGET_WINDOW

logger = logging.getLogger(__name__)

STATE_TTL_SECONDS = 600
_STATE_TYPE = "google_sign_in_state"
# The pages a sign-in can start from, and so return to on failure.
SIGN_IN_ORIGINS = ("signup", "login")


class SignInError(StrEnum):
    """Why a sign-in ended without a session. The web app turns each into its message."""

    CANCELLED = "cancelled"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    UNVERIFIED = "unverified"
    SIGNUP_CLOSED = "signup_closed"
    TRIAL_USED = "trial_used"


@dataclass(frozen=True)
class SignInStart:
    redirect_url: str
    # Set as a cookie on the browser, and matched against the state on the way back.
    nonce: str | None


@dataclass(frozen=True)
class SignInOutcome:
    redirect_url: str
    # Present only when the sign-in succeeded.
    refresh_token: str | None = None


class _SignInRefused(Exception):
    def __init__(self, error: SignInError):
        super().__init__(error.value)
        self.error = error


@inject
@singleton
@dataclass
class GoogleSignInService:
    config: Config
    google: GoogleIdentityClient
    auth_service: AuthService
    user_repository: UserRepository
    organization_repository: OrganizationRepository
    organization_user_repository: OrganizationUserRepository
    invite_tokens: PasswordResetTokenRepository
    trial_settings: TrialSettingsService
    llm_budgets: OrganizationLlmBudgetService

    def redirect_uri(self) -> str:
        # Must be registered on the Google client, and identical in the authorize request
        # and the code exchange.
        return f"{self.config.web_app_url}/api/v1/auth/google/callback"

    def _page(self, origin: str, error: SignInError | None = None) -> str:
        page = origin if origin in SIGN_IN_ORIGINS else "signup"
        url = f"{self.config.web_app_url}/{page}"
        return f"{url}?error={error.value}" if error else url

    def start(self, origin: str) -> SignInStart:
        if not self.google.configured:
            return SignInStart(redirect_url=self._page(origin, SignInError.UNAVAILABLE), nonce=None)
        nonce = secrets.token_urlsafe(32)
        state = jwt.encode(
            {
                "typ": _STATE_TYPE,
                "nonce": nonce,
                "origin": origin if origin in SIGN_IN_ORIGINS else "signup",
                "exp": int(time.time()) + STATE_TTL_SECONDS,
            },
            self.config.secret_signing_key,
            algorithm=JWT_ENCODING_ALGORITHM,
        )
        return SignInStart(
            redirect_url=self.google.authorize_url(redirect_uri=self.redirect_uri(), state=state), nonce=nonce
        )

    def _origin_from_state(self, state: str | None, nonce: str | None) -> str | None:
        """The page the sign-in started from, or None unless the state is ours, unexpired,
        and was started by this browser."""
        if not state or not nonce:
            return None
        try:
            claims = jwt.decode(state, self.config.secret_signing_key, algorithms=[JWT_ENCODING_ALGORITHM])
        except InvalidTokenError:
            return None
        if claims.get("typ") != _STATE_TYPE or not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            return None
        return claims.get("origin") if claims.get("origin") in SIGN_IN_ORIGINS else "signup"

    def complete(self, *, code: str | None, state: str | None, error: str | None, nonce: str | None) -> SignInOutcome:
        origin = self._origin_from_state(state, nonce)
        if origin is None:
            return SignInOutcome(redirect_url=self._page("signup", SignInError.FAILED))
        if error:
            # Google reports a cancelled consent screen as access_denied; anything else
            # it sends back here is a failure on its side.
            refused = SignInError.CANCELLED if error == "access_denied" else SignInError.FAILED
            return SignInOutcome(redirect_url=self._page(origin, refused))
        if not code:
            return SignInOutcome(redirect_url=self._page(origin, SignInError.FAILED))
        try:
            identity = self.google.exchange_code(code=code, redirect_uri=self.redirect_uri())
            user = self._sign_in(identity)
        except GoogleIdentityUnavailable:
            logger.warning("Google sign-in could not reach Google")
            return SignInOutcome(redirect_url=self._page(origin, SignInError.UNAVAILABLE))
        except GoogleIdentityError as exc:
            logger.warning("Google sign-in refused: %s", exc)
            return SignInOutcome(redirect_url=self._page(origin, SignInError.FAILED))
        except _SignInRefused as refused:
            return SignInOutcome(redirect_url=self._page(origin, refused.error))
        refresh_token = self.auth_service.create_refresh_token(
            TokenData(user_id=str(user.id), stamp=user.security_stamp, credential_class=CredentialClass.USER_SESSION)
        )
        # The web app trades the refresh cookie for an access token on its first request.
        onboarding = user.signed_up_at is not None and user.onboarding_completed_at is None
        landing = "onboarding" if onboarding else "dashboard"
        return SignInOutcome(redirect_url=f"{self.config.web_app_url}/{landing}", refresh_token=refresh_token)

    def _sign_in(self, identity: GoogleIdentity) -> User:
        # An unverified address proves nothing about who owns it, so it neither creates an
        # account nor signs in to one with that address.
        if not identity.email_verified:
            raise _SignInRefused(SignInError.UNVERIFIED)
        try:
            return self._find_or_create(identity)
        except EmailTakenHTTPException, IntegrityError:
            # A concurrent first sign-in with the same Google account or address committed
            # between our lookup and our insert; that is the account, so sign in to it.
            return self._find_or_create(identity)

    def _find_or_create(self, identity: GoogleIdentity) -> User:
        with Session(self.user_repository.delegate.engine, expire_on_commit=False) as session:
            user = self.user_repository.get_by_google_sub_for_update(identity.sub, session)
            if user is not None:
                return user
            user = self.user_repository.get_by_email_ignoring_case_for_update(identity.email, session)
            if user is not None:
                return self._link(user, identity, session)
            if not self.config.self_signup_enabled:
                raise _SignInRefused(SignInError.SIGNUP_CLOSED)
            user, organization = self._sign_up(identity, session)
        # With its limit already on it. Best effort: the Organization is committed, and
        # the first Agent key provisions the team again if this fails.
        self.llm_budgets.provision_team(organization.id)
        return user

    def _link(self, user: User, identity: GoogleIdentity, session: Session) -> User:
        """An account that already has this address. Google has verified it, which proves
        as much as following an invitation link would, so a pending invitee is enrolled
        and their invitation retired."""
        enrolling = user.email_verified_at is None
        user.google_sub = identity.sub
        if enrolling:
            user.email_verified_at = datetime.now(UTC)
            if not user.full_name and identity.name:
                user.full_name = identity.name
        session.add(user)
        session.commit()
        if enrolling:
            self.invite_tokens.invalidate_unused_for_user(user.id)
        return user

    def _sign_up(self, identity: GoogleIdentity, session: Session) -> tuple[User, Organization]:
        # One trial per address, even after its account is deleted.
        if self.trial_settings.has_had_trial(identity.email, session):
            raise _SignInRefused(SignInError.TRIAL_USED)
        now = datetime.now(UTC)
        user = User(
            email=identity.email,
            full_name=identity.name,
            # Unusable-but-valid hash: this account signs in with Google. "Forgot
            # password" can still give it a password later.
            hashed_password=hash_text(uuid7().hex),
            google_sub=identity.sub,
            email_verified_at=now,
            signed_up_at=now,
        )
        self.user_repository.save_with_session(user, session)
        credit = self.trial_settings.credit_usd()
        organization = Organization(
            name=AuthService._default_organization_name(identity.name),
            created_by_user_id=user.id,
            allowed_models=[self.config.agent_default_model.removeprefix("litellm/openrouter/")],
            is_trial=True,
            llm_budget_usd=credit,
            llm_budget_duration=ONE_OFF_BUDGET_WINDOW,
        )
        self.organization_repository.save_with_session(organization, session)
        # The deployment's default Agent limit may be below the credit; the trial's
        # Agents may each use all of it, and the Organization's limit still binds.
        session.add(OrganizationAgentSettings(organization_id=organization.id, default_agent_llm_budget_usd=credit))
        self.organization_user_repository.save_with_session(
            OrganizationUser(user_id=user.id, organization_id=organization.id, role=OrganizationRole.OWNER),
            session,
        )
        self.trial_settings.record_trial(identity.email, session)
        session.commit()
        return user, organization
