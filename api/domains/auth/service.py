from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid7

import jwt
from fastapi import BackgroundTasks, HTTPException, status
from injector import inject, singleton
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from sqlmodel import Session

from api.core.config import Config
from api.domains.auth.hashing import hash_text
from api.domains.auth.models import (
    ForgotPasswordRequest,
    PasswordResetRequest,
    PasswordResetToken,
    PasswordResetTokenData,
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
        now = datetime.now(timezone.utc)
        to_encode.update(
            {"iat": int(now.timestamp()), "exp": exp, "jti": jti or str(uuid7())}
        )
        return jwt.encode(
            to_encode, self.config.secret_signing_key, algorithm=JWT_ENCODING_ALGORITHM
        )

    def create_access_token(self, data: TokenData) -> str:
        to_encode = data.model_dump().copy()
        to_encode["token_type"] = "access"

        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=self.config.access_token_expire_minutes
            or DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES
        )
        return self._encode_jwt(data=to_encode, exp=expires_at.timestamp())

    def create_refresh_token(self, data: TokenData) -> str:
        expires = timedelta(
            days=self.config.refresh_token_expire_days
            or DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS
        )
        token = self.refresh_token_repository.save(
            RefreshToken(
                token=str(uuid7()),
                user_id=UUID(data.user_id),
                expires_at=datetime.now(timezone.utc) + expires,
                stamp=data.stamp,
            )
        )
        return token.token

    def create_token_pair(self, data: TokenData) -> Token:
        access_token = self.create_access_token(data)
        refresh_token = self.create_refresh_token(data)
        return Token(
            access_token=access_token, refresh_token=refresh_token, token_type="bearer"
        )

    def _create_signup_user_and_organization(
        self,
        *,
        email: str,
        full_name: str | None,
        hashed_password: str,
    ) -> User:
        with Session(self.user_repository.delegate.engine) as session:
            existing_user = self.user_repository.get_by_email_with_session(
                email, session
            )
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
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email already in use"
            )

        return self.create_token_pair(
            TokenData(user_id=str(user.id), stamp=user.security_stamp)
        )

    def verify_refresh_token(self, token: str) -> RefreshToken:
        refresh_token = self.refresh_token_repository.get(token)
        if not refresh_token or refresh_token.expires_at < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or revoked refresh token",
            )
        return refresh_token

    def revoke_refresh_token(self, token: RefreshToken):
        return self.refresh_token_repository.delete(token)

    def generate_password_reset_token(self, user_id: UUID) -> str:
        jti = str(uuid7())
        data = PasswordResetTokenData(user_id=str(user_id), jti=jti)
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=DEFAULT_PWD_RESET_TOKEN_EXPIRE_MINUTES
        )
        token = self._encode_jwt(
            data=data.model_dump(), exp=expires_at.timestamp(), jti=jti
        )

        self.pwd_reset_token_repository.save(
            PasswordResetToken(
                user_id=user_id, is_used=False, jti=jti, expires_at=expires_at
            )
        )
        return token

    def verify_password_reset_token(self, token: str) -> PasswordResetToken:
        try:
            payload = jwt.decode(
                token,
                self.config.secret_signing_key,
                algorithms=[JWT_ENCODING_ALGORITHM],
            )
            user_id = payload.get("user_id")
            jti = payload.get("jti")
            if user_id is None or jti is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid password reset token",
                )

            saved_token = self.pwd_reset_token_repository.get_unused_by_jti(jti)
            if saved_token is None or saved_token.is_used:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid password reset token",
                )
            if saved_token.expires_at < datetime.now(timezone.utc):
                raise HTTPException(
                    status_code=status.HTTP_410_GONE,
                    detail="Password reset token expired",
                )
            return saved_token
        except ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_410_GONE, detail="Password reset token expired"
            )
        except InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid password reset token",
            )

    def reset_password(self, reset_request: PasswordResetRequest):
        validate_strong_password(reset_request.new_password)
        reset_token = self.verify_password_reset_token(reset_request.token)
        user = self.user_repository.get(reset_token.user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        user.hashed_password = hash_text(reset_request.new_password)
        user.security_stamp = uuid7().hex
        self.user_repository.save(user)

        reset_token.is_used = True
        self.pwd_reset_token_repository.save(reset_token)

    def forgot_password(self, request: ForgotPasswordRequest):
        user = self.user_repository.get_by_email(str(request.email))
        if not user:
            return

        token = self.generate_password_reset_token(user.id)
        self.email_service.send_password_reset_email(
            receiver_email=user.email,
            password_reset_link=f"{self.config.web_app_url}/auth/reset-password?token={token}",
            receiver_name=user.full_name,
        )
