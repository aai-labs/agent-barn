from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.domains.auth.models import SlackConfigTokenRead
from api.domains.auth.repository import SlackConfigTokenRepository
from api.infrastructure.crypto import decrypt_token, encrypt_token
from api.infrastructure.slack.config_token import (
    rotate_refresh_token,
    validate_config_access_token,
)


def _mask_token(token: str) -> str:
    if len(token) <= 12:
        return token[:4] + "****"
    return token[:5] + "****" + token[-4:]


@inject
@singleton
@dataclass
class SlackConfigTokenService:
    repository: SlackConfigTokenRepository
    config: Config

    def get_config_token_read(self, user_id: UUID) -> SlackConfigTokenRead:
        record = self.repository.get_by_user_id(user_id)
        if not record:
            return SlackConfigTokenRead(has_token=False, token_preview=None)

        try:
            access_token = decrypt_token(
                record.access_token_encrypted,
                self.config.agent_token_encryption_key,
            )
            preview = _mask_token(access_token)
        except Exception:
            preview = "****"

        return SlackConfigTokenRead(has_token=True, token_preview=preview)

    def save_config_token(
        self, user_id: UUID, access_token_raw: str, refresh_token_raw: str = "",
    ) -> SlackConfigTokenRead:
        access = access_token_raw.strip()
        refresh = refresh_token_raw.strip()
        if not access:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Access token cannot be empty.",
            )

        validate_config_access_token(access)
        key = self.config.agent_token_encryption_key
        self.repository.upsert(
            user_id=user_id,
            access_token_encrypted=encrypt_token(access, key),
            refresh_token_encrypted=(
                encrypt_token(refresh, key) if refresh else ""
            ),
        )

        return SlackConfigTokenRead(
            has_token=True,
            token_preview=_mask_token(access),
        )

    def get_usable_access_token(self, user_id: UUID) -> str:
        record = self.repository.get_by_user_id(user_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "No Slack configuration token found. Save one in your account "
                    "settings first."
                ),
            )

        key = self.config.agent_token_encryption_key
        if record.refresh_token_encrypted:
            try:
                refresh_token = decrypt_token(record.refresh_token_encrypted, key)
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Stored refresh token is corrupted. Please re-save your "
                        "configuration token."
                    ),
                ) from exc

            new_access_token, new_refresh_token = rotate_refresh_token(refresh_token)
            self.repository.upsert(
                user_id=user_id,
                access_token_encrypted=encrypt_token(new_access_token, key),
                refresh_token_encrypted=encrypt_token(new_refresh_token, key),
            )
            return new_access_token

        try:
            return decrypt_token(record.access_token_encrypted, key)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Stored access token is corrupted. Please re-save your "
                    "configuration token."
                ),
            ) from exc

    def delete_config_token(self, user_id: UUID) -> None:
        self.repository.delete_by_user_id(user_id)
