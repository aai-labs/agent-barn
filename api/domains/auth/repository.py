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

    def get_unused_by_token_hash(self, token_hash: str) -> PasswordResetToken | None:
        return self.delegate.find_one(PasswordResetToken, token_hash=token_hash, is_used=False)

    def invalidate_unused_for_user(self, user_id: UUID) -> int:
        """Mark all of a user's outstanding (unused) tokens as used. Used when a fresh
        link supersedes older ones, or when an invite is revoked. Returns the count."""
        tokens = self.delegate.find_all(PasswordResetToken, user_id=user_id, is_used=False)
        for token in tokens:
            token.is_used = True
        if tokens:
            self.delegate.save_all(tokens)
        return len(tokens)

    def invalidate_unused_for_user_with_session(self, user_id: UUID, session: Session) -> int:
        """Session-scoped variant, so token rotation can share a caller's transaction
        (invite issued atomically with org/membership writes)."""
        tokens = list(
            session.exec(
                select(PasswordResetToken).where(
                    PasswordResetToken.user_id == user_id,
                    PasswordResetToken.is_used == False,  # noqa: E712
                )
            )
        )
        for token in tokens:
            token.is_used = True
            session.add(token)
        return len(tokens)

    def save(self, pwd_reset_token: PasswordResetToken) -> PasswordResetToken:
        self.delegate.save(pwd_reset_token)
        return pwd_reset_token

    def save_with_session(self, pwd_reset_token: PasswordResetToken, session: Session) -> PasswordResetToken:
        session.add(pwd_reset_token)
        session.flush()
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
            existing = session.exec(select(UserSlackConfigToken).where(UserSlackConfigToken.user_id == user_id)).first()
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
