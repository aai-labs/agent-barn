from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlmodel import Session, col, select

from api.domains.agent_tasks.models import AgentTaskFileChunk
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

CHUNK_BYTES = 1024 * 1024


class TaskFileStorage(Protocol):
    """Where Task File bytes live, keyed by the File's id.

    Tasks only know File metadata, so moving bytes to object storage replaces this
    store and its binding, nothing else. `write` takes the transaction that records
    the File; a store outside Postgres would upload before that commit.
    """

    def write(self, session: Session, file_id: UUID, data: bytes) -> None: ...

    def read(self, file_id: UUID) -> Iterator[bytes]: ...


@dataclass
class PostgresTaskFileStorage:
    """Stores each File as ordered chunks, removed with their File by cascade."""

    delegate: PostgresRepositoryDelegate

    def write(self, session: Session, file_id: UUID, data: bytes) -> None:
        for sequence, offset in enumerate(range(0, len(data), CHUNK_BYTES)):
            session.add(
                AgentTaskFileChunk(file_id=file_id, sequence=sequence, data=data[offset : offset + CHUNK_BYTES])
            )

    def read(self, file_id: UUID) -> Iterator[bytes]:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentTaskFileChunk.data)
                .where(col(AgentTaskFileChunk.file_id) == file_id)
                .order_by(col(AgentTaskFileChunk.sequence))
                .execution_options(yield_per=1)
            )
            yield from session.exec(query)
