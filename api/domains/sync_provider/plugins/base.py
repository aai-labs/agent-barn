from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from api.domains.sync_provider.models import SyncProviderCapability, SyncProviderDescriptorRead


class SyncLocationGuard(StrEnum):
    """A check another domain owns that a chosen location must pass before anything is granted.

    The plugin only names it; the sync provider service binds each member to the owning
    service, so a plugin never imports another domain.
    """

    SHAREPOINT_AGENT_SITES = "sharepoint_agent_sites"


@dataclass(frozen=True)
class SyncLocation:
    id: str
    name: str
    web_url: str


@dataclass(frozen=True)
class SyncFolder:
    id: str
    web_url: str


@dataclass(frozen=True)
class SignedIn:
    account_id: str
    access_token: str
    expires_in: int


@dataclass(frozen=True)
class Provisioned:
    folder: SyncFolder
    provider_data: dict[str, str]


@dataclass(frozen=True)
class SyncRoot:
    """Where an active connection's "Agent Barn" folder is at the provider (FILE_SYNC)."""

    account_id: str
    location_id: str | None
    folder_id: str
    folder_name: str


@dataclass(frozen=True)
class RemoteItem:
    """A file or folder at the provider (FILE_SYNC).

    ``path`` is relative to the "Agent Barn" folder, e.g. ``Sales Bot/workspace/notes.md``; it is
    None for an item outside that folder, and for a deleted item, which carries only its id.
    ``version`` changes on any change; ``content_version`` only when the contents change.
    """

    id: str
    name: str | None
    parent_id: str | None
    path: str | None
    version: str | None
    content_version: str | None
    size: int
    content_hash: str | None
    is_folder: bool
    deleted: bool
    modified_at: datetime | None
    modified_by_app: bool
    web_url: str | None


@dataclass(frozen=True)
class RemoteChanges:
    """One page of changes under the "Agent Barn" folder. Store ``cursor`` once the page is
    handled; ``more`` means the next page is already waiting."""

    items: list[RemoteItem]
    cursor: str
    more: bool


@dataclass(frozen=True)
class UploadTarget:
    """A pre-authenticated URL the Agent's pod uploads one file to, without any provider token."""

    url: str
    expires_at: datetime


class SyncProviderError(Exception):
    """A provider failure carrying the message to show the person connecting."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SignInRefused(SyncProviderError):
    pass


class SignInIncomplete(SyncProviderError):
    pass


class LocationNotFound(SyncProviderError):
    pass


class LocationAccessRefused(SyncProviderError):
    pass


class ProviderThrottled(SyncProviderError):
    """The provider is limiting requests. ``retry_after`` is the wait it asked for, in seconds."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderUnavailable(SyncProviderError):
    pass


class ProvisioningFailed(SyncProviderError):
    pass


class RemoteItemMissing(SyncProviderError):
    pass


class RemoteNameTaken(SyncProviderError):
    pass


class RemoteChangeRejected(SyncProviderError):
    pass


class RemoteResyncRequired(SyncProviderError):
    pass


class SyncProviderPlugin(ABC):
    """One storage provider an Organization can connect. Talks to the provider only; storage,
    permissions, state and the connection lifecycle belong to the sync provider service."""

    key: str
    display_name: str
    tagline: str
    folder_hint: str
    connect_hint: str | None = None
    location_noun: str | None = None
    schema_version: int = 1
    capabilities: frozenset[SyncProviderCapability] = frozenset()
    location_guard: SyncLocationGuard | None = None

    def is_offered(self) -> bool:
        return True

    @property
    def descriptor(self) -> SyncProviderDescriptorRead:
        return SyncProviderDescriptorRead(
            key=self.key,
            display_name=self.display_name,
            tagline=self.tagline,
            folder_hint=self.folder_hint,
            connect_hint=self.connect_hint,
            location_noun=self.location_noun,
            available=self.is_offered(),
            schema_version=self.schema_version,
            capabilities=sorted(self.capabilities, key=lambda item: item.value),
        )

    @abstractmethod
    def authorize_url(self, *, redirect_uri: str, state: str, code_challenge: str) -> str:
        """The provider's sign-in page for the popup."""

    def approval_url(self, *, redirect_uri: str) -> str:
        """A link to forward to whoever must approve Agent Barn at the provider (ADMIN_APPROVAL)."""
        raise NotImplementedError(f"{self.key} has no approval link")

    def is_approval_callback(self, query: Mapping[str, str]) -> bool:
        """Whether the callback is the approver returning, rather than a sign-in (ADMIN_APPROVAL)."""
        del query
        return False

    def callback_error_message(self, error: str, description: str) -> str:
        del description
        return f"{self.display_name} sign-in was cancelled or failed ({error})."

    @abstractmethod
    def complete_sign_in(self, *, code: str, code_verifier: str, redirect_uri: str) -> SignedIn:
        """Redeem the code. Raises SignInRefused, SignInIncomplete or ProviderUnavailable."""

    @abstractmethod
    def require_same_account(self, stored_account_id: str, signed_in: SignedIn) -> None:
        """Raise SignInRefused unless the sign-in is for the account that connected."""

    def search_locations(self, token: str, query: str) -> list[SyncLocation]:
        """Locations the signed-in person can see that match ``query`` (LOCATION_PICKER)."""
        del token, query
        raise NotImplementedError(f"{self.key} has no location picker")

    def resolve_location(self, token: str, location_id: str) -> SyncLocation:
        """The chosen location as the provider describes it (LOCATION_PICKER)."""
        del token, location_id
        raise NotImplementedError(f"{self.key} has no location picker")

    @abstractmethod
    def provision(self, token: str, *, account_id: str, location: SyncLocation | None, folder_name: str) -> Provisioned:
        """Give Agent Barn access and make its folder. Undoes its own access before raising."""

    @abstractmethod
    def undo_provision(self, token: str, *, location_id: str | None, provider_data: dict[str, str]) -> None:
        """Take back a provisioning that could not be recorded. Never raises."""

    @abstractmethod
    def revoke(self, token: str, *, location_id: str | None, provider_data: dict[str, str]) -> None:
        """Take back Agent Barn's access on disconnect. The folder stays."""

    def create_folder(self, root: SyncRoot, *, parent_id: str, name: str) -> RemoteItem:
        """A new folder under ``parent_id``. Raises RemoteNameTaken if the name is in use (FILE_SYNC)."""
        del root, parent_id, name
        raise NotImplementedError(f"{self.key} has no file sync")

    def get_item(self, root: SyncRoot, *, item_id: str) -> RemoteItem:
        """The item now. Raises RemoteItemMissing when it is gone (FILE_SYNC)."""
        del root, item_id
        raise NotImplementedError(f"{self.key} has no file sync")

    def get_item_by_path(self, root: SyncRoot, *, parent_id: str, rel_path: str) -> RemoteItem:
        """The item at ``rel_path`` under ``parent_id``. Raises RemoteItemMissing (FILE_SYNC)."""
        del root, parent_id, rel_path
        raise NotImplementedError(f"{self.key} has no file sync")

    def move_item(
        self, root: SyncRoot, *, item_id: str, name: str | None = None, parent_id: str | None = None
    ) -> RemoteItem:
        """Rename the item, move it under ``parent_id``, or both (FILE_SYNC)."""
        del root, item_id, name, parent_id
        raise NotImplementedError(f"{self.key} has no file sync")

    def delete_item(self, root: SyncRoot, *, item_id: str) -> None:
        """Delete the item to the provider's recycle bin. One already gone is not an error (FILE_SYNC)."""
        del root, item_id
        raise NotImplementedError(f"{self.key} has no file sync")

    def list_files(self, root: SyncRoot, *, folder_id: str) -> list[RemoteItem]:
        del root, folder_id
        raise NotImplementedError(f"{self.key} has no file sync")

    def changes(self, root: SyncRoot, cursor: str | None, *, from_start: bool = False) -> RemoteChanges:
        """The next page of changes under the root since ``cursor``. Without a cursor, the feed starts
        now, or with everything under the root when ``from_start``. Raises RemoteResyncRequired when
        the cursor is no longer valid (FILE_SYNC)."""
        del root, cursor, from_start
        raise NotImplementedError(f"{self.key} has no file sync")

    def upload_target(self, root: SyncRoot, *, parent_id: str, rel_path: str) -> UploadTarget:
        """A URL the pod uploads the file at ``rel_path`` under ``parent_id`` to, replacing it (FILE_SYNC)."""
        del root, parent_id, rel_path
        raise NotImplementedError(f"{self.key} has no file sync")

    def download_url(self, root: SyncRoot, *, item_id: str) -> str:
        """A short-lived URL the pod downloads the item from (FILE_SYNC)."""
        del root, item_id
        raise NotImplementedError(f"{self.key} has no file sync")

    def write_empty_file(self, root: SyncRoot, *, parent_id: str, rel_path: str) -> RemoteItem:
        """Write a 0-byte file at ``rel_path``, which needs no upload from the pod (FILE_SYNC)."""
        del root, parent_id, rel_path
        raise NotImplementedError(f"{self.key} has no file sync")
