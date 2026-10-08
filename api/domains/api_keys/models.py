from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel as DTO
from pydantic import Field as DTOField
from sqlalchemy import Column, DateTime, Index
from sqlmodel import Field

from api.infrastructure.postgres.models import BaseModel


class ApiKeyAccessMode(StrEnum):
    READ_ONLY = "READ_ONLY"
    FULL = "FULL"


class ApiKey(BaseModel, table=True):
    __tablename__ = "api_key"
    __table_args__ = (
        Index("uq_api_key_token_hash", "token_hash", unique=True),
        Index("ix_api_key_user_created", "user_id", "created_at"),
    )

    user_id: UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE")
    name: str = Field(max_length=100, nullable=False)
    token_hash: str = Field(max_length=64, nullable=False)
    token_prefix: str = Field(max_length=16, nullable=False)
    access_mode: ApiKeyAccessMode = Field(nullable=False)
    security_stamp: str = Field(nullable=False)
    expires_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    revoked_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    last_used_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))


class ApiKeyCreate(DTO):
    name: str = DTOField(min_length=1, max_length=100)
    access_mode: ApiKeyAccessMode = ApiKeyAccessMode.READ_ONLY
    expires_at: datetime | None = None


class ApiKeyRead(DTO):
    id: UUID
    name: str
    token_prefix: str
    access_mode: ApiKeyAccessMode
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    status: str


class ApiKeyCreated(DTO):
    api_key: ApiKeyRead
    token: str
