from dataclasses import dataclass

from injector import inject, singleton

from api.domains.playbooks.models import PlaybookExtraction, PlaybookExtractionError


class PlaybookExtractionFailed(Exception):
    """A run stopped for a reason people can act on; the code is stored on the run."""

    def __init__(self, error: PlaybookExtractionError) -> None:
        super().__init__(error.value)
        self.error = error


@inject
@singleton
@dataclass
class PlaybookPipeline:
    """Reads the source Agent's sessions and memories and writes the playbook draft."""

    def run(self, extraction: PlaybookExtraction) -> None:
        raise PlaybookExtractionFailed(PlaybookExtractionError.PIPELINE_UNAVAILABLE)
