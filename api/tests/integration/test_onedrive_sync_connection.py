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
from api.domains.agents.sharepoint_service import SignInState, encode_sign_in_state
from api.domains.onedrive_sync.repository import OneDriveSyncRepository
from api.domains.users.organization_users.models import OrganizationRole
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
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
        prepare_injector(),
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
        pending_access_token="encrypted-delegated-token",
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
        assert_that(str(body), not_(contains_string("encrypted-delegated-token")))


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
