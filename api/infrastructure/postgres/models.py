import datetime
import uuid

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class BaseModel(SQLModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid7, primary_key=True)
    created_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
        sa_type=sa.DateTime(timezone=True),  # type: ignore
        nullable=False,
    )
    updated_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
        sa_type=sa.DateTime(timezone=True),  # type: ignore
        nullable=False,
        sa_column_kwargs={"onupdate": lambda: datetime.datetime.now(datetime.UTC)},
    )
