"""Organization OneDrive sync connection: status, the authorize URL and the Microsoft callback.

Status is readable by every Organization Member; starting a connect or a disconnect needs
organization.update. The callback is unauthenticated and trusts only the signed state.
"""

import urllib.parse
import uuid
from datetime import UTC, datetime, timedelta
from uuid import uuid7

from fastapi import status
from hamcrest import (
    assert_that,
    contains_string,
    equal_to,
    has_entries,
    is_not,
    none,
    not_,
    starts_with,
)

from api.core.config import get_config
from api.domains.agents.microsoft_graph_sites import (
    SiteAccessRefused,
    SiteNotFound,
    SitesThrottled,
    SiteSummary,
    SitesUnavailable,
)
from api.domains.agents.microsoft_identity import MicrosoftIdentityError, MicrosoftIdentityUnavailable, MicrosoftTokens
from api.domains.agents.models import AgentSecret, GrantedSite, SecretProvider, SharePointContent, encrypt_content
from api.domains.agents.sharepoint_service import SignInState, encode_sign_in_state
from api.domains.onedrive_sync.models import OneDriveSyncStatus
from api.domains.onedrive_sync.repository import OneDriveSyncRepository
from api.domains.onedrive_sync.service import OneDriveSyncState, encode_state
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.crypto import decrypt_token, encrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, there_is_an_agent
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization,
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.sharepoint import (
    FOLDER_WEB_URL,
    FakeMicrosoftIdentityModule,
    fake_graph_sites,
    fake_identity,
    id_token,
)
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_CLIENT_ID = "7029602d-0000-4000-8000-000000000001"
_CLIENT_SECRET = "platform-app-secret-value"
_WEB_APP_URL = "https://farm.example.com"
_REDIRECT_URI = f"{_WEB_APP_URL}/api/v1/integrations/onedrive-sync/callback"
_CALLBACK = "/api/v1/integrations/onedrive-sync/callback"
_TENANT_ID = "22222222-2222-4222-8222-222222222222"
_SITE_ID = "contoso.sharepoint.com,aaa,bbb"
_FOLDER_URL = "https://contoso.sharepoint.com/sites/AgentBarnTest/Shared%20Documents/Agent%20Barn"
_SIGN_IN_SCOPE = (
    "https://graph.microsoft.com/Sites.FullControl.All https://graph.microsoft.com/Sites.Read.All openid profile"
)
_ADMIN_APPROVAL = "A Microsoft Global Administrator needs to approve Agent Barn for your organization."
_GRANTED_SCOPE = "https://graph.microsoft.com/Sites.FullControl.All https://graph.microsoft.com/Sites.Read.All"
_DELEGATED_ACCESS_TOKEN = "delegated-access-token"


def _env(client_id: str = _CLIENT_ID, client_secret: str = _CLIENT_SECRET):
    return set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "WEB_APP_URL": _WEB_APP_URL,
            "ONEDRIVE_SYNC_CLIENT_ID": client_id,
            "ONEDRIVE_SYNC_CLIENT_SECRET": client_secret,
        }
    )


def _given(role: OrganizationRole = OrganizationRole.OWNER, *, configured: bool = True):
    return [
        _env() if configured else _env(client_id="", client_secret=""),
        prepare_injector(modules=[FakeMicrosoftIdentityModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(role=role),
    ]


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _base(context, organization_id=None) -> str:
    return f"/api/v1/organizations/{organization_id or context.organization.id}/onedrive-sync/connection"


def _authorize_url(context, purpose: str = "connect", headers: dict | None = None):
    return context.client.get(
        f"{_base(context)}/authorize-url", params={"purpose": purpose}, headers=headers or _auth(context)
    )


def _query(url: str) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


def _member_headers(context) -> dict[str, str]:
    member_id = uuid7()
    there_is_a_user(
        id=member_id,
        email=f"member-{member_id}@example.com",
        organization_id=context.organization.id,
        role=OrganizationRole.MEMBER,
    )(context)
    there_is_an_access_token_for_user(user_id=member_id)(context)
    return {"Authorization": f"Bearer {context.access_token}"}


def _pending(context, *, expires_in: timedelta = timedelta(hours=1)):
    return context.injector.get(OneDriveSyncRepository).create_pending(
        context.organization.id,
        tenant_id=_TENANT_ID,
        connected_by_user_id=context.user.id,
        pending_access_token=encrypt_token(_DELEGATED_ACCESS_TOKEN, TEST_ENCRYPTION_KEY),
        pending_expires_at=datetime.now(UTC) + expires_in,
    )


def _active(context):
    return context.injector.get(OneDriveSyncRepository).activate(
        _pending(context).id,
        site_id=_SITE_ID,
        site_name="Agent Barn Test",
        site_url="https://contoso.sharepoint.com/sites/AgentBarnTest",
        folder_item_id="item-1",
        folder_web_url=_FOLDER_URL,
        permission_id="perm-1",
    )


def _consent_state(context) -> str:
    response = _authorize_url(context)
    return _query(response.json()["authorize_url"])["state"]


# --- status ------------------------------------------------------------------------


def test_status_says_unavailable_when_the_platform_app_is_not_configured():
    with given(_given(configured=False)) as context:
        with when("an Organization reads its OneDrive sync status on a server without the app"):
            response = context.client.get(_base(context), headers=_auth(context))

        with then("the section is reported unavailable rather than failing"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json(), has_entries(available=False, status=None))


def test_status_says_not_connected_when_there_is_no_connection():
    with given(_given()) as context:
        response = context.client.get(_base(context), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json(), has_entries(available=True, status=None, folder_web_url=None))


def test_a_member_can_read_the_status():
    with given(_given()) as context:
        _active(context)

        response = context.client.get(_base(context), headers=_member_headers(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json(), has_entries(status="active", folder_web_url=_FOLDER_URL))


def test_another_organizations_status_is_refused():
    with given(_given()) as context:
        response = context.client.get(_base(context, uuid7()), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_an_active_connection_shows_the_site_and_the_folder_link_only():
    with given(_given()) as context:
        _active(context)

        body = context.client.get(_base(context), headers=_auth(context)).json()

        assert_that(
            body,
            has_entries(
                available=True,
                status="active",
                site_name="Agent Barn Test",
                site_url="https://contoso.sharepoint.com/sites/AgentBarnTest",
                folder_web_url=_FOLDER_URL,
            ),
        )
        assert_that(body["connected_at"], is_not(none()))
        assert_that(
            set(body),
            equal_to({"available", "status", "site_name", "site_url", "folder_web_url", "connected_at"}),
        )


def test_a_pending_connection_is_reported_while_its_sign_in_is_fresh():
    with given(_given()) as context:
        _pending(context)

        body = context.client.get(_base(context), headers=_auth(context)).json()

        assert_that(body, has_entries(status="pending"))
        assert_that(str(body), not_(contains_string(_DELEGATED_ACCESS_TOKEN)))
        assert_that(
            set(body), equal_to({"available", "status", "site_name", "site_url", "folder_web_url", "connected_at"})
        )


def test_an_expired_pending_connection_reads_as_not_connected():
    with given(_given()) as context:
        _pending(context, expires_in=timedelta(minutes=-1))

        body = context.client.get(_base(context), headers=_auth(context)).json()

        assert_that(body, has_entries(status=None))


# --- authorize URL -----------------------------------------------------------------


def test_connecting_is_unavailable_when_the_platform_app_is_not_configured():
    with given(_given(configured=False)) as context:
        response = _authorize_url(context)

        assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))
        assert_that(response.json()["detail"], equal_to("OneDrive sync is not configured on this server."))


def test_a_member_cannot_start_a_connection():
    with given(_given()) as context:
        response = _authorize_url(context, headers=_member_headers(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_an_admin_starts_with_microsoft_admin_consent_for_any_organization():
    with given(_given(role=OrganizationRole.ADMIN)) as context:
        with when("an Organization Admin starts connecting OneDrive"):
            response = _authorize_url(context)

        with then("they are sent to Microsoft's admin consent for the platform app's permissions"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            url = response.json()["authorize_url"]
            assert_that(url, starts_with("https://login.microsoftonline.com/organizations/v2.0/adminconsent?"))
            query = _query(url)
            assert_that(
                query,
                has_entries(
                    client_id=_CLIENT_ID,
                    scope="https://graph.microsoft.com/.default",
                    redirect_uri=_REDIRECT_URI,
                ),
            )
            assert_that(query["state"], is_not(none()))
            assert_that(url, not_(contains_string(_CLIENT_SECRET)))


def test_connecting_is_refused_while_already_connected():
    with given(_given()) as context:
        _active(context)

        response = _authorize_url(context)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_disconnecting_is_refused_when_not_connected():
    with given(_given()) as context:
        response = _authorize_url(context, purpose="disconnect")

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_disconnecting_goes_straight_to_microsoft_sign_in():
    with given(_given()) as context:
        _active(context)

        response = _authorize_url(context, purpose="disconnect")

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        url = response.json()["authorize_url"]
        assert_that(url, starts_with("https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize?"))
        assert_that(
            _query(url),
            has_entries(
                client_id=_CLIENT_ID,
                redirect_uri=_REDIRECT_URI,
                response_type="code",
                scope=_SIGN_IN_SCOPE,
                prompt="select_account",
                code_challenge_method="S256",
            ),
        )


# --- callback ----------------------------------------------------------------------


def test_after_consent_the_callback_continues_to_sign_in_without_trusting_the_tenant():
    with given(_given()) as context:
        state = _consent_state(context)

        with when("Microsoft returns from admin consent, naming a tenant"):
            response = context.client.get(
                _CALLBACK,
                params={"admin_consent": "True", "tenant": "attacker-chosen-tenant", "state": state},
                follow_redirects=False,
            )

        with then("the popup is sent straight on to sign-in at the multi-tenant authority"):
            assert_that(response.status_code, equal_to(status.HTTP_302_FOUND))
            location = response.headers["location"]
            assert_that(location, starts_with("https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize?"))
            assert_that(location, not_(contains_string("attacker-chosen-tenant")))
            query = _query(location)
            assert_that(
                query,
                has_entries(
                    client_id=_CLIENT_ID,
                    redirect_uri=_REDIRECT_URI,
                    response_type="code",
                    scope=_SIGN_IN_SCOPE,
                    prompt="select_account",
                    state=state,
                    code_challenge_method="S256",
                ),
            )
            assert_that(query["code_challenge"], is_not(none()))


def test_a_consent_microsoft_refused_explains_who_must_approve():
    with given(_given()) as context:
        state = _consent_state(context)

        response = context.client.get(
            _CALLBACK,
            params={
                "admin_consent": "True",
                "error": "access_denied",
                "error_description": "AADSTS65004: User declined to consent to access the app.",
                "state": state,
            },
            follow_redirects=False,
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.text, contains_string(_ADMIN_APPROVAL))
        assert_that(response.text, contains_string('"type": "onedrive-sync-oauth"'))


def test_consent_required_explains_who_must_approve():
    with given(_given()) as context:
        response = context.client.get(_CALLBACK, params={"error": "consent_required"}, follow_redirects=False)

        assert_that(response.text, contains_string(_ADMIN_APPROVAL))


def test_another_microsoft_error_is_named():
    with given(_given()) as context:
        response = context.client.get(_CALLBACK, params={"error": "server_error"}, follow_redirects=False)

        assert_that(response.text, contains_string("server_error"))
        assert_that(response.text, not_(contains_string(_ADMIN_APPROVAL)))


def test_the_sign_in_code_is_handed_to_the_opener():
    with given(_given()) as context:
        state = _consent_state(context)

        response = context.client.get(_CALLBACK, params={"code": "the-code", "state": state}, follow_redirects=False)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.text, contains_string('"type": "onedrive-sync-oauth"'))
        assert_that(response.text, contains_string('"code": "the-code"'))
        assert_that(response.text, contains_string(f'"state": "{state}"'))
        assert_that(response.text, contains_string(f'"{_WEB_APP_URL}"'))


def test_a_forged_or_expired_state_is_refused():
    with given(_given()) as context:
        response = context.client.get(_CALLBACK, params={"code": "the-code", "state": "not-a-state"})

        assert_that(response.text, contains_string("expired"))
        assert_that(response.text, not_(contains_string("the-code")))


def test_a_sharepoint_sign_in_state_is_refused():
    with given(_given()) as context:
        sharepoint_state = encode_sign_in_state(
            get_config(),
            SignInState(
                agent_id=uuid.uuid4(),
                connection_id=uuid.uuid4(),
                user_id=context.user.id,
                read_only=False,
                code_verifier="v" * 50,
            ),
        )

        response = context.client.get(_CALLBACK, params={"code": "the-code", "state": sharepoint_state})

        assert_that(response.text, contains_string("expired"))
        assert_that(response.text, not_(contains_string("the-code")))


def test_script_injection_in_the_error_is_escaped():
    with given(_given()) as context:
        response = context.client.get(_CALLBACK, params={"error": "</script><script>alert(1)</script>"})

        assert_that(response.text, not_(contains_string("</script><script>")))


# --- sign-in -----------------------------------------------------------------------


def _signed_in_tokens(*, scope: str = _GRANTED_SCOPE, tenant_id: str | None = _TENANT_ID) -> MicrosoftTokens:
    claims_token = id_token(tenant_id=tenant_id) if tenant_id else None
    return MicrosoftTokens(
        access_token=_DELEGATED_ACCESS_TOKEN, refresh_token=None, expires_in=3600, scope=scope, id_token=claims_token
    )


def _sign_in(context, state: str, headers: dict | None = None):
    return context.client.post(
        f"{_base(context)}/sign-in", json={"code": "the-code", "state": state}, headers=headers or _auth(context)
    )


def _forged_state(context, *, organization_id=None, user_id=None, purpose="connect") -> str:
    return encode_state(
        get_config(),
        OneDriveSyncState(
            organization_id=organization_id or context.organization.id,
            user_id=user_id or context.user.id,
            purpose=purpose,
            code_verifier="v" * 50,
            code_challenge="c",
        ),
    )


def test_signing_in_redeems_the_code_as_the_platform_app_and_holds_a_pending_connection():
    with given(_given()) as context:
        fake_identity(context).exchange_result = _signed_in_tokens()
        state = _consent_state(context)

        with when("the Owner's popup hands back Microsoft's code"):
            response = _sign_in(context, state)

        with then("the code is redeemed with the platform app's secret at the multi-tenant authority"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json(), has_entries(available=True, status="pending"))
            assert_that(response.text, not_(contains_string(_DELEGATED_ACCESS_TOKEN)))
            exchange = fake_identity(context).exchanges[0]
            assert_that(
                exchange,
                has_entries(
                    tenant_id="organizations",
                    client_id=_CLIENT_ID,
                    client_secret=_CLIENT_SECRET,
                    code="the-code",
                    redirect_uri=_REDIRECT_URI,
                    scopes=tuple(_SIGN_IN_SCOPE.split()),
                ),
            )
            assert_that(len(exchange["code_verifier"]) >= 43, equal_to(True))

        with then("the tenant comes from the sign-in and the delegated token is kept only encrypted"):
            connection = context.injector.get(OneDriveSyncRepository).get_open(context.organization.id)
            assert connection is not None
            assert connection.pending_access_token is not None
            assert_that(connection.status, equal_to(OneDriveSyncStatus.PENDING))
            assert_that(connection.tenant_id, equal_to(_TENANT_ID))
            assert_that(connection.connected_by_user_id, equal_to(context.user.id))
            assert_that(connection.pending_access_token, is_not(equal_to(_DELEGATED_ACCESS_TOKEN)))
            assert_that(
                decrypt_token(connection.pending_access_token, TEST_ENCRYPTION_KEY),
                equal_to(_DELEGATED_ACCESS_TOKEN),
            )
            assert_that(connection.pending_expires_at, is_not(none()))


def test_a_state_issued_to_someone_else_is_refused():
    with given(_given()) as context:
        state = _forged_state(context, user_id=uuid7())

        response = _sign_in(context, state)

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(fake_identity(context).exchanges, equal_to([]))


def test_a_state_issued_for_another_organization_is_refused():
    with given(_given()) as context:
        response = _sign_in(context, _forged_state(context, organization_id=uuid7()))

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_a_disconnect_state_cannot_complete_a_connect():
    with given(_given()) as context:
        response = _sign_in(context, _forged_state(context, purpose="disconnect"))

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_a_member_cannot_complete_a_sign_in():
    with given(_given()) as context:
        headers = _member_headers(context)
        state = _forged_state(context)

        response = _sign_in(context, state, headers=headers)

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(fake_identity(context).exchanges, equal_to([]))


def test_a_read_only_api_key_cannot_complete_a_sign_in():
    with given(_given()) as context:
        key = context.client.post(
            "/api/v1/auth/me/api-keys",
            json={"name": "Automation", "access_mode": "READ_ONLY"},
            headers=_auth(context),
        ).json()["token"]

        response = _sign_in(context, _consent_state(context), headers={"Authorization": f"Bearer {key}"})

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_signing_in_is_unavailable_when_the_platform_app_is_not_configured():
    with given(_given(configured=False)) as context:
        response = _sign_in(context, _forged_state(context))

        assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))


def test_a_sign_in_without_a_tenant_is_refused():
    with given(_given()) as context:
        fake_identity(context).exchange_result = _signed_in_tokens(tenant_id=None)

        response = _sign_in(context, _consent_state(context))

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(context.injector.get(OneDriveSyncRepository).get_open(context.organization.id), none())


def test_a_sign_in_without_site_administration_is_refused():
    with given(_given()) as context:
        fake_identity(context).exchange_result = _signed_in_tokens(scope="https://graph.microsoft.com/Sites.Read.All")

        response = _sign_in(context, _consent_state(context))

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json()["detail"], contains_string("administrator"))


def test_a_sign_in_microsoft_refuses_is_reported():
    with given(_given()) as context:
        fake_identity(context).exchange_result = MicrosoftIdentityError("invalid_grant", "AADSTS70008: expired code")

        response = _sign_in(context, _consent_state(context))

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.text, not_(contains_string(_CLIENT_SECRET)))


def test_an_unreachable_microsoft_is_reported():
    with given(_given()) as context:
        fake_identity(context).exchange_result = MicrosoftIdentityUnavailable("ConnectError")

        response = _sign_in(context, _consent_state(context))

        assert_that(response.status_code, equal_to(status.HTTP_502_BAD_GATEWAY))


def test_signing_in_again_replaces_the_pending_connection():
    with given(_given()) as context:
        fake_identity(context).exchange_result = _signed_in_tokens()
        _sign_in(context, _consent_state(context))
        first = context.injector.get(OneDriveSyncRepository).get_open(context.organization.id)

        _sign_in(context, _consent_state(context))

        second = context.injector.get(OneDriveSyncRepository).get_open(context.organization.id)
        assert first is not None and second is not None
        assert_that(second.id, is_not(equal_to(first.id)))


def test_signing_in_is_refused_while_connected():
    with given(_given()) as context:
        fake_identity(context).exchange_result = _signed_in_tokens()
        state = _forged_state(context)
        _active(context)

        response = _sign_in(context, state)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


# --- abandon -----------------------------------------------------------------------


def test_abandoning_a_pending_connection_forgets_it():
    with given(_given()) as context:
        _pending(context)

        response = context.client.delete(_base(context), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        assert_that(context.client.get(_base(context), headers=_auth(context)).json(), has_entries(status=None))


def test_abandoning_leaves_an_active_connection_alone():
    with given(_given()) as context:
        _active(context)

        response = context.client.delete(_base(context), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        assert_that(context.client.get(_base(context), headers=_auth(context)).json(), has_entries(status="active"))


def test_a_member_cannot_abandon_a_connection():
    with given(_given()) as context:
        _pending(context)

        response = context.client.delete(_base(context), headers=_member_headers(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


# --- site picker -------------------------------------------------------------------


def _search(context, search: str, headers: dict | None = None):
    return context.client.get(f"{_base(context)}/sites", params={"search": search}, headers=headers or _auth(context))


def _choose(context, site_id: str = _SITE_ID, headers: dict | None = None):
    return context.client.post(f"{_base(context)}/site", json={"site_id": site_id}, headers=headers or _auth(context))


def test_sites_are_searched_with_the_administrators_delegated_token():
    with given(_given()) as context:
        _pending(context)
        fake_graph_sites(context).search_results = [
            SiteSummary(
                id=_SITE_ID, name="Agent Barn Test", web_url="https://contoso.sharepoint.com/sites/AgentBarnTest"
            )
        ]

        response = _search(context, "Agent Barn")

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            response.json(),
            equal_to(
                [
                    {
                        "id": _SITE_ID,
                        "name": "Agent Barn Test",
                        "web_url": "https://contoso.sharepoint.com/sites/AgentBarnTest",
                    }
                ]
            ),
        )
        assert_that(
            fake_graph_sites(context).searches, equal_to([{"token": _DELEGATED_ACCESS_TOKEN, "query": "Agent Barn"}])
        )


def test_a_search_needs_a_term():
    with given(_given()) as context:
        _pending(context)

        response = _search(context, "   ")

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(fake_graph_sites(context).searches, equal_to([]))


def test_sites_cannot_be_searched_without_a_sign_in():
    with given(_given()) as context:
        response = _search(context, "Agent Barn")

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_sites_cannot_be_searched_after_the_sign_in_expired():
    with given(_given()) as context:
        _pending(context, expires_in=timedelta(minutes=-1))

        response = _search(context, "Agent Barn")

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(fake_graph_sites(context).searches, equal_to([]))


def test_a_member_cannot_search_sites():
    with given(_given()) as context:
        _pending(context)

        response = _search(context, "Agent Barn", headers=_member_headers(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


# --- choosing the site -------------------------------------------------------------


def test_choosing_a_site_grants_write_on_it_and_creates_the_agent_barn_folder():
    with given(_given()) as context:
        _pending(context)

        with when("the Owner picks the SharePoint site"):
            response = _choose(context)

        with then("the platform app is granted write on that site only, with the administrator's token"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(
                fake_graph_sites(context).grants,
                equal_to(
                    [
                        {
                            "token": _DELEGATED_ACCESS_TOKEN,
                            "site_id": _SITE_ID,
                            "app_id": _CLIENT_ID,
                            "role": "write",
                            "display_name": "Agent Barn",
                        }
                    ]
                ),
            )

        with then("the folder is ensured as the app, in the tenant the administrator signed in to"):
            assert_that(
                fake_identity(context).app_token_requests,
                equal_to([{"tenant_id": _TENANT_ID, "client_id": _CLIENT_ID, "client_secret": _CLIENT_SECRET}]),
            )
            assert_that(
                fake_graph_sites(context).folders,
                equal_to([{"token": "app-only-token", "site_id": _SITE_ID, "name": "Agent Barn"}]),
            )

        with then("the connection is active, shows the folder link, and keeps no token"):
            assert_that(
                response.json(),
                has_entries(
                    status="active",
                    site_name="Agent Barn Test",
                    site_url="https://contoso.sharepoint.com/sites/AgentBarnTest",
                    folder_web_url=FOLDER_WEB_URL,
                ),
            )
            connection = context.injector.get(OneDriveSyncRepository).get_open(context.organization.id)
            assert connection is not None
            assert_that(connection.permission_id, equal_to("perm-1"))
            assert_that(connection.folder_item_id, equal_to("folder-item-1"))
            assert_that(connection.pending_access_token, none())


def test_a_site_cannot_be_chosen_after_the_sign_in_expired():
    with given(_given()) as context:
        _pending(context, expires_in=timedelta(minutes=-1))

        response = _choose(context)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(fake_graph_sites(context).grants, equal_to([]))


def test_a_site_cannot_be_chosen_without_a_sign_in():
    with given(_given()) as context:
        response = _choose(context)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_a_member_cannot_choose_the_site():
    with given(_given()) as context:
        _pending(context)

        response = _choose(context, headers=_member_headers(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(fake_graph_sites(context).grants, equal_to([]))


def test_an_unknown_site_is_reported():
    with given(_given()) as context:
        _pending(context)
        fake_graph_sites(context).unknown_sites.add(_SITE_ID)

        response = _choose(context)

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(fake_graph_sites(context).grants, equal_to([]))


def test_a_grant_microsoft_refuses_says_who_may_connect():
    with given(_given()) as context:
        _pending(context)
        fake_graph_sites(context).grant_failures[_SITE_ID] = SiteAccessRefused("HTTP 403")

        response = _choose(context)

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(response.json()["detail"], contains_string("SharePoint administrator who is a member of this site"))
        assert_that(context.client.get(_base(context), headers=_auth(context)).json(), has_entries(status="pending"))


def test_throttling_says_to_wait():
    with given(_given()) as context:
        _pending(context)
        fake_graph_sites(context).grant_failures[_SITE_ID] = SitesThrottled("HTTP 429")

        response = _choose(context)

        assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))


def test_a_folder_that_cannot_be_created_takes_back_the_grant():
    with given(_given()) as context:
        _pending(context)
        fake_graph_sites(context).folder_failure = SitesUnavailable("HTTP 500")

        response = _choose(context)

        assert_that(response.status_code, equal_to(status.HTTP_502_BAD_GATEWAY))
        assert_that(
            fake_graph_sites(context).revokes,
            equal_to([{"token": _DELEGATED_ACCESS_TOKEN, "site_id": _SITE_ID, "permission_id": "perm-1"}]),
        )
        assert_that(context.client.get(_base(context), headers=_auth(context)).json(), has_entries(status="pending"))


def test_a_folder_the_app_may_not_create_takes_back_the_grant():
    with given(_given()) as context:
        _pending(context)
        fake_graph_sites(context).folder_failure = SiteAccessRefused("HTTP 403")

        response = _choose(context)

        assert_that(response.status_code, equal_to(status.HTTP_502_BAD_GATEWAY))
        assert_that(len(fake_graph_sites(context).revokes), equal_to(1))


def test_an_app_token_microsoft_refuses_takes_back_the_grant():
    with given(_given()) as context:
        _pending(context)
        fake_identity(context).app_token_result = MicrosoftIdentityError("invalid_client", "AADSTS7000215")

        response = _choose(context)

        assert_that(response.status_code, equal_to(status.HTTP_502_BAD_GATEWAY))
        assert_that(response.text, not_(contains_string(_CLIENT_SECRET)))
        assert_that(len(fake_graph_sites(context).revokes), equal_to(1))
        assert_that(fake_graph_sites(context).folders, equal_to([]))


def test_a_site_that_disappeared_is_reported_without_a_grant():
    with given(_given()) as context:
        _pending(context)
        fake_graph_sites(context).grant_failures[_SITE_ID] = SiteNotFound(_SITE_ID)

        response = _choose(context)

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(fake_graph_sites(context).revokes, equal_to([]))


# --- sites an Agent already holds --------------------------------------------------


def _an_agent_holds_site(context, site_id: str = _SITE_ID, *, deleted: bool = False) -> None:
    """An Agent's SharePoint integration was granted ``site_id`` on its own Teams app."""
    there_is_an_agent(name=f"SharePoint Agent {uuid7()}", deleted=deleted)(context)
    content = SharePointContent(
        mode="selected_sites",
        connection_id=str(uuid.uuid4()),
        tenant_id=_TENANT_ID,
        client_id="teams-app-id",
        email="admin@contoso.com",
        scopes=["Sites.Selected"],
        sites=[
            GrantedSite(url="https://contoso.sharepoint.com/sites/AgentBarnTest", site_id=site_id, permission_id="p1")
        ],
    )
    context.injector.get(PostgresRepositoryDelegate).save(
        AgentSecret(
            agent_id=context.agent.id,
            provider=SecretProvider.SHAREPOINT,
            secret_name="SharePoint",
            content=encrypt_content(content, TEST_ENCRYPTION_KEY),
        )
    )


def test_a_site_an_agent_already_holds_is_refused():
    with given(_given()) as context:
        _an_agent_holds_site(context, site_id=_SITE_ID.upper())
        _pending(context)

        with when("the Owner picks a site an Agent's SharePoint integration was granted"):
            response = _choose(context)

        with then("connecting is refused with one line, before anything is granted"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(
                response.json()["detail"],
                equal_to(
                    "An Agent in this Organization already has SharePoint access to this site. "
                    "Remove it there, or pick another site."
                ),
            )
            assert_that(fake_graph_sites(context).grants, equal_to([]))
            assert_that(
                context.client.get(_base(context), headers=_auth(context)).json(), has_entries(status="pending")
            )


def test_a_site_a_deleted_agent_still_holds_is_refused():
    with given(_given()) as context:
        _an_agent_holds_site(context, deleted=True)
        _pending(context)

        response = _choose(context)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(fake_graph_sites(context).grants, equal_to([]))


def test_a_site_an_agent_holds_elsewhere_does_not_block_connecting():
    with given(_given()) as context:
        _an_agent_holds_site(context, site_id="contoso.sharepoint.com,other,site")
        _pending(context)

        response = _choose(context)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(response.json(), has_entries(status="active"))


def test_another_organizations_agent_does_not_block_connecting():
    with given(_given()) as context:
        organization = context.organization
        there_is_an_organization()(context)
        _an_agent_holds_site(context)
        context.organization = organization
        _pending(context)

        response = _choose(context)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
