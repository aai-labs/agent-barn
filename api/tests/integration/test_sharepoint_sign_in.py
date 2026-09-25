"""Signing SharePoint in on the agent's Teams app, as a public client with PKCE: setup details,
the authorize URL, the callback page, and the exchange that stores the credential."""

import base64
import hashlib
import urllib.parse
from uuid import UUID

from fastapi import status
from hamcrest import assert_that, contains_string, equal_to, has_entries, has_key, is_not, none, not_, starts_with

from api.core.config import Config
from api.domains.agents.models import SecretProvider, SharePointContent, decrypt_content
from api.domains.agents.sharepoint_service import decode_sign_in_state
from api.domains.users.organization_users.models import OrganizationRole
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.sharepoint import (
    CODE_VERIFIER,
    SIGNED_IN_EMAIL,
    TEAMS_APP_ID,
    TEAMS_APP_PASSWORD,
    TEAMS_TENANT_ID,
    FakeMicrosoftIdentityModule,
    agent_base,
    auth,
    fake_identity,
    public_client_flows_off,
    sharepoint_secret,
    sign_in,
    sign_in_state,
    there_is_a_teams_connection,
    tokens,
)
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_CALLBACK = "https://farm.example.com/api/v1/integrations/microsoft/callback"

_ENV = {
    "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
    "LITELLM_BASE_URL": "http://litellm:4000",
    "LITELLM_SECRET_NAME": "litellm",
    "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
    "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
    "SKIP_TEAMS_TOKEN_VALIDATION": "true",
    "WEB_APP_URL": "https://farm.example.com",
}

_GIVEN = [
    set_env_variable(_ENV),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), FakeMicrosoftIdentityModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_an_agent(),
    there_is_a_teams_connection(),
]


def _get(context, path: str, connection_id: str | None = None, **params):
    return context.client.get(
        f"{agent_base(context)}/integrations/sharepoint/{path}",
        params={"connection_id": connection_id or context.teams_connection["id"], **params},
        headers=auth(context),
    )


def _callback(context, **params):
    return context.client.get("/api/v1/integrations/microsoft/callback", params=params)


def _query(url: str) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


# --- setup details ------------------------------------------------------------------


def test_setup_gives_the_teams_app_and_the_redirect_uri_to_register() -> None:
    with given(_GIVEN) as context:
        with when("I ask what to set up on the agent's Teams app"):
            response = _get(context, "setup")

        with then("I get the app, its tenant and the exact redirect URI, and nothing secret"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            body = response.json()
            assert_that(body, has_entries(app_id=TEAMS_APP_ID, tenant_id=TEAMS_TENANT_ID, redirect_uri=_CALLBACK))

        with then("and administrator approval links for each access level, on the app's tenant"):
            for key, permission in (
                ("admin_consent_url", "Sites.ReadWrite.All"),
                ("read_only_admin_consent_url", "Sites.Read.All"),
            ):
                url = body[key]
                assert_that(url, starts_with(f"https://login.microsoftonline.com/{TEAMS_TENANT_ID}/v2.0/adminconsent?"))
                assert_that(
                    _query(url),
                    has_entries(
                        client_id=TEAMS_APP_ID,
                        scope=f"https://graph.microsoft.com/{permission}",
                        redirect_uri=_CALLBACK,
                    ),
                )
            assert_that(response.text, not_(contains_string(TEAMS_APP_PASSWORD)))


def test_setup_refuses_a_connection_of_another_agent() -> None:
    with given(_GIVEN) as context:
        own_connection = context.teams_connection
        there_is_an_agent(name="Other Agent", bot_token="xoxb-other-agent")(context)

        with when("I ask about the first agent's Teams app under the second agent"):
            response = _get(context, "setup", connection_id=own_connection["id"])

        with then("the connection is not found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


# --- authorize URL ------------------------------------------------------------------


def test_authorize_url_signs_in_on_the_teams_app_with_pkce() -> None:
    with given(_GIVEN) as context:
        with when("I ask for the SharePoint sign-in URL"):
            response = _get(context, "authorize-url", read_only="false")

        with then("it points at the Teams app's tenant, as a public client with a PKCE challenge"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            url = response.json()["authorize_url"]
            assert_that(url, starts_with(f"https://login.microsoftonline.com/{TEAMS_TENANT_ID}/oauth2/v2.0/authorize"))
            query = _query(url)
            assert_that(
                query, has_entries(client_id=TEAMS_APP_ID, redirect_uri=_CALLBACK, code_challenge_method="S256")
            )
            assert_that(query["scope"], contains_string("Sites.ReadWrite.All"))
            assert_that(url, not_(contains_string(TEAMS_APP_PASSWORD)))

        with then("the signed state carries the verifier that matches the challenge"):
            state = decode_sign_in_state(query["state"], context.injector.get(Config))
            assert state is not None
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(state.code_verifier.encode()).digest()).rstrip(b"=").decode()
            )
            assert_that(query["code_challenge"], equal_to(challenge))
            assert_that(url, not_(contains_string(state.code_verifier)))
            assert_that(state.connection_id, equal_to(UUID(context.teams_connection["id"])))


def test_authorize_url_read_only_asks_for_read_access() -> None:
    with given(_GIVEN) as context:
        with when("I ask for a read-only sign-in"):
            response = _get(context, "authorize-url", read_only="true")

        with then("the read scope is requested"):
            assert_that(response.json()["authorize_url"], contains_string("Sites.Read.All"))


def test_authorize_url_refuses_a_disabled_teams_connection() -> None:
    given_disabled = [*_GIVEN[:-1], there_is_a_teams_connection(enabled=False)]
    with given(given_disabled) as context:
        with when("I ask for the sign-in URL"):
            response = _get(context, "authorize-url")

        with then("I'm told to turn the connection on"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_authorize_url_is_hidden_from_a_member_without_access_to_the_agent() -> None:
    with given(_GIVEN) as context:
        there_is_a_user(
            name="Member",
            email="member@example.com",
            role=OrganizationRole.MEMBER,
            organization_id=context.organization.id,
        )(context)
        there_is_an_access_token_for_user()(context)

        with when("a member without access to the agent asks for the sign-in URL"):
            response = _get(context, "authorize-url")

        with then("the agent is not found for them"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


# --- sign-in (code exchange) --------------------------------------------------------


def test_sign_in_stores_the_credential_and_returns_only_who_signed_in() -> None:
    with given(_GIVEN) as context:
        with when("I complete the sign-in"):
            response = sign_in(context)

        with then("only the account and access come back"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(response.json(), equal_to({"email": SIGNED_IN_EMAIL, "read_only": False}))
            assert_that(response.text, not_(contains_string("rt-from-exchange")))

        with then("the code was redeemed with the verifier, on the Teams app's tenant, without a secret"):
            exchange = fake_identity(context).exchanges[0]
            assert_that(
                exchange,
                has_entries(
                    tenant_id=TEAMS_TENANT_ID,
                    client_id=TEAMS_APP_ID,
                    code="the-code",
                    redirect_uri=_CALLBACK,
                    code_verifier=CODE_VERIFIER,
                ),
            )
            assert_that(exchange, is_not(has_key("client_secret")))

        with then("the credential holds what aai-cli needs to refresh as that person"):
            secret = sharepoint_secret(context)
            assert secret is not None and secret.content is not None
            content = decrypt_content(SecretProvider.SHAREPOINT, secret.content, TEST_ENCRYPTION_KEY)
            assert isinstance(content, SharePointContent)
            assert_that(content.connection_id, equal_to(context.teams_connection["id"]))
            assert_that(content.tenant_id, equal_to(TEAMS_TENANT_ID))
            assert_that(content.client_id, equal_to(TEAMS_APP_ID))
            assert_that(content.email, equal_to(SIGNED_IN_EMAIL))
            assert_that(content.refresh_token, equal_to("rt-from-exchange"))
            assert_that(content.read_only, equal_to(False))


def test_signing_in_again_replaces_the_previous_sign_in() -> None:
    with given(_GIVEN) as context:
        sign_in(context)
        first = sharepoint_secret(context)
        assert first is not None and first.content is not None
        first_content = decrypt_content(SecretProvider.SHAREPOINT, first.content, TEST_ENCRYPTION_KEY)
        assert isinstance(first_content, SharePointContent)
        fake_identity(context).exchange_result = tokens(
            refresh_token="rt-second", scope="Sites.Read.All", email="other@contoso.com"
        )

        with when("I sign in again, read-only, as someone else"):
            response = sign_in(context, read_only=True)

        with then("the same credential holds the new sign-in, marked as a new sign-in"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            second = sharepoint_secret(context)
            assert second is not None and second.content is not None
            assert_that(second.id, equal_to(first.id))
            content = decrypt_content(SecretProvider.SHAREPOINT, second.content, TEST_ENCRYPTION_KEY)
            assert isinstance(content, SharePointContent)
            assert_that(content.refresh_token, equal_to("rt-second"))
            assert_that(content.sign_in_id, is_not(equal_to(first_content.sign_in_id)))
            assert_that(response.json(), equal_to({"email": "other@contoso.com", "read_only": True}))


def test_sign_in_rejects_an_account_from_another_tenant() -> None:
    with given(_GIVEN) as context:
        fake_identity(context).exchange_result = tokens(tenant_id="99999999-9999-4999-8999-999999999999")

        with when("the sign-in comes back for a different organization"):
            response = sign_in(context)

        with then("it is refused and nothing is stored"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(sharepoint_secret(context), none())


def test_sign_in_accepts_the_teams_tenant_id_in_any_case() -> None:
    # Microsoft reports tid in lower case; the Teams connection keeps whatever was typed.
    given_upper = [*_GIVEN[:-1], there_is_a_teams_connection(tenant_id=TEAMS_TENANT_ID.upper())]
    with given(given_upper) as context:
        with when("I sign in"):
            response = sign_in(context)

        with then("it succeeds, and the credential keeps Microsoft's tenant id"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            secret = sharepoint_secret(context)
            assert secret is not None and secret.content is not None
            content = decrypt_content(SecretProvider.SHAREPOINT, secret.content, TEST_ENCRYPTION_KEY)
            assert isinstance(content, SharePointContent)
            assert_that(content.tenant_id, equal_to(TEAMS_TENANT_ID))


def test_sign_in_accepts_a_teams_tenant_given_as_a_domain() -> None:
    # The sign-in authority is already that organization, so the token's tenant is the right one.
    given_domain = [*_GIVEN[:-1], there_is_a_teams_connection(tenant_id="contoso.onmicrosoft.com")]
    with given(given_domain) as context:
        with when("I sign in"):
            response = sign_in(context)

        with then("it succeeds, and the credential stores the tenant id Microsoft reported"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            secret = sharepoint_secret(context)
            assert secret is not None and secret.content is not None
            content = decrypt_content(SecretProvider.SHAREPOINT, secret.content, TEST_ENCRYPTION_KEY)
            assert isinstance(content, SharePointContent)
            assert_that(content.tenant_id, equal_to(TEAMS_TENANT_ID))


def test_sign_in_rejects_a_teams_tenant_that_is_neither_a_guid_nor_a_domain() -> None:
    # A value like "organizations" or "common" is a multi-tenant authority, so the token could
    # come from any organization; only a GUID or a domain pins one.
    given_odd = [*_GIVEN[:-1], there_is_a_teams_connection(tenant_id="organizations")]
    with given(given_odd) as context:
        with when("I sign in through a Teams connection whose tenant names no organization"):
            response = sign_in(context)

        with then("it is refused and nothing is stored"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(sharepoint_secret(context), none())


def test_sign_in_rejects_a_grant_without_sharepoint_access() -> None:
    with given(_GIVEN) as context:
        fake_identity(context).exchange_result = tokens(scope="User.Read")

        with when("Microsoft grants less than SharePoint needs"):
            response = sign_in(context)

        with then("it is refused, pointing at administrator approval"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("administrator"))
            assert_that(sharepoint_secret(context), none())


def test_sign_in_rejects_a_response_without_a_refresh_token() -> None:
    with given(_GIVEN) as context:
        fake_identity(context).exchange_result = tokens(refresh_token=None)

        with when("Microsoft returns no refresh token"):
            response = sign_in(context)

        with then("nothing is stored, because the agent could not keep access"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(sharepoint_secret(context), none())


def test_sign_in_explains_the_app_settings_when_microsoft_wants_a_secret() -> None:
    with given(_GIVEN) as context:
        fake_identity(context).exchange_result = public_client_flows_off()

        with when("the Teams app isn't set up as a public client"):
            response = sign_in(context)

        with then("the message says exactly which settings to fix"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            detail = response.json()["detail"]
            assert_that(detail, contains_string("Mobile and desktop applications"))
            assert_that(detail, contains_string("Allow public client flows"))
            assert_that(detail, not_(contains_string("AADSTS")))


def test_sign_in_rejects_a_state_issued_to_someone_else() -> None:
    with given(_GIVEN) as context:
        owner_id = context.user.id
        there_is_a_user(
            name="Admin",
            email="second-admin@example.com",
            role=OrganizationRole.ADMIN,
            organization_id=context.organization.id,
        )(context)
        there_is_an_access_token_for_user()(context)

        with when("another user completes a sign-in that was started by the owner"):
            response = sign_in(context, user_id=owner_id)

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(sharepoint_secret(context), none())


def test_sign_in_rejects_a_forged_state() -> None:
    with given(_GIVEN) as context:
        with when("the state was not signed by this server"):
            response = context.client.post(
                f"{agent_base(context)}/integrations/sharepoint/sign-in",
                json={"code": "the-code", "state": "forged"},
                headers=auth(context),
            )

        with then("it is refused without contacting Microsoft"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(fake_identity(context).exchanges, equal_to([]))


# --- callback page ------------------------------------------------------------------


def test_the_callback_page_passes_code_and_state_to_the_opener() -> None:
    with given(_GIVEN) as context:
        state = sign_in_state(context)

        with when("Microsoft redirects the popup back"):
            response = _callback(context, code="c-1", state=state)

        with then("the page posts both to the opener, without needing a login"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.text, contains_string('"code": "c-1"'))
            assert_that(response.text, contains_string(f'"state": "{state}"'))


def test_the_callback_page_refuses_a_state_this_server_did_not_sign() -> None:
    with given(_GIVEN) as context:
        with when("the popup comes back with a forged state"):
            response = _callback(context, code="c-1", state="forged")

        with then("the code is not passed on"):
            assert_that(response.text, not_(contains_string("c-1")))
            assert_that(response.text, contains_string("expired"))


def test_the_callback_page_confirms_an_administrator_approval() -> None:
    with given(_GIVEN) as context:
        with when("Microsoft returns from the administrator approval link"):
            response = _callback(context, admin_consent="True", tenant=TEAMS_TENANT_ID)

        with then("the page says it's approved and tells the opener"):
            assert_that(response.text, contains_string("approved"))
            assert_that(response.text, contains_string('"adminConsent": true'))


def test_the_callback_page_says_when_an_administrator_must_approve() -> None:
    with given(_GIVEN) as context:
        with when("Microsoft reports that the organization requires administrator approval"):
            response = _callback(
                context,
                error="consent_required",
                error_description="AADSTS65001: The user or administrator has not consented to use the application.",
                state=sign_in_state(context),
            )

        with then("the user is told to ask an administrator, not just that it failed"):
            assert_that(response.text, contains_string("Microsoft 365 administrator"))
            assert_that(response.text, contains_string("approve"))
            assert_that(response.text, not_(contains_string("AADSTS")))


def test_the_callback_page_recognises_an_admin_consent_request() -> None:
    with given(_GIVEN) as context:
        with when("the user asked an administrator for approval through Microsoft"):
            response = _callback(
                context,
                error="access_denied",
                error_description="AADSTS90094: The grant requires admin permission.",
                state=sign_in_state(context),
            )

        with then("they are told approval is needed before signing in again"):
            assert_that(response.text, contains_string("Microsoft 365 administrator"))


def test_the_callback_page_treats_a_declined_consent_as_cancelled() -> None:
    with given(_GIVEN) as context:
        with when("the user declines the consent screen"):
            response = _callback(
                context,
                error="access_denied",
                error_description="AADSTS65004: User declined to consent to access the app.",
                state=sign_in_state(context),
            )

        with then("it reads as cancelled, with no mention of administrators"):
            assert_that(response.text, contains_string("cancelled"))
            assert_that(response.text, not_(contains_string("administrator")))


# --- other paths --------------------------------------------------------------------


def test_the_generic_secret_path_cannot_write_a_sharepoint_credential() -> None:
    with given(_GIVEN) as context:
        with when("someone tries to save SharePoint content directly"):
            response = context.client.patch(
                agent_base(context),
                json={
                    "secrets": [
                        {
                            "provider": "sharepoint",
                            "content": {
                                "connection_id": context.teams_connection["id"],
                                "tenant_id": TEAMS_TENANT_ID,
                                "client_id": TEAMS_APP_ID,
                                "email": "someone@contoso.com",
                                "refresh_token": "rt",
                                "sign_in_id": "0199c2a4-7b1e-7c3d-9f00-000000000001",
                            },
                        }
                    ]
                },
                headers=auth(context),
            )

        with then("it is refused; SharePoint is only connected by signing in"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))
            assert_that(sharepoint_secret(context), none())


def test_the_credential_can_be_removed() -> None:
    with given(_GIVEN) as context:
        sign_in(context)

        with when("SharePoint is removed from the agent"):
            response = context.client.patch(
                agent_base(context),
                json={"removed_secret_providers": ["sharepoint"]},
                headers=auth(context),
            )

        with then("the sign-in is gone"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(sharepoint_secret(context), none())
