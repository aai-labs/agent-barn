"""Contract tests for the Sync Provider Plugin registry, and the OneDrive plugin's Microsoft behaviour.

One parametrized sweep over every shipped plugin, so a new provider cannot be added half-way.
"""

import urllib.parse
from datetime import UTC, datetime

import httpx
import pytest
from hamcrest import assert_that, contains_string, empty, equal_to, has_entries, is_, starts_with

from api.core.config import Config
from api.domains.agents.microsoft_graph_files import MicrosoftGraphFiles
from api.domains.agents.microsoft_graph_sites import SiteAccessRefused, SitesThrottled, SitesUnavailable
from api.domains.agents.microsoft_identity import (
    MicrosoftAppTokens,
    MicrosoftIdentityError,
    MicrosoftIdentityUnavailable,
)
from api.domains.sync_provider.models import SyncProviderCapability
from api.domains.sync_provider.plugins.base import (
    LocationAccessRefused,
    LocationNotFound,
    ProviderThrottled,
    ProviderUnavailable,
    Provisioned,
    ProvisioningFailed,
    RemoteChangeRejected,
    RemoteChanges,
    RemoteItem,
    RemoteItemMissing,
    RemoteNameTaken,
    RemoteResyncRequired,
    SignedIn,
    SignInIncomplete,
    SignInRefused,
    SyncFolder,
    SyncLocation,
    SyncLocationGuard,
    SyncProviderError,
    SyncProviderPlugin,
    SyncRoot,
    UploadTarget,
)
from api.domains.sync_provider.plugins.onedrive import OneDriveSyncProviderPlugin
from api.domains.sync_provider.plugins.providers import shipped_plugins
from api.domains.sync_provider.plugins.registry import CAPABILITY_METHODS, SyncProviderPluginRegistry
from api.tests.steps.sharepoint import (
    FOLDER_WEB_URL,
    TEAMS_TENANT_ID,
    FakeMicrosoftGraphSites,
    FakeMicrosoftIdentity,
    app_tokens,
    tokens,
)

CLIENT_ID = "00000000-0000-0000-0000-000000000001"
CLIENT_SECRET = "onedrive-client-secret"
WEB_APP_URL = "https://app.example.test"
REDIRECT_URI = f"{WEB_APP_URL}/api/v1/integrations/sync-provider/onedrive/callback"
SIGN_IN_SCOPE = "https://graph.microsoft.com/Sites.FullControl.All https://graph.microsoft.com/Sites.Read.All"
SITE_ID = "contoso.sharepoint.com,aaa,bbb"
ADMIN_APPROVAL_NEEDED = "A Microsoft Global Administrator needs to approve Agent Barn for your organization."


def _config(*, configured: bool = True) -> Config:
    return Config(
        db_connection_url="postgresql://user:pass@localhost:5432/db",
        secret_signing_key="signing-key",
        platform_admin_credentials="admin@example.com:StrongPass123",
        web_app_url=WEB_APP_URL,
        onedrive_sync_client_id=CLIENT_ID if configured else "",
        onedrive_sync_client_secret=CLIENT_SECRET if configured else "",
        _env_file=None,
    )


def _onedrive(
    *, configured: bool = True
) -> tuple[OneDriveSyncProviderPlugin, FakeMicrosoftIdentity, FakeMicrosoftGraphSites]:
    identity = FakeMicrosoftIdentity()
    graph_sites = FakeMicrosoftGraphSites()
    plugin = OneDriveSyncProviderPlugin(
        _config(configured=configured), identity, graph_sites, MicrosoftGraphFiles(), MicrosoftAppTokens(identity)
    )
    return plugin, identity, graph_sites


_SHIPPED_IDENTITY = FakeMicrosoftIdentity()
SHIPPED = shipped_plugins(
    _config(),
    _SHIPPED_IDENTITY,
    FakeMicrosoftGraphSites(),
    MicrosoftGraphFiles(),
    MicrosoftAppTokens(_SHIPPED_IDENTITY),
)


def _ids(plugins):
    return [plugin.key for plugin in plugins]


# --- shipped catalogue ---


def test_the_shipped_catalogue_is_accepted_by_the_registry():
    registry = SyncProviderPluginRegistry(SHIPPED)

    assert_that(_ids(registry.offered()), is_(equal_to(["onedrive"])))


@pytest.mark.parametrize("plugin", SHIPPED, ids=_ids(SHIPPED))
def test_plugin_describes_itself_for_the_settings_list(plugin: SyncProviderPlugin):
    descriptor = plugin.descriptor

    assert_that(descriptor.key, is_(equal_to(plugin.key)))
    assert_that(descriptor.display_name, is_(equal_to(plugin.display_name)))
    assert_that(bool(descriptor.tagline.strip()), is_(True))
    assert_that(bool(descriptor.folder_hint.strip()), is_(True))
    assert_that(descriptor.capabilities, is_(equal_to(sorted(plugin.capabilities, key=lambda item: item.value))))


@pytest.mark.parametrize("plugin", SHIPPED, ids=_ids(SHIPPED))
def test_plugin_declares_only_a_known_location_guard(plugin: SyncProviderPlugin):
    assert_that(plugin.location_guard is None or isinstance(plugin.location_guard, SyncLocationGuard), is_(True))


# --- registry validation ---


class _Stub(SyncProviderPlugin):
    key = "stub"
    display_name = "Stub"
    tagline = "Sync to a stub"
    folder_hint = "Open the stub folder."

    def authorize_url(self, *, redirect_uri: str, state: str, code_challenge: str) -> str:
        return "https://stub.example.test/authorize"

    def complete_sign_in(self, *, code: str, code_verifier: str, redirect_uri: str) -> SignedIn:
        return SignedIn(account_id="account", access_token="token", expires_in=3600)

    def require_same_account(self, stored_account_id: str, signed_in: SignedIn) -> None:
        return None

    def provision(self, token: str, *, account_id: str, location: SyncLocation | None, folder_name: str) -> Provisioned:
        return Provisioned(folder=SyncFolder(id="folder", web_url="https://stub.example.test/folder"), provider_data={})

    def undo_provision(self, token: str, *, location_id: str | None, provider_data: dict[str, str]) -> None:
        return None

    def revoke(self, token: str, *, location_id: str | None, provider_data: dict[str, str]) -> None:
        return None


def _stub(**attrs) -> SyncProviderPlugin:
    return type("_Variant", (_Stub,), attrs)()


def _registry_error(*plugins: SyncProviderPlugin) -> str:
    with pytest.raises(ValueError) as exc:
        SyncProviderPluginRegistry(plugins)
    return str(exc.value)


def test_registry_rejects_a_non_canonical_key():
    assert_that(_registry_error(_stub(key="Stub")), contains_string("canonical lowercase"))


def test_registry_rejects_duplicate_keys():
    assert_that(_registry_error(_stub(), _stub()), contains_string("Duplicate Sync Provider Plugin key: stub"))


def test_registry_rejects_a_non_positive_schema_version():
    assert_that(_registry_error(_stub(schema_version=0)), contains_string("schema version must be positive"))


def test_registry_rejects_a_location_picker_without_location_search():
    message = _registry_error(_stub(capabilities=frozenset({SyncProviderCapability.LOCATION_PICKER})))

    assert_that(message, contains_string("never overrides search_locations"))


def test_registry_rejects_a_location_picker_without_a_location_noun():
    class _Picker(_Stub):
        capabilities = frozenset({SyncProviderCapability.LOCATION_PICKER})

        def search_locations(self, token: str, query: str) -> list[SyncLocation]:
            return []

        def resolve_location(self, token: str, location_id: str) -> SyncLocation:
            return SyncLocation(id=location_id, name="n", web_url="u")

    assert_that(_registry_error(_Picker()), contains_string("names no location_noun"))


def test_registry_rejects_admin_approval_without_an_approval_link():
    message = _registry_error(_stub(capabilities=frozenset({SyncProviderCapability.ADMIN_APPROVAL})))

    assert_that(message, contains_string("never overrides approval_url"))


def test_registry_rejects_an_unknown_location_guard():
    assert_that(_registry_error(_stub(location_guard="sharepoint_agent_sites")), contains_string("location guard"))


_FILE_SYNC_METHODS = (
    "create_folder",
    "get_item",
    "get_item_by_path",
    "move_item",
    "delete_item",
    "delete_item_with",
    "changes",
    "list_files",
    "upload_target",
    "download_url",
    "write_empty_file",
)
_ROOT = SyncRoot(account_id="tenant-1", location_id=SITE_ID, folder_id="barn-1", folder_name="Agent Barn")
_ITEM = RemoteItem(
    id="item-1",
    name="notes.md",
    parent_id="folder-1",
    path="Sales Bot/workspace/notes.md",
    version='"{A},2"',
    content_version='"c:{A},2"',
    size=22,
    content_hash="aSxzM1vs4ODedgYgJoMc3tAGEIQ=",
    is_folder=False,
    deleted=False,
    modified_at=None,
    modified_by_app=False,
    web_url=None,
)


class _FileSync(_Stub):
    capabilities = frozenset({SyncProviderCapability.FILE_SYNC})

    def create_folder(self, root: SyncRoot, *, parent_id: str, name: str) -> RemoteItem:
        return _ITEM

    def get_item(self, root: SyncRoot, *, item_id: str) -> RemoteItem:
        return _ITEM

    def get_item_by_path(self, root: SyncRoot, *, parent_id: str, rel_path: str) -> RemoteItem:
        return _ITEM

    def move_item(
        self, root: SyncRoot, *, item_id: str, name: str | None = None, parent_id: str | None = None
    ) -> RemoteItem:
        return _ITEM

    def delete_item(self, root: SyncRoot, *, item_id: str) -> None:
        return None

    def delete_item_with(self, token: str, root: SyncRoot, *, item_id: str) -> None:
        return None

    def changes(self, root: SyncRoot, cursor: str | None, *, from_start: bool = False) -> RemoteChanges:
        return RemoteChanges(items=[], cursor="next", more=False)

    def list_files(self, root: SyncRoot, *, folder_id: str) -> list[RemoteItem]:
        return [_ITEM]

    def upload_target(self, root: SyncRoot, *, parent_id: str, rel_path: str) -> UploadTarget:
        return UploadTarget(url="https://stub.example.test/upload", expires_at=datetime(2026, 10, 22, tzinfo=UTC))

    def download_url(self, root: SyncRoot, *, item_id: str) -> str:
        return "https://stub.example.test/download"

    def write_empty_file(self, root: SyncRoot, *, parent_id: str, rel_path: str) -> RemoteItem:
        return _ITEM


def test_file_sync_names_every_method_the_engine_and_pod_routes_call():
    assert_that(CAPABILITY_METHODS[SyncProviderCapability.FILE_SYNC], equal_to(_FILE_SYNC_METHODS))


def test_registry_accepts_file_sync_when_every_method_is_implemented():
    registry = SyncProviderPluginRegistry([_FileSync()])

    assert_that(registry.require("stub").capabilities, equal_to(frozenset({SyncProviderCapability.FILE_SYNC})))


@pytest.mark.parametrize("missing", _FILE_SYNC_METHODS)
def test_registry_rejects_file_sync_missing_any_method(missing: str):
    partial = type("_Partial", (_FileSync,), {missing: getattr(SyncProviderPlugin, missing)})()

    assert_that(_registry_error(partial), contains_string(f"declares file_sync but never overrides {missing}"))


def test_a_plugin_without_file_sync_refuses_file_calls():
    with pytest.raises(NotImplementedError, match="stub has no file sync"):
        _stub().get_item(_ROOT, item_id="item-1")


def test_throttling_can_carry_the_providers_requested_wait():
    assert_that(ProviderThrottled("busy").retry_after, equal_to(None))
    assert_that(ProviderThrottled("busy", retry_after=120).retry_after, equal_to(120))
    assert_that(ProviderThrottled("busy", retry_after=120).message, equal_to("busy"))


def test_file_sync_failures_are_provider_errors():
    for error in (RemoteItemMissing, RemoteNameTaken, RemoteChangeRejected, RemoteResyncRequired):
        assert_that(issubclass(error, SyncProviderError), is_(True))


def test_require_names_an_unknown_provider():
    registry = SyncProviderPluginRegistry([_stub()])

    assert_that(registry.require("stub").key, is_(equal_to("stub")))
    with pytest.raises(KeyError, match="Unsupported sync provider: dropbox"):
        registry.require("dropbox")


def test_registry_offers_only_configured_providers_in_key_order():
    hidden = _stub(key="hidden", is_offered=lambda self: False)
    registry = SyncProviderPluginRegistry([_stub(key="zeta"), hidden, _stub(key="alpha")])

    assert_that(_ids(registry.offered()), is_(equal_to(["alpha", "zeta"])))
    assert_that([descriptor.key for descriptor in registry.descriptors()], is_(equal_to(["alpha", "zeta"])))
    assert_that(registry.require("hidden").key, is_(equal_to("hidden")))
    assert_that(_ids(registry.all()), is_(equal_to(["alpha", "hidden", "zeta"])))


# --- OneDrive: offering and links ---


def test_onedrive_is_offered_only_when_its_microsoft_app_is_configured():
    assert_that(_onedrive()[0].is_offered(), is_(True))
    assert_that(_onedrive(configured=False)[0].is_offered(), is_(False))


def test_onedrive_declares_the_picker_the_approval_link_file_sync_and_the_sharepoint_guard():
    plugin = _onedrive()[0]

    assert_that(
        plugin.capabilities,
        is_(
            equal_to(
                frozenset(
                    {
                        SyncProviderCapability.LOCATION_PICKER,
                        SyncProviderCapability.ADMIN_APPROVAL,
                        SyncProviderCapability.FILE_SYNC,
                    }
                )
            )
        ),
    )
    assert_that(plugin.location_guard, is_(SyncLocationGuard.SHAREPOINT_AGENT_SITES))
    assert_that(plugin.descriptor.tagline, is_(equal_to("Sync to a SharePoint site")))
    assert_that(plugin.descriptor.folder_hint, contains_string("Add shortcut to My files"))
    assert_that(plugin.descriptor.location_noun, is_(equal_to("SharePoint site")))
    connect_hint = plugin.descriptor.connect_hint
    assert connect_hint is not None
    assert_that(connect_hint, contains_string("Microsoft Global Administrator"))
    assert_that(connect_hint, contains_string("SharePoint Administrator"))


def test_onedrive_signs_in_at_any_work_organization_with_the_site_scopes():
    url = _onedrive()[0].authorize_url(redirect_uri=REDIRECT_URI, state="the-state", code_challenge="the-challenge")

    assert_that(url, starts_with("https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize?"))
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    assert_that(
        query,
        has_entries(
            client_id=CLIENT_ID,
            redirect_uri=REDIRECT_URI,
            scope="https://graph.microsoft.com/Sites.FullControl.All https://graph.microsoft.com/Sites.Read.All "
            "openid profile",
            prompt="select_account",
            state="the-state",
            code_challenge="the-challenge",
            code_challenge_method="S256",
        ),
    )


def test_onedrive_approval_link_asks_any_organization_for_the_app_permissions_without_state():
    url = _onedrive()[0].approval_url(redirect_uri=REDIRECT_URI)

    assert_that(url, starts_with("https://login.microsoftonline.com/organizations/v2.0/adminconsent?"))
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    assert_that(
        query,
        is_(
            equal_to(
                {"client_id": CLIENT_ID, "scope": "https://graph.microsoft.com/.default", "redirect_uri": REDIRECT_URI}
            )
        ),
    )


def test_onedrive_recognises_microsofts_approval_redirect():
    plugin = _onedrive()[0]

    assert_that(plugin.is_approval_callback({"admin_consent": "True", "tenant": "ignored"}), is_(True))
    assert_that(plugin.is_approval_callback({"code": "the-code", "state": "the-state"}), is_(False))


@pytest.mark.parametrize(
    ("error", "description"),
    [
        ("consent_required", ""),
        ("access_denied", "AADSTS65001: The user or administrator has not consented"),
        ("access_denied", "AADSTS65004: User declined to consent"),
        ("invalid_request", "AADSTS90094: The grant requires admin permission."),
        ("invalid_request", "AADSTS90095: Admin consent is required"),
    ],
)
def test_onedrive_explains_who_must_approve_when_microsoft_asks_for_an_administrator(error, description):
    assert_that(_onedrive()[0].callback_error_message(error, description), is_(equal_to(ADMIN_APPROVAL_NEEDED)))


def test_onedrive_names_any_other_microsoft_error():
    message = _onedrive()[0].callback_error_message("access_denied", "The user cancelled")

    assert_that(message, is_(equal_to("Microsoft sign-in was cancelled or failed (access_denied).")))


# --- OneDrive: sign-in ---


def test_onedrive_redeems_the_code_as_the_platform_app_and_names_the_tenant_from_the_id_token():
    plugin, identity, _ = _onedrive()
    identity.exchange_result = tokens(scope=SIGN_IN_SCOPE)

    signed_in = plugin.complete_sign_in(code="the-code", code_verifier="the-verifier", redirect_uri=REDIRECT_URI)

    assert_that(
        signed_in, is_(equal_to(SignedIn(account_id=TEAMS_TENANT_ID, access_token="at-from-exchange", expires_in=3600)))
    )
    assert_that(
        identity.exchanges,
        is_(
            equal_to(
                [
                    {
                        "tenant_id": "organizations",
                        "client_id": CLIENT_ID,
                        "code": "the-code",
                        "redirect_uri": REDIRECT_URI,
                        "code_verifier": "the-verifier",
                        "scopes": (
                            "https://graph.microsoft.com/Sites.FullControl.All",
                            "https://graph.microsoft.com/Sites.Read.All",
                            "openid",
                            "profile",
                        ),
                        "client_secret": CLIENT_SECRET,
                    }
                ]
            )
        ),
    )


def test_onedrive_refused_sign_in_is_a_sign_in_failure():
    plugin, identity, _ = _onedrive()
    identity.exchange_result = MicrosoftIdentityError("invalid_grant", "AADSTS70008: expired")

    with pytest.raises(SignInRefused, match="Microsoft refused the sign-in. Please connect again."):
        plugin.complete_sign_in(code="the-code", code_verifier="v", redirect_uri=REDIRECT_URI)


def test_onedrive_unreachable_microsoft_is_reported_as_unavailable():
    plugin, identity, _ = _onedrive()
    identity.exchange_result = MicrosoftIdentityUnavailable("timeout")

    with pytest.raises(ProviderUnavailable, match="Microsoft couldn't be reached"):
        plugin.complete_sign_in(code="the-code", code_verifier="v", redirect_uri=REDIRECT_URI)


def test_onedrive_sign_in_without_a_tenant_is_incomplete():
    plugin, identity, _ = _onedrive()
    identity.exchange_result = tokens(scope=SIGN_IN_SCOPE, tenant_id="")

    with pytest.raises(SignInIncomplete, match="Sign in with a work account"):
        plugin.complete_sign_in(code="the-code", code_verifier="v", redirect_uri=REDIRECT_URI)


@pytest.mark.parametrize(
    "scope",
    ["https://graph.microsoft.com/Sites.Read.All", "https://graph.microsoft.com/Sites.FullControl.All"],
)
def test_onedrive_sign_in_missing_a_site_permission_is_incomplete(scope):
    plugin, identity, _ = _onedrive()
    identity.exchange_result = tokens(scope=scope)

    with pytest.raises(SignInIncomplete, match="permission to manage SharePoint sites"):
        plugin.complete_sign_in(code="the-code", code_verifier="v", redirect_uri=REDIRECT_URI)


def test_onedrive_accepts_the_same_tenant_in_any_case():
    signed_in = SignedIn(account_id=TEAMS_TENANT_ID.upper(), access_token="t", expires_in=3600)

    _onedrive()[0].require_same_account(TEAMS_TENANT_ID, signed_in)


def test_onedrive_refuses_another_tenant():
    signed_in = SignedIn(account_id="33333333-3333-4333-8333-333333333333", access_token="t", expires_in=3600)

    with pytest.raises(SignInRefused, match="Microsoft organization that connected OneDrive"):
        _onedrive()[0].require_same_account(TEAMS_TENANT_ID, signed_in)


# --- OneDrive: locations ---


def test_onedrive_searches_sharepoint_sites_with_the_administrators_token():
    plugin, _, graph_sites = _onedrive()
    graph_sites.search_results = [graph_sites.get_site("t", SITE_ID)]

    found = plugin.search_locations("admin-token", "Agent Barn")

    assert_that(
        found,
        is_(
            equal_to(
                [
                    SyncLocation(
                        id=SITE_ID, name="Agent Barn Test", web_url="https://contoso.sharepoint.com/sites/AgentBarnTest"
                    )
                ]
            )
        ),
    )
    assert_that(graph_sites.searches, is_(equal_to([{"token": "admin-token", "query": "Agent Barn"}])))


@pytest.mark.parametrize(
    ("failure", "expected", "message"),
    [
        (SiteAccessRefused("no"), LocationAccessRefused, "permission to manage SharePoint sites"),
        (SitesThrottled("slow down"), ProviderThrottled, "limiting requests"),
        (SitesUnavailable("down"), ProviderUnavailable, "Microsoft couldn't be reached"),
    ],
)
def test_onedrive_search_failures_are_typed(failure, expected, message):
    plugin, _, graph_sites = _onedrive()
    graph_sites.search_failure = failure

    with pytest.raises(expected, match=message):
        plugin.search_locations("admin-token", "Agent Barn")


def test_onedrive_reads_the_chosen_site_from_microsoft():
    location = _onedrive()[0].resolve_location("admin-token", SITE_ID)

    assert_that(location.name, is_(equal_to("Agent Barn Test")))
    assert_that(location.web_url, is_(equal_to("https://contoso.sharepoint.com/sites/AgentBarnTest")))


def test_onedrive_unknown_site_is_not_found():
    plugin, _, graph_sites = _onedrive()
    graph_sites.unknown_sites.add(SITE_ID)

    with pytest.raises(LocationNotFound, match="Couldn't find that SharePoint site"):
        plugin.resolve_location("admin-token", SITE_ID)


# --- OneDrive: provisioning ---


def _site() -> SyncLocation:
    return SyncLocation(
        id=SITE_ID, name="Agent Barn Test", web_url="https://contoso.sharepoint.com/sites/AgentBarnTest"
    )


def test_onedrive_grants_the_platform_app_write_on_the_site_and_creates_the_folder_as_the_app():
    plugin, identity, graph_sites = _onedrive()

    provisioned = plugin.provision(
        "admin-token", account_id=TEAMS_TENANT_ID, location=_site(), folder_name="Agent Barn"
    )

    assert_that(
        graph_sites.grants,
        is_(
            equal_to(
                [
                    {
                        "token": "admin-token",
                        "site_id": SITE_ID,
                        "app_id": CLIENT_ID,
                        "role": "write",
                        "display_name": "Agent Barn",
                    }
                ]
            )
        ),
    )
    assert_that(
        identity.app_token_requests,
        is_(equal_to([{"tenant_id": TEAMS_TENANT_ID, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}])),
    )
    assert_that(
        graph_sites.folders, is_(equal_to([{"token": "app-only-token", "site_id": SITE_ID, "name": "Agent Barn"}]))
    )
    assert_that(
        provisioned,
        is_(
            equal_to(
                Provisioned(
                    folder=SyncFolder(id="folder-item-1", web_url=FOLDER_WEB_URL),
                    provider_data={"permission_id": "perm-1"},
                )
            )
        ),
    )


def test_onedrive_needs_a_site():
    with pytest.raises(LocationNotFound):
        _onedrive()[0].provision("admin-token", account_id=TEAMS_TENANT_ID, location=None, folder_name="Agent Barn")


@pytest.mark.parametrize(
    ("failure", "expected", "message"),
    [
        (SiteAccessRefused("no"), LocationAccessRefused, "SharePoint administrator who is a member of this site"),
        (SitesThrottled("slow down"), ProviderThrottled, "limiting requests"),
        (SitesUnavailable("down"), ProviderUnavailable, "Microsoft couldn't be reached"),
    ],
)
def test_onedrive_grant_failures_are_typed_and_leave_nothing_to_undo(failure, expected, message):
    plugin, identity, graph_sites = _onedrive()
    graph_sites.grant_failures[SITE_ID] = failure

    with pytest.raises(expected, match=message):
        plugin.provision("admin-token", account_id=TEAMS_TENANT_ID, location=_site(), folder_name="Agent Barn")

    assert_that(identity.app_token_requests, is_(empty()))
    assert_that(graph_sites.revokes, is_(empty()))


@pytest.mark.parametrize(
    "failure_point",
    ["app_token_refused", "app_token_unreachable", "folder_refused", "folder_unavailable"],
)
def test_onedrive_takes_its_grant_back_when_the_folder_cannot_be_made(failure_point):
    plugin, identity, graph_sites = _onedrive()
    if failure_point == "app_token_refused":
        identity.app_token_result = MicrosoftIdentityError("unauthorized_client")
    elif failure_point == "app_token_unreachable":
        identity.app_token_result = MicrosoftIdentityUnavailable("timeout")
    elif failure_point == "folder_refused":
        graph_sites.folder_failure = SiteAccessRefused("no")
    else:
        graph_sites.folder_failure = SitesUnavailable("down")

    with pytest.raises(ProvisioningFailed, match="couldn't create its folder"):
        plugin.provision("admin-token", account_id=TEAMS_TENANT_ID, location=_site(), folder_name="Agent Barn")

    assert_that(
        graph_sites.revokes,
        is_(equal_to([{"token": "admin-token", "site_id": SITE_ID, "permission_id": "perm-1"}])),
    )


def test_onedrive_a_failed_rollback_still_reports_the_folder_failure():
    plugin, _, graph_sites = _onedrive()
    graph_sites.folder_failure = SitesUnavailable("down")
    graph_sites.revoke_failures[SITE_ID] = SitesUnavailable("still down")

    with pytest.raises(ProvisioningFailed):
        plugin.provision("admin-token", account_id=TEAMS_TENANT_ID, location=_site(), folder_name="Agent Barn")


def test_onedrive_undoes_a_provisioning_quietly():
    plugin, _, graph_sites = _onedrive()
    graph_sites.revoke_failures[SITE_ID] = SiteAccessRefused("no")

    plugin.undo_provision("admin-token", location_id=SITE_ID, provider_data={"permission_id": "perm-1"})

    graph_sites.revoke_failures.clear()
    plugin.undo_provision("admin-token", location_id=SITE_ID, provider_data={"permission_id": "perm-1"})
    assert_that(
        graph_sites.revokes,
        is_(equal_to([{"token": "admin-token", "site_id": SITE_ID, "permission_id": "perm-1"}])),
    )


# --- OneDrive: disconnect ---


def test_onedrive_revokes_the_stored_grant_with_the_administrators_fresh_token():
    plugin, _, graph_sites = _onedrive()

    plugin.revoke("fresh-token", location_id=SITE_ID, provider_data={"permission_id": "perm-7"})

    assert_that(
        graph_sites.revokes,
        is_(equal_to([{"token": "fresh-token", "site_id": SITE_ID, "permission_id": "perm-7"}])),
    )


@pytest.mark.parametrize(
    ("failure", "expected", "message"),
    [
        (SiteAccessRefused("no"), LocationAccessRefused, "SharePoint administrator who is a member of this site"),
        (SitesThrottled("slow down"), ProviderThrottled, "limiting requests"),
        (SitesUnavailable("down"), ProviderUnavailable, "Microsoft couldn't be reached"),
    ],
)
def test_onedrive_revoke_failures_are_typed(failure, expected, message):
    plugin, _, graph_sites = _onedrive()
    graph_sites.revoke_failures[SITE_ID] = failure

    with pytest.raises(expected, match=message):
        plugin.revoke("fresh-token", location_id=SITE_ID, provider_data={"permission_id": "perm-7"})


def test_onedrive_revoke_without_a_recorded_grant_is_refused_before_calling_microsoft():
    plugin, _, graph_sites = _onedrive()

    with pytest.raises(LocationNotFound):
        plugin.revoke("fresh-token", location_id=SITE_ID, provider_data={})

    assert_that(graph_sites.revokes, is_(empty()))


def test_the_onedrive_plugin_never_sees_the_app_token_as_a_secret_it_returns():
    plugin, identity, _ = _onedrive()
    identity.app_token_result = app_tokens(access_token="app-only-token")

    provisioned = plugin.provision(
        "admin-token", account_id=TEAMS_TENANT_ID, location=_site(), folder_name="Agent Barn"
    )

    assert_that("app-only-token" in str(provisioned), is_(False))
    assert_that(CLIENT_SECRET in str(provisioned), is_(False))


# --- OneDrive file sync ---

_GRAPH_DRIVE = f"https://graph.microsoft.com/v1.0/sites/{SITE_ID}/drive"
_BARN_ID = "01F65KC4PUTIGIFLJ4WBGZHXW6AHK22MPR"
_SYNC_ROOT = SyncRoot(account_id=TEAMS_TENANT_ID, location_id=SITE_ID, folder_id=_BARN_ID, folder_name="Agent Barn")


def _graph_item(name: str, parent_path: str | None, **extra) -> dict:
    parent: dict = {"id": "parent-1"}
    if parent_path is not None:
        parent["path"] = parent_path
    return {
        "id": f"id-{name}",
        "name": name,
        "eTag": '"{A},5"',
        "cTag": '"c:{A},3"',
        "size": 22,
        "lastModifiedDateTime": "2026-10-21T08:39:12Z",
        "lastModifiedBy": {"user": {"displayName": "Dominykas"}},
        "parentReference": parent,
        "file": {"hashes": {"quickXorHash": "aSxzM1vs4ODedgYgJoMc3tAGEIQ="}},
        **extra,
    }


class _GraphRecorder:
    def __init__(self, *responses: httpx.Response | Exception):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, method, url, headers=None, json=None, content=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "json": json, "content": content})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def graph(monkeypatch):
    def install(*responses):
        recorder = _GraphRecorder(*responses)
        monkeypatch.setattr(httpx, "request", recorder)
        return recorder

    return install


def test_onedrive_file_calls_act_as_the_platform_app_in_the_connections_tenant(graph):
    item = _graph_item("notes.md", "/drives/b!x/root:/Agent Barn/Sales Bot/workspace")
    recorder = graph(httpx.Response(200, json=item), httpx.Response(200, json=item))
    plugin, identity, _ = _onedrive()
    identity.app_token_result = app_tokens(access_token="app-only-token")

    plugin.get_item(_SYNC_ROOT, item_id="id-notes.md")
    plugin.get_item(_SYNC_ROOT, item_id="id-notes.md")

    assert_that(
        identity.app_token_requests,
        equal_to([{"tenant_id": TEAMS_TENANT_ID, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}]),
    )
    assert_that(
        [call["headers"] for call in recorder.calls], equal_to([{"Authorization": "Bearer app-only-token"}] * 2)
    )
    assert_that(recorder.calls[0]["url"], equal_to(f"{_GRAPH_DRIVE}/items/id-notes.md"))


def test_onedrive_items_carry_their_path_inside_agent_barn(graph):
    graph(httpx.Response(200, json=_graph_item("notes.md", "/drives/b!x/root:/Agent Barn/Sales Bot/workspace")))

    item = _onedrive()[0].get_item(_SYNC_ROOT, item_id="id-notes.md")

    assert_that(
        item,
        equal_to(
            RemoteItem(
                id="id-notes.md",
                name="notes.md",
                parent_id="parent-1",
                path="Sales Bot/workspace/notes.md",
                version='"{A},5"',
                content_version='"c:{A},3"',
                size=22,
                content_hash="aSxzM1vs4ODedgYgJoMc3tAGEIQ=",
                is_folder=False,
                deleted=False,
                modified_at=datetime(2026, 10, 21, 8, 39, 12, tzinfo=UTC),
                modified_by_app=False,
                web_url=None,
            )
        ),
    )


@pytest.mark.parametrize(
    ("name", "parent_path", "expected"),
    [
        ("Sales Bot", "/drives/b!x/root:/Agent Barn", "Sales Bot"),
        ("Q3 #1.md", "/drives/b!x/root:/agent barn/Sales Bot", "Sales Bot/Q3 #1.md"),
        ("Agent Barn", "/drives/b!x/root:", None),
        ("Agent Barnyard", "/drives/b!x/root:", None),
        ("other.md", "/drives/b!x/root:/Agent Barnyard", None),
        ("other.md", "/drives/b!x/root:/Finance", None),
        ("orphan.md", None, None),
    ],
)
def test_onedrive_items_outside_agent_barn_have_no_path(graph, name, parent_path, expected):
    graph(httpx.Response(200, json=_graph_item(name, parent_path)))

    assert_that(_onedrive()[0].get_item(_SYNC_ROOT, item_id="x").path, equal_to(expected))


def test_onedrive_a_deleted_item_has_no_path(graph):
    graph(httpx.Response(200, json={"id": "gone", "parentReference": {"id": "p"}, "deleted": {"state": "deleted"}}))

    item = _onedrive()[0].get_item(_SYNC_ROOT, item_id="gone")

    assert_that((item.deleted, item.path, item.name), equal_to((True, None, None)))


def test_onedrive_changes_start_from_now_on_the_agent_barn_folder(graph):
    delta_link = "https://graph.microsoft.com/v1.0/drives/b!x/items/barn/delta?token=next"
    recorder = graph(httpx.Response(200, json={"value": [], "@odata.deltaLink": delta_link}))

    changes = _onedrive()[0].changes(_SYNC_ROOT, None)

    assert_that(recorder.calls[0]["url"], equal_to(f"{_GRAPH_DRIVE}/items/{_BARN_ID}/delta?token=latest"))
    assert_that(changes, equal_to(RemoteChanges(items=[], cursor=delta_link, more=False)))


def test_onedrive_changes_can_list_everything_under_agent_barn(graph):
    recorder = graph(httpx.Response(200, json={"value": [], "@odata.deltaLink": "https://g/next"}))

    _onedrive()[0].changes(_SYNC_ROOT, None, from_start=True)

    assert_that(recorder.calls[0]["url"], equal_to(f"{_GRAPH_DRIVE}/items/{_BARN_ID}/delta"))


def test_onedrive_changes_continue_from_the_stored_cursor_and_say_when_more_is_waiting(graph):
    next_link = "https://graph.microsoft.com/v1.0/drives/b!x/items/barn/delta?token=page2"
    item = _graph_item("notes.md", "/drives/b!x/root:/Agent Barn/Sales Bot/workspace")
    recorder = graph(httpx.Response(200, json={"value": [item], "@odata.nextLink": next_link}))

    changes = _onedrive()[0].changes(_SYNC_ROOT, "https://graph.microsoft.com/v1.0/stored-cursor")

    assert_that(recorder.calls[0]["url"], equal_to("https://graph.microsoft.com/v1.0/stored-cursor"))
    assert_that((changes.cursor, changes.more), equal_to((next_link, True)))
    assert_that([change.path for change in changes.items], equal_to(["Sales Bot/workspace/notes.md"]))


def test_onedrive_a_change_page_without_a_next_cursor_is_unavailable(graph):
    graph(httpx.Response(200, json={"value": []}))

    with pytest.raises(ProviderUnavailable):
        _onedrive()[0].changes(_SYNC_ROOT, None)


def test_onedrive_writes_go_where_the_engine_asks(graph):
    created = _graph_item("Sales Bot", "/drives/b!x/root:/Agent Barn", folder={"childCount": 0})
    upload = {
        "uploadUrl": "https://aailabs.sharepoint.com/upload?tempauth=x",
        "expirationDateTime": "2026-10-22T09:15:00Z",
    }
    empty = _graph_item("empty.txt", "/drives/b!x/root:/Agent Barn/Sales Bot/workspace", size=0)
    recorder = graph(
        httpx.Response(201, json=created),
        httpx.Response(200, json=created),
        httpx.Response(204),
        httpx.Response(200, json=upload),
        httpx.Response(200, json={"id": "i", "@microsoft.graph.downloadUrl": "https://aailabs.sharepoint.com/dl"}),
        httpx.Response(201, json=empty),
        httpx.Response(200, json=created),
    )
    plugin = _onedrive()[0]

    folder = plugin.create_folder(_SYNC_ROOT, parent_id=_BARN_ID, name="Sales Bot")
    plugin.move_item(_SYNC_ROOT, item_id="id-Sales Bot", name="Sales Team")
    plugin.delete_item(_SYNC_ROOT, item_id="old")
    target = plugin.upload_target(_SYNC_ROOT, parent_id="folder-1", rel_path="workspace/notes.md")
    url = plugin.download_url(_SYNC_ROOT, item_id="i")
    empty_file = plugin.write_empty_file(_SYNC_ROOT, parent_id="folder-1", rel_path="workspace/empty.txt")
    plugin.get_item_by_path(_SYNC_ROOT, parent_id=_BARN_ID, rel_path="Sales Bot")

    assert_that((folder.is_folder, folder.path), equal_to((True, "Sales Bot")))
    assert_that(
        target,
        equal_to(
            UploadTarget(
                url="https://aailabs.sharepoint.com/upload?tempauth=x",
                expires_at=datetime(2026, 10, 22, 9, 15, tzinfo=UTC),
            )
        ),
    )
    assert_that(url, equal_to("https://aailabs.sharepoint.com/dl"))
    assert_that(empty_file.size, equal_to(0))
    assert_that(
        [(call["method"], call["url"]) for call in recorder.calls],
        equal_to(
            [
                ("POST", f"{_GRAPH_DRIVE}/items/{_BARN_ID}/children"),
                ("PATCH", f"{_GRAPH_DRIVE}/items/id-Sales Bot"),
                ("DELETE", f"{_GRAPH_DRIVE}/items/old"),
                ("POST", f"{_GRAPH_DRIVE}/items/folder-1:/workspace/notes.md:/createUploadSession"),
                ("GET", f"{_GRAPH_DRIVE}/items/i?select=id,@microsoft.graph.downloadUrl"),
                ("PUT", f"{_GRAPH_DRIVE}/items/folder-1:/workspace/empty.txt:/content"),
                ("GET", f"{_GRAPH_DRIVE}/items/{_BARN_ID}:/Sales%20Bot:"),
            ]
        ),
    )
    assert_that(recorder.calls[1]["json"], equal_to({"name": "Sales Team"}))


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(404), RemoteItemMissing),
        (httpx.Response(409), RemoteNameTaken),
        (httpx.Response(400), RemoteChangeRejected),
        (httpx.Response(412), RemoteChangeRejected),
        (httpx.Response(410), RemoteResyncRequired),
        (httpx.Response(403), LocationAccessRefused),
        (httpx.Response(500), ProviderUnavailable),
        (httpx.ConnectError("boom"), ProviderUnavailable),
    ],
)
def test_onedrive_file_failures_are_typed(graph, response, expected):
    graph(response)

    with pytest.raises(expected):
        _onedrive()[0].get_item(_SYNC_ROOT, item_id="x")


def test_onedrive_throttling_passes_on_microsofts_wait(graph):
    graph(httpx.Response(429, headers={"Retry-After": "120"}))

    with pytest.raises(ProviderThrottled) as exc:
        _onedrive()[0].get_item(_SYNC_ROOT, item_id="x")

    assert_that(exc.value.retry_after, equal_to(120))


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (MicrosoftIdentityError("invalid_client", "AADSTS7000215"), LocationAccessRefused),
        (MicrosoftIdentityUnavailable("ConnectError"), ProviderUnavailable),
    ],
)
def test_onedrive_an_app_token_failure_is_typed_before_calling_graph(graph, failure, expected):
    recorder = graph()
    plugin, identity, _ = _onedrive()
    identity.app_token_result = failure

    with pytest.raises(expected):
        plugin.get_item(_SYNC_ROOT, item_id="x")

    assert_that(recorder.calls, is_(empty()))


def test_onedrive_a_root_without_a_site_is_refused_before_calling_microsoft(graph):
    recorder = graph()
    plugin, identity, _ = _onedrive()
    no_site = SyncRoot(account_id=TEAMS_TENANT_ID, location_id=None, folder_id=_BARN_ID, folder_name="Agent Barn")

    with pytest.raises(LocationNotFound):
        plugin.get_item(no_site, item_id="x")

    assert_that((recorder.calls, identity.app_token_requests), equal_to(([], [])))


def test_onedrive_refreshes_a_rejected_token_once_and_retries(graph):
    item = _graph_item("notes.md", "/drives/b!x/root:/Agent Barn/Sales Bot/workspace")
    recorder = graph(httpx.Response(401), httpx.Response(200, json=item))
    plugin, identity, _ = _onedrive()

    found = plugin.get_item(_SYNC_ROOT, item_id="id-notes.md")

    assert_that(found.path, equal_to("Sales Bot/workspace/notes.md"))
    assert_that((len(identity.app_token_requests), len(recorder.calls)), equal_to((2, 2)))


def test_onedrive_reports_access_lost_when_a_fresh_token_is_rejected_too(graph):
    graph(httpx.Response(401), httpx.Response(401))
    plugin, identity, _ = _onedrive()

    with pytest.raises(LocationAccessRefused):
        plugin.get_item(_SYNC_ROOT, item_id="x")

    assert_that(len(identity.app_token_requests), equal_to(2))


def test_onedrive_service_unavailable_passes_on_microsofts_wait(graph):
    graph(httpx.Response(503, headers={"Retry-After": "45"}))

    with pytest.raises(ProviderThrottled) as exc:
        _onedrive()[0].get_item(_SYNC_ROOT, item_id="x")

    assert_that(exc.value.retry_after, equal_to(45))


def test_onedrive_lists_every_file_below_a_folder_across_pages_and_subfolders(graph):
    reports = "/drives/b!x/root:/Agent Barn/Sales Bot/workspace/reports"
    first_page = {
        "value": [_graph_item("q3", reports, folder={"childCount": 1}), _graph_item("a.md", reports)],
        "@odata.nextLink": f"{_GRAPH_DRIVE}/items/folder-1/children?$skiptoken=2",
    }
    recorder = graph(
        httpx.Response(200, json=first_page),
        httpx.Response(200, json={"value": [_graph_item("b.md", reports)]}),
        httpx.Response(200, json={"value": [_graph_item("c.md", f"{reports}/q3")]}),
    )

    files = _onedrive()[0].list_files(_SYNC_ROOT, folder_id="folder-1")

    assert_that(
        sorted(item.path or "" for item in files),
        equal_to(
            [
                "Sales Bot/workspace/reports/a.md",
                "Sales Bot/workspace/reports/b.md",
                "Sales Bot/workspace/reports/q3/c.md",
            ]
        ),
    )
    assert_that(
        [call["url"] for call in recorder.calls],
        equal_to(
            [
                f"{_GRAPH_DRIVE}/items/folder-1/children",
                f"{_GRAPH_DRIVE}/items/folder-1/children?$skiptoken=2",
                f"{_GRAPH_DRIVE}/items/id-q3/children",
            ]
        ),
    )


def test_onedrive_deletes_with_the_administrators_own_token_not_the_apps(graph):
    recorder = graph(httpx.Response(204))
    plugin, identity, _ = _onedrive()

    plugin.delete_item_with("delegated-admin-token", _SYNC_ROOT, item_id="folder-1")

    assert_that(identity.app_token_requests, equal_to([]))
    assert_that(
        (recorder.calls[0]["method"], recorder.calls[0]["url"], recorder.calls[0]["headers"]),
        equal_to(("DELETE", f"{_GRAPH_DRIVE}/items/folder-1", {"Authorization": "Bearer delegated-admin-token"})),
    )
