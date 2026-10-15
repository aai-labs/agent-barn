from typing import Any, Literal, Self
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as DTO
from pydantic import ConfigDict, Field, model_validator
from sqlmodel import Field as SqlField

from api.domains.custom_api.request import credential_headers, parse_url
from api.infrastructure.postgres.models import BaseModel


class CustomApiConnection(BaseModel, table=True):
    __tablename__: str = "custom_api_connection"
    __table_args__ = (sa.UniqueConstraint("agent_id", "slug", name="uq_custom_api_connection_slug"),)

    agent_id: UUID = SqlField(foreign_key="agent.id", nullable=False, ondelete="CASCADE", index=True)
    slug: str = SqlField(max_length=64)
    name: str = SqlField(max_length=120)
    base_url: str
    isolated: bool = False
    credentials_encrypted: str
    token_hash: str | None = None
    generation: UUID | None = None


class HeaderInput(DTO):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    value: str | None = Field(default=None, max_length=8192)
    secret: bool = False


class AuthInput(DTO):
    model_config = ConfigDict(extra="forbid")
    type: Literal["none", "bearer", "api_key", "basic"]
    header_name: str | None = None
    token: str | None = Field(default=None, max_length=8192)
    username: str | None = Field(default=None, max_length=1024)
    password: str | None = Field(default=None, max_length=8192)


class CustomApiConnectionCreate(DTO):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(max_length=2048)
    isolated: bool = False
    restart: bool = False
    auth: AuthInput = Field(default_factory=lambda: AuthInput(type="none"))
    headers: list[HeaderInput] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def validate_url(self) -> Self:
        parse_url(self.base_url, base=True)
        return self


class CustomApiConnectionUpdate(DTO):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = Field(default=None, max_length=2048)
    isolated: bool | None = None
    auth: AuthInput | None = None
    headers: list[HeaderInput] | None = Field(default=None, max_length=32)


class HeaderRead(DTO):
    name: str
    secret: bool
    value: str | None = None


class CustomApiConnectionRead(DTO):
    id: UUID
    slug: str
    name: str
    base_url: str
    isolated: bool
    applied_isolated: bool | None
    pending_apply: bool
    auth_type: str
    auth_header_name: str | None = None
    headers: list[HeaderRead]


def validate_credentials(config: dict) -> None:
    credential_headers(config)


class CustomApiRequest(DTO):
    model_config = ConfigDict(extra="forbid")
    method: str = "GET"
    url: str = Field(max_length=8192)
    query: dict[str, Any] = Field(default_factory=dict)
    body: Any = None
    headers: list[HeaderInput] = Field(default_factory=list, max_length=32)


class CustomApiConnectionApply(CustomApiConnectionUpdate):
    restart: bool = False
