"""A second, test-only sync provider beside OneDrive: no location picker, no approval link."""

from dataclasses import dataclass, field

from injector import Module, provider, singleton

from api.core.config import Config
from api.domains.agents.microsoft_graph_sites import MicrosoftGraphSites
from api.domains.agents.microsoft_identity import MicrosoftIdentityClient
from api.domains.sync_provider.plugins.base import (
    Provisioned,
    SignedIn,
    SignInRefused,
    SyncFolder,
    SyncLocation,
    SyncProviderPlugin,
)
from api.domains.sync_provider.plugins.providers import shipped_plugins
from api.domains.sync_provider.plugins.registry import SyncProviderPluginRegistry

OTHER_DRIVE = "otherdrive"
OTHER_ACCOUNT_ID = "other-account"
OTHER_TOKEN = "other-drive-token"
OTHER_FOLDER_URL = "https://otherdrive.example.test/Agent%20Barn"


@dataclass
class OtherDrivePlugin(SyncProviderPlugin):
    key = OTHER_DRIVE
    display_name = "Other Drive"
    tagline = "Sync to Other Drive"
    folder_hint = "Open the folder in Other Drive."

    signed_in_account: str = OTHER_ACCOUNT_ID
    sign_ins: list[dict] = field(default_factory=list)
    provisions: list[dict] = field(default_factory=list)
    revokes: list[dict] = field(default_factory=list)

    def authorize_url(self, *, redirect_uri: str, state: str, code_challenge: str) -> str:
        return f"https://otherdrive.example.test/authorize?state={state}"

    def complete_sign_in(self, *, code: str, code_verifier: str, redirect_uri: str) -> SignedIn:
        self.sign_ins.append({"code": code, "redirect_uri": redirect_uri})
        return SignedIn(account_id=self.signed_in_account, access_token=OTHER_TOKEN, expires_in=3600)

    def require_same_account(self, stored_account_id: str, signed_in: SignedIn) -> None:
        if stored_account_id != signed_in.account_id:
            raise SignInRefused("Sign in with the Other Drive account that connected.")

    def provision(self, token: str, *, account_id: str, location: SyncLocation | None, folder_name: str) -> Provisioned:
        self.provisions.append({"token": token, "account_id": account_id, "location": location, "folder": folder_name})
        return Provisioned(
            folder=SyncFolder(id="other-folder", web_url=OTHER_FOLDER_URL), provider_data={"grant": "g1"}
        )

    def undo_provision(self, token: str, *, location_id: str | None, provider_data: dict[str, str]) -> None:
        return None

    def revoke(self, token: str, *, location_id: str | None, provider_data: dict[str, str]) -> None:
        self.revokes.append({"token": token, "provider_data": provider_data})


class OtherDriveModule(Module):
    """Registers Other Drive after the shipped plugins, overriding AppModule's registry."""

    @provider
    @singleton
    def provide_other_drive(self) -> OtherDrivePlugin:
        return OtherDrivePlugin()

    @provider
    @singleton
    def provide_registry(
        self,
        config: Config,
        identity: MicrosoftIdentityClient,
        graph_sites: MicrosoftGraphSites,
        other_drive: OtherDrivePlugin,
    ) -> SyncProviderPluginRegistry:
        return SyncProviderPluginRegistry([*shipped_plugins(config, identity, graph_sites), other_drive])


def other_drive(context) -> OtherDrivePlugin:
    return context.injector.get(OtherDrivePlugin)
