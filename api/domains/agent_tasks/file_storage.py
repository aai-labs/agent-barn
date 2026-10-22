from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlmodel import Session, col, delete, select

from api.domains.agent_tasks.models import AgentTaskFileChunk
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

CHUNK_BYTES = 1024 * 1024


class TaskFileStorage(Protocol):
    """Where Task File bytes live, keyed by the File's id.

    Tasks only know File metadata, so moving bytes to object storage replaces this
    store and its binding, nothing else. `write` streams the upload and returns how
    many bytes it stored; it takes the transaction that records the File, and a store
    outside Postgres would upload before that commit. `delete` takes the transaction
    that removes the File.
    """

    def write(self, session: Session, file_id: UUID, data: Iterable[bytes]) -> int: ...

    def read(self, file_id: UUID) -> Iterator[bytes]: ...

    def delete(self, session: Session, file_id: UUID) -> None: ...


@dataclass
class PostgresTaskFileStorage:
    """Stores each File as ordered chunks, removed with their File by cascade."""

    delegate: PostgresRepositoryDelegate

    def write(self, session: Session, file_id: UUID, data: Iterable[bytes]) -> int:
        """Re-cut the upload into fixed chunks, flushing each so memory stays at about one chunk."""
        buffer = bytearray()
        sequence = 0
        total = 0

        def store(chunk: bytes) -> None:
            nonlocal sequence
            row = AgentTaskFileChunk(file_id=file_id, sequence=sequence, data=chunk)
            session.add(row)
            session.flush()
            session.expunge(row)
            sequence += 1

        for piece in data:
            total += len(piece)
            buffer += piece
            while len(buffer) >= CHUNK_BYTES:
                store(bytes(buffer[:CHUNK_BYTES]))
                del buffer[:CHUNK_BYTES]
        if buffer:
            store(bytes(buffer))
        return total

    def read(self, file_id: UUID) -> Iterator[bytes]:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentTaskFileChunk.data)
                .where(col(AgentTaskFileChunk.file_id) == file_id)
                .order_by(col(AgentTaskFileChunk.sequence))
                .execution_options(yield_per=1)
            )
            yield from session.exec(query)

    def delete(self, session: Session, file_id: UUID) -> None:
        session.exec(delete(AgentTaskFileChunk).where(col(AgentTaskFileChunk.file_id) == file_id))
