import logging
from collections.abc import Mapping

from api.core.config import Config
from api.domains.agents.microsoft_graph_scopes import (
    GRAPH_SCOPE_PREFIX,
    READ_PERMISSION,
    SITE_GRANT_PERMISSION,
    granted_permissions,
)
from api.domains.agents.microsoft_graph_sites import (
    MicrosoftGraphSites,
    SiteAccessRefused,
    SiteNotFound,
    SitesThrottled,
    SitesUnavailable,
)
from api.domains.agents.microsoft_identity import (
    MicrosoftIdentityClient,
    MicrosoftIdentityError,
    MicrosoftIdentityUnavailable,
    build_app_permission_consent_url,
    build_authorize_url,
    claims_from_id_token,
)
from api.domains.sync_provider.models import SyncProviderCapability
from api.domains.sync_provider.plugins.base import (
    LocationAccessRefused,
    LocationNotFound,
    ProviderThrottled,
    ProviderUnavailable,
    Provisioned,
    ProvisioningFailed,
    SignedIn,
    SignInIncomplete,
    SignInRefused,
    SyncFolder,
    SyncLocation,
    SyncLocationGuard,
    SyncProviderPlugin,
)

logger = logging.getLogger(__name__)

ONEDRIVE_PROVIDER_KEY = "onedrive"
MULTI_TENANT_AUTHORITY = "organizations"
SIGN_IN_SCOPES: tuple[str, ...] = tuple(
    sorted(
        {
            f"{GRAPH_SCOPE_PREFIX}{SITE_GRANT_PERMISSION}",
            f"{GRAPH_SCOPE_PREFIX}{READ_PERMISSION}",
            "openid",
            "profile",
        }
    )
)
GRANT_DISPLAY_NAME = "Agent Barn"
GRANT_ROLE = "write"
PERMISSION_ID = "permission_id"

_REQUIRED_PERMISSIONS = frozenset({SITE_GRANT_PERMISSION, READ_PERMISSION})
_ADMIN_APPROVAL_ERROR_CODES = ("AADSTS65001", "AADSTS65004", "AADSTS90094", "AADSTS90095")

_ADMIN_APPROVAL_NEEDED = "A Microsoft Global Administrator needs to approve Agent Barn for your organization."
_SIGN_IN_REFUSED = "Microsoft refused the sign-in. Please connect again."
_SIGN_IN_WITHOUT_TENANT = "Microsoft didn't say which organization you signed in to. Sign in with a work account."
_SITE_ADMINISTRATION_MISSING = (
    "Microsoft didn't grant permission to manage SharePoint sites. Sign in as a SharePoint or Microsoft 365 "
    "administrator."
)
_UNREACHABLE = "Microsoft couldn't be reached. Please try again."
_SITE_NOT_FOUND = "Couldn't find that SharePoint site. Search again and pick it from the list."
_NOT_A_SITE_ADMINISTRATOR = "Sign in as a SharePoint administrator who is a member of this site, then try again."
_THROTTLED = "Microsoft is limiting requests right now. Wait a few minutes, then try again."
_FOLDER_FAILED = "Agent Barn couldn't create its folder on that site, so it was not connected. Please try again."
_ANOTHER_TENANT = "Sign in with an account from the Microsoft organization that connected OneDrive."
_NO_RECORDED_GRANT = "This OneDrive connection has no site grant on record."


class OneDriveSyncProviderPlugin(SyncProviderPlugin):
    """OneDrive through one SharePoint site: the platform Microsoft app is granted ``write`` on
    the chosen site with Sites.Selected, and creates its folder there as the app."""

    key = ONEDRIVE_PROVIDER_KEY
    display_name = "OneDrive"
    tagline = "Sync to a SharePoint site"
    folder_hint = "In OneDrive, choose Add shortcut to My files to keep this folder next to your own files."
    connect_hint = (
        "A Microsoft Global Administrator approves Agent Barn for your organization once, and the person "
        "connecting must be a SharePoint Administrator and a member of the site they pick."
    )
    location_noun = "SharePoint site"
    server_setup_hint = (
        "Set ONEDRIVE_SYNC_CLIENT_ID and ONEDRIVE_SYNC_CLIENT_SECRET for a multi-tenant Microsoft Entra app in "
        "the server configuration, then redeploy. See “Connecting OneDrive (manual step)” in the README."
    )
    capabilities = frozenset({SyncProviderCapability.LOCATION_PICKER, SyncProviderCapability.ADMIN_APPROVAL})
    location_guard = SyncLocationGuard.SHAREPOINT_AGENT_SITES

    def __init__(self, config: Config, identity: MicrosoftIdentityClient, graph_sites: MicrosoftGraphSites) -> None:
        self.config = config
        self.identity = identity
        self.graph_sites = graph_sites

    def is_offered(self) -> bool:
        return self.config.is_onedrive_sync_enabled

    def authorize_url(self, *, redirect_uri: str, state: str, code_challenge: str) -> str:
        return build_authorize_url(
            tenant_id=MULTI_TENANT_AUTHORITY,
            client_id=self.config.onedrive_sync_client_id,
            redirect_uri=redirect_uri,
            scopes=SIGN_IN_SCOPES,
            state=state,
            code_challenge=code_challenge,
        )

    def approval_url(self, *, redirect_uri: str) -> str:
        return build_app_permission_consent_url(
            tenant_id=MULTI_TENANT_AUTHORITY,
            client_id=self.config.onedrive_sync_client_id,
            redirect_uri=redirect_uri,
        )

    def is_approval_callback(self, query: Mapping[str, str]) -> bool:
        return (query.get("admin_consent") or "").lower() == "true"

    def callback_error_message(self, error: str, description: str) -> str:
        if error == "consent_required" or any(known in description for known in _ADMIN_APPROVAL_ERROR_CODES):
            return _ADMIN_APPROVAL_NEEDED
        return f"Microsoft sign-in was cancelled or failed ({error})."

    def complete_sign_in(self, *, code: str, code_verifier: str, redirect_uri: str) -> SignedIn:
        """The tenant is the one Microsoft names in the id_token; both site permissions must be granted."""
        try:
            tokens = self.identity.exchange_code(
                tenant_id=MULTI_TENANT_AUTHORITY,
                client_id=self.config.onedrive_sync_client_id,
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
                scopes=SIGN_IN_SCOPES,
                client_secret=self.config.onedrive_sync_client_secret,
            )
        except MicrosoftIdentityError as exc:
            logger.info("OneDrive sign-in refused by Microsoft: %s", exc.error)
            raise SignInRefused(_SIGN_IN_REFUSED) from exc
        except MicrosoftIdentityUnavailable as exc:
            raise ProviderUnavailable(_UNREACHABLE) from exc
        tenant_id = str(claims_from_id_token(tokens.id_token).get("tid") or "")
        if not tenant_id:
            raise SignInIncomplete(_SIGN_IN_WITHOUT_TENANT)
        if not _REQUIRED_PERMISSIONS <= granted_permissions(tokens.scope.split()):
            raise SignInIncomplete(_SITE_ADMINISTRATION_MISSING)
        return SignedIn(account_id=tenant_id, access_token=tokens.access_token, expires_in=tokens.expires_in)

    def require_same_account(self, stored_account_id: str, signed_in: SignedIn) -> None:
        if signed_in.account_id.lower() != stored_account_id.lower():
            raise SignInRefused(_ANOTHER_TENANT)

    def search_locations(self, token: str, query: str) -> list[SyncLocation]:
        try:
            found = self.graph_sites.search_sites(token, query)
        except SiteAccessRefused as exc:
            raise LocationAccessRefused(_SITE_ADMINISTRATION_MISSING) from exc
        except SitesThrottled as exc:
            raise ProviderThrottled(_THROTTLED) from exc
        except (SiteNotFound, SitesUnavailable) as exc:
            raise ProviderUnavailable(_UNREACHABLE) from exc
        return [SyncLocation(id=site.id, name=site.name, web_url=site.web_url) for site in found]

    def resolve_location(self, token: str, location_id: str) -> SyncLocation:
        try:
            site = self.graph_sites.get_site(token, location_id)
        except SiteNotFound as exc:
            raise LocationNotFound(_SITE_NOT_FOUND) from exc
        except SiteAccessRefused as exc:
            raise LocationAccessRefused(_NOT_A_SITE_ADMINISTRATOR) from exc
        except SitesThrottled as exc:
            raise ProviderThrottled(_THROTTLED) from exc
        except SitesUnavailable as exc:
            raise ProviderUnavailable(_UNREACHABLE) from exc
        return SyncLocation(id=site.id, name=site.name, web_url=site.web_url)

    def provision(self, token: str, *, account_id: str, location: SyncLocation | None, folder_name: str) -> Provisioned:
        """Grant the platform app write on the site, then create the folder as the app. A folder
        failure takes the grant back, so the site is never left granted to nothing."""
        if location is None:
            raise LocationNotFound(_SITE_NOT_FOUND)
        try:
            permission_id = self.graph_sites.grant_site(
                token,
                site_id=location.id,
                app_id=self.config.onedrive_sync_client_id,
                display_name=GRANT_DISPLAY_NAME,
                role=GRANT_ROLE,
            )
        except SiteNotFound as exc:
            raise LocationNotFound(_SITE_NOT_FOUND) from exc
        except SiteAccessRefused as exc:
            raise LocationAccessRefused(_NOT_A_SITE_ADMINISTRATOR) from exc
        except SitesThrottled as exc:
            raise ProviderThrottled(_THROTTLED) from exc
        except SitesUnavailable as exc:
            raise ProviderUnavailable(_UNREACHABLE) from exc
        provider_data = {PERMISSION_ID: permission_id}
        try:
            app_tokens = self.identity.client_credentials(
                tenant_id=account_id,
                client_id=self.config.onedrive_sync_client_id,
                client_secret=self.config.onedrive_sync_client_secret,
            )
            folder = self.graph_sites.ensure_folder(app_tokens.access_token, site_id=location.id, name=folder_name)
        except (
            MicrosoftIdentityError,
            MicrosoftIdentityUnavailable,
            SiteAccessRefused,
            SiteNotFound,
            SitesUnavailable,
        ) as exc:
            logger.warning("OneDrive folder setup failed on %s: %s", location.id, type(exc).__name__)
            self.undo_provision(token, location_id=location.id, provider_data=provider_data)
            raise ProvisioningFailed(_FOLDER_FAILED) from exc
        return Provisioned(folder=SyncFolder(id=folder.item_id, web_url=folder.web_url), provider_data=provider_data)

    def undo_provision(self, token: str, *, location_id: str | None, provider_data: dict[str, str]) -> None:
        permission_id = provider_data.get(PERMISSION_ID)
        if location_id is None or permission_id is None:
            return
        try:
            self.graph_sites.revoke_site(token, site_id=location_id, permission_id=permission_id)
        except SiteAccessRefused, SitesUnavailable:
            logger.warning("OneDrive could not take back site grant %s on %s", permission_id, location_id)

    def revoke(self, token: str, *, location_id: str | None, provider_data: dict[str, str]) -> None:
        """An app granted only ``write`` cannot remove its own grant, so this uses the
        administrator's fresh delegated token."""
        permission_id = provider_data.get(PERMISSION_ID)
        if location_id is None or permission_id is None:
            raise LocationNotFound(_NO_RECORDED_GRANT)
        try:
            self.graph_sites.revoke_site(token, site_id=location_id, permission_id=permission_id)
        except SiteAccessRefused as exc:
            raise LocationAccessRefused(_NOT_A_SITE_ADMINISTRATOR) from exc
        except SitesThrottled as exc:
            raise ProviderThrottled(_THROTTLED) from exc
        except SitesUnavailable as exc:
            raise ProviderUnavailable(_UNREACHABLE) from exc
