"""Bounded subset of the pinned Hindsight 0.10.2 wire contract.

Unknown fields are discarded. Visibility, traces, raw chunks, directives, entity
selection, and strategy overrides are never forwarded from a runtime.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class MemoryAccess:
    agent_id: UUID
    organization_id: UUID
    readable_tags: tuple[str, ...]
    organization_memory: bool


class EntityOptions(BaseModel):
    max_tokens: int = Field(default=500, ge=1, le=2000)


class RecallInclude(BaseModel):
    entities: EntityOptions | None = Field(default_factory=EntityOptions)


class MemoryRecall(BaseModel):
    query: str = Field(min_length=1, max_length=20000)
    budget: Literal["low", "mid", "high"] = "mid"
    max_tokens: int = Field(default=4096, ge=1, le=8192)
    types: list[Literal["world", "experience", "observation"]] | None = Field(default=None, max_length=3)
    prefer_observations: bool = False
    query_timestamp: str | None = None
    include: RecallInclude = Field(default_factory=RecallInclude)


class MemoryReflect(BaseModel):
    query: str = Field(min_length=1, max_length=20000)
    budget: Literal["low", "mid", "high"] = "low"
    max_tokens: int = Field(default=4096, ge=1, le=8192)
    context: str | None = Field(default=None, max_length=20000)
    response_schema: dict | None = None
    fact_types: list[Literal["world", "experience", "observation"]] | None = Field(default=None, max_length=3)


class MemoryRetainItem(BaseModel):
    content: str = Field(min_length=1, max_length=100000)
    context: str | None = Field(default=None, max_length=20000)
    metadata: dict[str, str] | None = None
    timestamp: str | None = None
    document_id: str | None = Field(default=None, max_length=1000)
    tags: list[str] | None = Field(default=None, max_length=100)
    update_mode: Literal["append", "replace"] | None = None


class MemoryRetain(BaseModel):
    items: list[MemoryRetainItem] = Field(min_length=1, max_length=20)
    async_: bool = Field(default=False, alias="async")
    operation_id: UUID | None = None


class MemoryViewQuery(BaseModel):
    """The only client-controlled inputs of the read-only viewer."""

    model_config = ConfigDict(extra="forbid")

    search: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=25, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=100000)


class MemoryViewItem(BaseModel):
    """Allowlisted fields of one saved memory; entities, chunks, history, and metadata are excluded."""

    id: str
    type: Literal["world", "experience", "observation"]
    text: str
    mentioned_at: datetime | None
    shared: bool


class MemoryViewPage(BaseModel):
    items: list[MemoryViewItem]
    total: int = Field(ge=0)
