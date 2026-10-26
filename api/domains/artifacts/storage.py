"""Private byte-store boundary; download authority is issued and checked by the provider."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from api.domains.artifacts.models import Artifact


class DownloadDenied(Exception):
    """The provider rejected a missing, forged, or expired download capability."""


@dataclass
class ArtifactDownload:
    filename: str
    size: int
    chunks: Iterator[bytes]
    close: Callable[[], None]


class ArtifactStorage(ABC):
    @abstractmethod
    def put(self, artifact: Artifact, content: bytes) -> None: ...

    @abstractmethod
    def issue_download(self, artifact: Artifact, seconds: int) -> str:
        """Return opaque provider authority, not a public storage address."""
        ...

    @abstractmethod
    def download(self, artifact: Artifact, access: str) -> ArtifactDownload: ...

    @abstractmethod
    def delete(self, artifact: Artifact) -> None: ...
