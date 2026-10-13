from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlmodel import Field, SQLModel


class Installation(SQLModel, table=True):
    __tablename__ = "installation"
    __table_args__ = (sa.CheckConstraint("singleton", name="ck_installation_singleton"),)

    singleton: bool = Field(default=True, primary_key=True)
    id: UUID = Field(
        sa_column=sa.Column(
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
            server_default=sa.text("gen_random_uuid()"),
        )
    )
    created_at: datetime = Field(
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))
    )
