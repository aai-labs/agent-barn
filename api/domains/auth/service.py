import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

import jwt
from fastapi import BackgroundTasks, HTTPException, status
from injector import inject, singleton
from sqlmodel import Session

from api.core.config import Config
from api.domains.auth.hashing import hash_text
from api.domains.auth.models import (
    AcceptInviteRequest,
    ForgotPasswordRequest,
    PasswordResetRequest,
    PasswordResetToken,
    RefreshToken,
    SignupRequest,
    Token,
    TokenData,
)
from api.domains.auth.password_validation import validate_strong_password
from api.domains.auth.repository import (
    PasswordResetTokenRepository,
    RefreshTokenRepository,
)
from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.exceptions import EmailTakenHTTPException
from api.domains.users.models import User
from api.domains.users.organization_users.models import (
    OrganizationRole,
    OrganizationUser,
)
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.domains.users.repository import UserRepository
from api.infrastructure.email.service import EmailService

DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES = 30
DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS = 15
DEFAULT_PWD_RESET_TOKEN_EXPIRE_MINUTES = 60 * 24
JWT_ENCODING_ALGORITHM = "HS256"


@dataclass
class PreparedInvite:
    """An invite whose DB writes are staged in a caller's transaction but whose email
    has not been sent. ``invite_link`` is ``None`` when the user is already active, so no
    invite is needed. Callers commit, then call ``send_prepared_invite``."""

    user: User
    invite_link: str | None


@inject
@singleton
@dataclass
class AuthService:
    config: Config
    refresh_token_repository: RefreshTokenRepository
    pwd_reset_token_repository: PasswordResetTokenRepository
    user_repository: UserRepository
    organization_repository: OrganizationRepository
    organization_user_repository: OrganizationUserRepository
    email_service: EmailService

    @staticmethod
    def _default_organization_name(full_name: str | None) -> str:
        if not full_name:
            return "My Organization"
        first_name = full_name.strip().split(" ")[0]
        if not first_name:
            return "My Organization"
        return f"{first_name}'s Organization"

    def _encode_jwt(self, data: dict, exp: float, jti: str | None = None) -> str:
        to_encode = data.copy()
        now = datetime.now(UTC)
        to_encode.update({"iat": int(now.timestamp()), "exp": exp, "jti": jti or str(uuid7())})
        return jwt.encode(to_encode, self.config.secret_signing_key, algorithm=JWT_ENCODING_ALGORITHM)

    def create_access_token(self, data: TokenData) -> str:
        to_encode = data.model_dump().copy()
        to_encode["token_type"] = "access"

        expires_at = datetime.now(UTC) + timedelta(
            minutes=self.config.access_token_expire_minutes or DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES
        )
        return self._encode_jwt(data=to_encode, exp=expires_at.timestamp())

    def create_refresh_token(self, data: TokenData) -> str:
        expires = timedelta(days=self.config.refresh_token_expire_days or DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS)
        token = self.refresh_token_repository.save(
            RefreshToken(
                token=str(uuid7()),
                user_id=UUID(data.user_id),
                expires_at=datetime.now(UTC) + expires,
                stamp=data.stamp,
            )
        )
        return token.token

    def create_token_pair(self, data: TokenData) -> Token:
        access_token = self.create_access_token(data)
        refresh_token = self.create_refresh_token(data)
        return Token(access_token=access_token, refresh_token=refresh_token, token_type="bearer")

    def _create_signup_user_and_organization(
        self,
        *,
        email: str,
        full_name: str | None,
        hashed_password: str,
    ) -> User:
        with Session(self.user_repository.delegate.engine) as session:
            existing_user = self.user_repository.get_by_email_with_session(email, session)
            if existing_user is not None:
                raise EmailTakenHTTPException(email)

            user = User(
                email=email,
                full_name=full_name,
                hashed_password=hashed_password,
            )
            organization = Organization(name=self._default_organization_name(full_name))

            self.user_repository.save_with_session(user, session)
            self.organization_repository.save_with_session(organization, session)
            self.organization_user_repository.save_with_session(
                OrganizationUser(
                    user_id=user.id,
                    organization_id=organization.id,
                    role=OrganizationRole.OWNER,
                ),
                session,
            )
            session.commit()
            session.refresh(user)

        # Predefined templates are global platform resources seeded once at
        # startup, so a new org needs no per-org catalog clone.
        return user

    def signup(self, signup_request: SignupRequest, _: BackgroundTasks) -> Token:
        validate_strong_password(signup_request.password)
        try:
            user = self._create_signup_user_and_organization(
                email=signup_request.email,
                full_name=signup_request.full_name,
                hashed_password=hash_text(signup_request.password),
            )
        except EmailTakenHTTPException:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")

        return self.create_token_pair(TokenData(user_id=str(user.id), stamp=user.security_stamp))

    def verify_refresh_token(self, token: str) -> RefreshToken:
        refresh_token = self.refresh_token_repository.get(token)
        if not refresh_token or refresh_token.expires_at < datetime.now(UTC):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or revoked refresh token",
            )
        return refresh_token

    def revoke_refresh_token(self, token: RefreshToken):
        return self.refresh_token_repository.delete(token)

    @staticmethod
    def _hash_reset_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def generate_password_reset_token(self, user_id: UUID) -> str:
        # A fresh link supersedes any outstanding one for this user (invite resend /
        # repeated forgot-password), so only the latest link is ever valid.
        self.pwd_reset_token_repository.invalidate_unused_for_user(user_id)

        raw_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(minutes=DEFAULT_PWD_RESET_TOKEN_EXPIRE_MINUTES)
        self.pwd_reset_token_repository.save(
            PasswordResetToken(
                user_id=user_id,
                is_used=False,
                token_hash=self._hash_reset_token(raw_token),
                expires_at=expires_at,
            )
        )
        return raw_token

    def revoke_pending_invites(self, user_id: UUID) -> None:
        """Invalidate a user's outstanding invite/reset links (e.g. when a pending
        invite is rescinded)."""
        self.pwd_reset_token_repository.invalidate_unused_for_user(user_id)

    def verify_password_reset_token(self, token: str) -> PasswordResetToken:
        saved_token = self.pwd_reset_token_repository.get_unused_by_token_hash(self._hash_reset_token(token))
        if saved_token is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid password reset token",
            )
        if saved_token.expires_at < datetime.now(UTC):
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Password reset token expired",
            )
        return saved_token

    def _apply_new_password(
        self,
        reset_request: PasswordResetRequest,
        mark_email_verified: bool,
        full_name: str | None = None,
    ) -> User:
        validate_strong_password(reset_request.new_password)
        reset_token = self.verify_password_reset_token(reset_request.token)
        user = self.user_repository.get(reset_token.user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        user.hashed_password = hash_text(reset_request.new_password)
        user.security_stamp = uuid7().hex
        if mark_email_verified and user.email_verified_at is None:
            user.email_verified_at = datetime.now(UTC)
        # On invite acceptance the user provides their own (authoritative) name.
        if full_name is not None:
            user.full_name = full_name
        self.user_repository.save(user)

        reset_token.is_used = True
        self.pwd_reset_token_repository.save(reset_token)
        return user

    def reset_password(self, reset_request: PasswordResetRequest):
        self._apply_new_password(reset_request, mark_email_verified=False)

    def accept_invite(self, request: AcceptInviteRequest):
        """Complete enrollment: the invitee sets their password + name and their email is
        verified, in one step."""
        self._apply_new_password(request, mark_email_verified=True, full_name=request.full_name)

    def prepare_invite(self, session: Session, email: str, full_name: str | None = None) -> PreparedInvite:
        """Stage an invite's DB writes (find/create pending user + fresh token) inside
        the caller's ``session`` — no commit, no email. Lets org/membership creation and
        the invite share one transaction so a failure can't half-create either. When the
        user already exists and is active, no token is issued (``invite_link`` is None).
        """
        existing = self.user_repository.get_by_email_with_session(email, session)
        if existing is not None and existing.email_verified_at is not None:
            return PreparedInvite(user=existing, invite_link=None)

        if existing is not None:
            user = existing
        else:
            user = User(
                email=email,
                full_name=full_name,
                # Unusable-but-valid hash: login fails until the invite is accepted.
                hashed_password=hash_text(uuid7().hex),
                email_verified_at=None,
            )
            self.user_repository.save_with_session(user, session)

        # A fresh link supersedes any outstanding one, within this transaction.
        self.pwd_reset_token_repository.invalidate_unused_for_user_with_session(user.id, session)
        raw_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(minutes=DEFAULT_PWD_RESET_TOKEN_EXPIRE_MINUTES)
        self.pwd_reset_token_repository.save_with_session(
            PasswordResetToken(
                user_id=user.id,
                is_used=False,
                token_hash=self._hash_reset_token(raw_token),
                expires_at=expires_at,
            ),
            session,
        )
        invite_link = f"{self.config.web_app_url}/set-password?token={raw_token}"
        return PreparedInvite(user=user, invite_link=invite_link)

    def send_prepared_invite(self, prepared: PreparedInvite) -> None:
        """Send the invite email for a committed ``PreparedInvite``. Call only after the
        transaction commits, so we never email someone for a rolled-back org/membership."""
        if prepared.invite_link is None:
            return
        self.email_service.send_user_invite_email(
            receiver_email=prepared.user.email,
            set_password_link=prepared.invite_link,
            receiver_name=prepared.user.full_name,
        )

    def invite_user(self, email: str, full_name: str | None = None) -> tuple[User, str | None]:
        """Single-shot invite (its own transaction): stage, commit, then email. Used
        where there's no larger transaction to join (e.g. resending an invite).
        """
        with Session(self.user_repository.delegate.engine, expire_on_commit=False) as session:
            prepared = self.prepare_invite(session, email, full_name)
            session.commit()
        self.send_prepared_invite(prepared)
        return prepared.user, prepared.invite_link

    def forgot_password(self, request: ForgotPasswordRequest):
        user = self.user_repository.get_by_email(str(request.email))
        if not user:
            return

        token = self.generate_password_reset_token(user.id)
        self.email_service.send_password_reset_email(
            receiver_email=user.email,
            password_reset_link=f"{self.config.web_app_url}/reset-password?token={token}",
            receiver_name=user.full_name,
        )
