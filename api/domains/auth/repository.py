from dataclasses import dataclass
from typing import List
from uuid import UUID

from injector import inject, singleton
from sqlmodel import Session, select

from api.domains.auth.models import (
    PasswordResetToken,
    RefreshToken,
    UserSlackConfigToken,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class RefreshTokenRepository:
    delegate: PostgresRepositoryDelegate

    def get(self, token: str) -> RefreshToken | None:
        return self.delegate.find_one(RefreshToken, token=token)

    def get_by_user(self, user_id: UUID) -> List[RefreshToken]:
        return self.delegate.find_all(RefreshToken, user_id=user_id)

    def save(self, refresh_token: RefreshToken) -> RefreshToken:
        self.delegate.save(refresh_token)
        return refresh_token

    def delete(self, refresh_token: RefreshToken) -> bool:
        return self.delegate.delete_one(RefreshToken, refresh_token.id)

    def delete_all_by(self, tokens: List[RefreshToken]) -> bool:
        return self.delegate.delete_many(tokens)


@inject
@singleton
@dataclass
class PasswordResetTokenRepository:
    delegate: PostgresRepositoryDelegate

    def get_unused_by_jti(self, jti: str) -> PasswordResetToken | None:
        return self.delegate.find_one(PasswordResetToken, jti=jti, is_used=False)

    def save(self, pwd_reset_token: PasswordResetToken) -> PasswordResetToken:
        self.delegate.save(pwd_reset_token)
        return pwd_reset_token


@inject
@singleton
@dataclass
class SlackConfigTokenRepository:
    delegate: PostgresRepositoryDelegate

    def get_by_user_id(self, user_id: UUID) -> UserSlackConfigToken | None:
        return self.delegate.find_one(UserSlackConfigToken, user_id=user_id)

    def upsert(
        self,
        user_id: UUID,
        access_token_encrypted: str,
        refresh_token_encrypted: str,
    ) -> UserSlackConfigToken:
        with Session(self.delegate.engine) as session:
            existing = session.exec(
                select(UserSlackConfigToken).where(
                    UserSlackConfigToken.user_id == user_id
                )
            ).first()
            if existing:
                existing.access_token_encrypted = access_token_encrypted
                existing.refresh_token_encrypted = refresh_token_encrypted
                session.commit()
                session.refresh(existing)
                return existing

            token = UserSlackConfigToken(
                user_id=user_id,
                access_token_encrypted=access_token_encrypted,
                refresh_token_encrypted=refresh_token_encrypted,
            )
            session.add(token)
            session.commit()
            session.refresh(token)
            return token

    def delete_by_user_id(self, user_id: UUID) -> bool:
        return self.delegate.delete_all(UserSlackConfigToken, user_id=user_id)
