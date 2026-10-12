from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.auth.models import PasswordResetToken, RefreshToken
from api.domains.events.catalog import EVENT_REGISTRY, USER_SIGNED_UP
from api.domains.events.models import ActorIdentity, ActorIdentityType, SubjectIdentity, SubjectIdentityType
from api.domains.events.repository import OutboxMessageRepository
from api.domains.users.models import User
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class RefreshTokenRepository:
    delegate: PostgresRepositoryDelegate

    def get(self, token: str) -> RefreshToken | None:
        return self.delegate.find_one(RefreshToken, token=token)

    def get_by_user(self, user_id: UUID) -> list[RefreshToken]:
        return self.delegate.find_all(RefreshToken, user_id=user_id)

    def save(self, refresh_token: RefreshToken) -> RefreshToken:
        self.delegate.save(refresh_token)
        return refresh_token

    def delete(self, refresh_token: RefreshToken) -> bool:
        return self.delegate.delete_one(RefreshToken, refresh_token.id)

    def delete_all_by(self, tokens: list[RefreshToken]) -> bool:
        return self.delegate.delete_many(tokens)


@inject
@singleton
@dataclass
class PasswordResetTokenRepository:
    delegate: PostgresRepositoryDelegate
    outbox_repository: OutboxMessageRepository

    def redeem(
        self,
        token_id: UUID,
        *,
        hashed_password: str,
        security_stamp: str,
        mark_email_verified: bool,
        full_name: str | None,
    ) -> tuple[User, list[UUID]] | None:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            token = session.exec(
                select(PasswordResetToken).where(col(PasswordResetToken.id) == token_id).with_for_update()
            ).first()
            if token is None or token.is_used:
                return None
            user = session.exec(select(User).where(col(User.id) == token.user_id).with_for_update()).first()
            if user is None:
                return None
            signed_up = mark_email_verified and user.email_verified_at is None
            user.hashed_password = hashed_password
            user.security_stamp = security_stamp
            if signed_up:
                user.email_verified_at = datetime.now(UTC)
            if full_name is not None:
                user.full_name = full_name
            token.is_used = True
            session.add(user)
            session.add(token)
            delivery_ids: list[UUID] = []
            if signed_up:
                event = EVENT_REGISTRY.build_event(
                    event_name=USER_SIGNED_UP,
                    schema_version=1,
                    occurred_at=datetime.now(UTC),
                    organization_id=None,
                    actor=ActorIdentity(type=ActorIdentityType.USER, id=user.id),
                    subject=SubjectIdentity(type=SubjectIdentityType.USER, id=user.id),
                    correlation_id=uuid4(),
                    payload={"user_id": user.id},
                )
                self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
                delivery_ids = self.outbox_repository.delivery_ids_for_event(session, event.event_id)
            session.commit()
            return user, delivery_ids

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

    def refresh_unused_expiry_for_user_with_session(self, user_id: UUID, expires_at: datetime, session: Session) -> int:
        """Push out the expiry of a user's outstanding (unused) links without touching the
        tokens themselves, so the link already sitting in their inbox keeps working. Shares
        the caller's transaction. Returns the count."""
        tokens = list(
            session.exec(
                select(PasswordResetToken).where(
                    PasswordResetToken.user_id == user_id,
                    PasswordResetToken.is_used == False,
                )
            )
        )
        for token in tokens:
            token.expires_at = expires_at
            session.add(token)
        return len(tokens)

    def save(self, pwd_reset_token: PasswordResetToken) -> PasswordResetToken:
        self.delegate.save(pwd_reset_token)
        return pwd_reset_token

    def save_with_session(self, pwd_reset_token: PasswordResetToken, session: Session) -> PasswordResetToken:
        session.add(pwd_reset_token)
        session.flush()
        return pwd_reset_token
