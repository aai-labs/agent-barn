from dataclasses import dataclass
from typing import List
from uuid import UUID

from injector import inject, singleton

from api.domains.auth.models import PasswordResetToken, RefreshToken
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
