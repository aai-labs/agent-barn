from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
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
    pass


class ProviderUnavailable(SyncProviderError):
    pass


class ProvisioningFailed(SyncProviderError):
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
    server_setup_hint: str | None = None
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
            server_setup_hint=self.server_setup_hint,
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
