import threading
from uuid import UUID

from injector import Injector

from api.core.utils import create_injector
from api.domains.playbooks.processor import PlaybookExtractionProcessor

_injector_lock = threading.Lock()
_injector: Injector | None = None


def _get_injector() -> Injector:
    """The process-wide injector, built lazily so importing this module opens no engine."""
    global _injector
    if _injector is None:
        with _injector_lock:
            if _injector is None:
                _injector = create_injector()
    return _injector


def process_playbook_extraction(extraction_id: UUID) -> None:
    _get_injector().get(PlaybookExtractionProcessor).process(extraction_id)
