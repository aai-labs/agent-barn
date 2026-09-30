import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.api_keys.models import ApiKey, ApiKeyCreate, ApiKeyCreated, ApiKeyRead
from api.domains.api_keys.repository import ApiKeyRepository
from api.domains.auth.exceptions import CredentialsException
from api.domains.auth.models import CurrentUserContext
from api.domains.events.dispatch import EventDeliveryDispatcher
from api.domains.users.models import User
from api.domains.users.repository import UserRepository


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


@inject
@singleton
@dataclass
class ApiKeyService:
    repository: ApiKeyRepository
    users: UserRepository
    dispatcher: EventDeliveryDispatcher

    def to_read(self, key: ApiKey, security_stamp: str) -> ApiKeyRead:
        now = datetime.now(UTC)
        state = (
            "REVOKED"
            if key.revoked_at
            else "INVALIDATED"
            if key.security_stamp != security_stamp
            else "EXPIRED"
            if key.expires_at and key.expires_at <= now
            else "ACTIVE"
        )
        return ApiKeyRead(
            id=key.id,
            name=key.name,
            token_prefix=key.token_prefix,
            access_mode=key.access_mode,
            created_at=key.created_at,
            expires_at=key.expires_at,
            revoked_at=key.revoked_at,
            last_used_at=key.last_used_at,
            status=state,
        )

    def create(self, context: CurrentUserContext, data: ApiKeyCreate) -> ApiKeyCreated:
        name = data.name.strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Name is required")
        if context.user.email_verified_at is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account must be verified")
        if data.expires_at is not None and (data.expires_at.tzinfo is None or data.expires_at <= datetime.now(UTC)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Expiration must be a future time with a timezone",
            )
        raw = "abk_" + secrets.token_urlsafe(32)
        key = ApiKey(
            user_id=context.user.id,
            name=name,
            token_hash=hash_token(raw),
            token_prefix=raw[:12],
            access_mode=data.access_mode,
            security_stamp=context.user.security_stamp,
            expires_at=data.expires_at,
        )
        delivery_ids = self.repository.create(key, context.user.id, context.user.email)
        self.dispatcher.enqueue_immediate(delivery_ids)
        return ApiKeyCreated(api_key=self.to_read(key, context.user.security_stamp), token=raw)

    def list_owned(self, context: CurrentUserContext) -> list[ApiKeyRead]:
        return [self.to_read(key, context.user.security_stamp) for key in self.repository.list_by_user(context.user.id)]

    def revoke(self, context: CurrentUserContext, key_id: UUID) -> None:
        key, delivery_ids = self.repository.revoke_owned(context.user.id, key_id, datetime.now(UTC), context.user.email)
        if key is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
        self.dispatcher.enqueue_immediate(delivery_ids)

    def authenticate(self, raw: str) -> tuple[User, ApiKey]:
        if re.fullmatch(r"abk_[A-Za-z0-9_-]{43}", raw) is None:
            raise CredentialsException()
        key = self.repository.get_by_hash(hash_token(raw))
        if key is None or key.revoked_at is not None:
            raise CredentialsException()
        user = self.users.get(key.user_id)
        if user is None or user.email_verified_at is None or key.security_stamp != user.security_stamp:
            raise CredentialsException()
        now = datetime.now(UTC)
        if key.expires_at is not None and key.expires_at <= now:
            raise CredentialsException()
        if key.last_used_at is None or key.last_used_at < now - timedelta(minutes=1):
            self.repository.touch_last_used(key.id, now)
        return user, key
