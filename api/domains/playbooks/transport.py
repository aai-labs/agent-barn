from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton


@inject
@singleton
@dataclass
class PlaybookExtractionQueue:
    """Hands an accepted run to the worker. Tests replace it to run the worker inline."""

    def enqueue(self, extraction_id: UUID) -> None:
        from api.worker_app import playbook_extraction_actor

        playbook_extraction_actor.send(str(extraction_id))
