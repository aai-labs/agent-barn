"""SharePoint limited to selected sites: an administrator's sign-in grants the agent's Teams app
each chosen site under Sites.Selected, and each later sign-in reconciles the grants."""

import urllib.parse

from fastapi import status
from hamcrest import assert_that, contains_string, empty, equal_to, has_entries, is_not, none, not_

from api.core.config import Config
from api.domains.agents.microsoft_graph_sites import SiteAccessRefused, SitesUnavailable
from api.domains.agents.models import SecretProvider, SharePointContent, decrypt_content
from api.domains.agents.sharepoint_service import decode_sign_in_state
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
    ADMIN_EMAIL,
    TEAMS_APP_ID,
    TEAMS_TENANT_ID,
    FakeMicrosoftIdentityModule,
    admin_tokens,
    agent_base,
    auth,
    fake_graph_sites,
    fake_identity,
    replace_sharepoint_content,
    sharepoint_is_signed_in,
    sharepoint_secret,
    sign_in,
    site_id_for,
    sites_are_granted,
    there_is_a_teams_connection,
)

_FINANCE = "https://contoso.sharepoint.com/sites/finance"
_LEGAL = "https://contoso.sharepoint.com/sites/legal"
_OPS = "https://contoso.sharepoint.com/teams/ops"

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


def _sharepoint(context, path: str = "", **params):
    return context.client.get(
        f"{agent_base(context)}/integrations/sharepoint{path}",
        params={"connection_id": context.teams_connection["id"], **params},
        headers=auth(context),
    )


def _authorize_url(context, *sites: str, read_only: bool = False):
    return _sharepoint(
        context, "/authorize-url", mode="selected_sites", sites=list(sites), read_only=str(read_only).lower()
    )


def _admin_signs_in(context, *sites: str, read_only: bool = False):
    fake_identity(context).exchange_result = admin_tokens()
    return sign_in(context, read_only=read_only, sites=sites)


def _stored_grants_belong_to_another_app():
    def step(context):
        moved = _stored(context).model_copy(update={"client_id": "99999999-9999-4999-8999-999999999999"})
        replace_sharepoint_content(context, moved)

    return step


def _stored(context) -> SharePointContent:
    secret = sharepoint_secret(context)
    assert secret is not None and secret.content is not None
    content = decrypt_content(SecretProvider.SHAREPOINT, secret.content, TEST_ENCRYPTION_KEY)
    assert isinstance(content, SharePointContent)
    return content


# --- setup and authorize URL ---------------------------------------------------------


def test_setup_links_the_approval_of_the_apps_application_permissions() -> None:
    with given(_GIVEN) as context:
        with when("I ask what to set up on the agent's Teams app"):
            response = _sharepoint(context, "/setup")

        with then("there is an approval link for the application permissions listed on the app"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            url = response.json()["app_permission_consent_url"]
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
            assert_that(query, has_entries(client_id=TEAMS_APP_ID, scope="https://graph.microsoft.com/.default"))


def test_authorize_url_asks_the_administrator_for_site_administration_only_for_this_sign_in() -> None:
    with given(_GIVEN) as context:
        with when("I start the grant sign-in for two sites, one pasted from inside a library"):
            response = _authorize_url(context, f"{_FINANCE}/Shared%20Documents/Forms/AllItems.aspx", _LEGAL)

        with then("Microsoft is asked for site administration, with no lasting access"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            url = response.json()["authorize_url"]
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
            assert_that(query["scope"], contains_string("Sites.FullControl.All"))
            assert_that(query["scope"], not_(contains_string("offline_access")))

        with then("the sites to grant ride in the signed state, reduced to their roots"):
            state = decode_sign_in_state(query["state"], context.injector.get(Config))
            assert state is not None
            assert_that(state.mode, equal_to("selected_sites"))
            assert_that(state.sites, equal_to((_FINANCE, _LEGAL)))


def test_authorize_url_refuses_a_url_that_is_not_a_sharepoint_site() -> None:
    with given(_GIVEN) as context:
        with when("I start the grant sign-in with a URL outside SharePoint"):
            response = _authorize_url(context, "https://example.com/sites/finance")

        with then("it is refused, naming the URL"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("https://example.com/sites/finance"))


def test_authorize_url_needs_at_least_one_site() -> None:
    with given(_GIVEN) as context:
        with when("I start the grant sign-in with no sites"):
            response = _authorize_url(context)

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


# --- the administrator's sign-in ----------------------------------------------------


def test_the_administrators_sign_in_grants_each_site_and_keeps_no_token() -> None:
    with given(_GIVEN) as context:
        with when("an administrator signs in to grant two sites"):
            response = _admin_signs_in(context, _FINANCE, _LEGAL)

        with then("the Teams app is granted write access to each, with the administrator's token"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            grants = fake_graph_sites(context).grants
            assert_that(
                [(g["site_id"], g["app_id"], g["role"], g["token"]) for g in grants],
                equal_to(
                    [
                        (site_id_for(_FINANCE), TEAMS_APP_ID, "write", "admin-access-token"),
                        (site_id_for(_LEGAL), TEAMS_APP_ID, "write", "admin-access-token"),
                    ]
                ),
            )

        with then("the credential lists the sites and their grants, and holds no token"):
            content = _stored(context)
            assert_that(content.mode, equal_to("selected_sites"))
            assert_that(content.email, equal_to(ADMIN_EMAIL))
            assert_that(content.tenant_id, equal_to(TEAMS_TENANT_ID))
            assert_that(
                [(s.url, s.permission_id) for s in content.sites], equal_to([(_FINANCE, "perm-1"), (_LEGAL, "perm-2")])
            )
            assert_that(content.refresh_token, none())

        with then("the response says who granted which sites"):
            assert_that(
                response.json(),
                has_entries(email=ADMIN_EMAIL, mode="selected_sites", read_only=False, sites=[_FINANCE, _LEGAL]),
            )
            assert_that(response.text, not_(contains_string("admin-access-token")))


def test_a_read_only_grant_asks_for_the_read_role() -> None:
    with given(_GIVEN) as context:
        with when("an administrator grants a site read-only"):
            response = _admin_signs_in(context, _FINANCE, read_only=True)

        with then("the grant is for reading"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(fake_graph_sites(context).grants[0]["role"], equal_to("read"))


def test_signing_in_again_grants_added_sites_and_revokes_removed_ones() -> None:
    with given([*_GIVEN, sites_are_granted(_FINANCE, _LEGAL)]) as context:
        graph = fake_graph_sites(context)
        graph.grants.clear()

        with when("an administrator signs in again with legal removed and ops added"):
            response = _admin_signs_in(context, _FINANCE, _OPS)

        with then("only ops is granted and only legal's grant is removed"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that([g["site_id"] for g in graph.grants], equal_to([site_id_for(_OPS)]))
            assert_that(
                [(r["site_id"], r["permission_id"]) for r in graph.revokes],
                equal_to([(site_id_for(_LEGAL), "perm-2")]),
            )

        with then("the credential keeps finance's original grant beside ops' new one"):
            assert_that(
                [(s.url, s.permission_id) for s in _stored(context).sites],
                equal_to([(_FINANCE, "perm-1"), (_OPS, "perm-1")]),
            )


def test_changing_the_access_level_updates_each_kept_sites_grant_in_place() -> None:
    with given([*_GIVEN, sites_are_granted(_FINANCE)]) as context:
        graph = fake_graph_sites(context)
        graph.grants.clear()

        with when("an administrator signs in again for the same site, read-only"):
            response = _admin_signs_in(context, _FINANCE, read_only=True)

        with then("the existing grant becomes read-only, with no moment without access"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(
                graph.role_updates,
                equal_to([{"site_id": site_id_for(_FINANCE), "permission_id": "perm-1", "role": "read"}]),
            )
            assert_that(graph.grants, empty())
            assert_that(graph.revokes, empty())
            assert_that(_stored(context).read_only, equal_to(True))


def test_grants_made_for_a_previous_teams_app_are_replaced() -> None:
    with given([*_GIVEN, sites_are_granted(_FINANCE), _stored_grants_belong_to_another_app()]) as context:
        graph = fake_graph_sites(context)
        graph.grants.clear()

        with when("an administrator signs in again for the same site"):
            response = _admin_signs_in(context, _FINANCE)

        with then("the old app's grant is removed and the agent's current Teams app is granted"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that([r["permission_id"] for r in graph.revokes], equal_to(["perm-1"]))
            assert_that(
                [(g["site_id"], g["app_id"]) for g in graph.grants], equal_to([(site_id_for(_FINANCE), TEAMS_APP_ID)])
            )
            assert_that(_stored(context).client_id, equal_to(TEAMS_APP_ID))


def test_switching_from_a_personal_sign_in_replaces_it() -> None:
    with given([*_GIVEN, sharepoint_is_signed_in()]) as context:
        with when("an administrator grants selected sites"):
            response = _admin_signs_in(context, _FINANCE)

        with then("the agent now uses the selected sites, and the personal token is gone"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            content = _stored(context)
            assert_that(content.mode, equal_to("selected_sites"))
            assert_that(content.refresh_token, none())


def test_a_sign_in_without_site_administration_is_refused() -> None:
    with given(_GIVEN) as context:
        fake_identity(context).exchange_result = admin_tokens(scope="https://graph.microsoft.com/Sites.Read.All")

        with when("the sign-in comes back without permission to manage sites"):
            response = sign_in(context, sites=(_FINANCE,))

        with then("it is refused and nothing is granted or stored"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("administrator"))
            assert_that(fake_graph_sites(context).grants, empty())
            assert_that(sharepoint_secret(context), none())


def test_a_non_administrator_is_refused_and_earlier_grants_from_the_attempt_are_undone() -> None:
    with given(_GIVEN) as context:
        graph = fake_graph_sites(context)
        graph.grant_failures[site_id_for(_LEGAL)] = SiteAccessRefused("HTTP 403")

        with when("Microsoft refuses the second grant"):
            response = _admin_signs_in(context, _FINANCE, _LEGAL)

        with then("the sign-in is refused as needing an administrator"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(response.json()["detail"], contains_string("administrator"))

        with then("the first site's new grant is taken back and nothing is stored"):
            assert_that([r["permission_id"] for r in graph.revokes], equal_to(["perm-1"]))
            assert_that(sharepoint_secret(context), none())


def test_an_unknown_site_is_named_and_nothing_is_granted() -> None:
    with given(_GIVEN) as context:
        graph = fake_graph_sites(context)
        graph.unknown_sites.add(_LEGAL)

        with when("one of the sites doesn't exist"):
            response = _admin_signs_in(context, _FINANCE, _LEGAL)

        with then("the sign-in names it and grants nothing"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string(_LEGAL))
            assert_that(graph.grants, empty())


def test_a_grant_that_could_not_be_removed_is_kept_on_record_for_the_next_sign_in() -> None:
    with given([*_GIVEN, sites_are_granted(_FINANCE, _LEGAL)]) as context:
        graph = fake_graph_sites(context)
        graph.revoke_failures[site_id_for(_LEGAL)] = SitesUnavailable("HTTP 503")

        with when("legal is removed but Microsoft fails to remove its grant"):
            response = _admin_signs_in(context, _FINANCE)

        with then("the sign-in reports it, naming the site"):
            assert_that(response.status_code, equal_to(status.HTTP_502_BAD_GATEWAY))
            assert_that(response.json()["detail"], contains_string(_LEGAL))

        with then("legal stays on record, so the next sign-in removes it"):
            assert_that([s.url for s in _stored(context).sites], equal_to([_FINANCE, _LEGAL]))


def test_the_administrator_must_belong_to_the_teams_apps_organization() -> None:
    with given(_GIVEN) as context:
        fake_identity(context).exchange_result = admin_tokens(tenant_id="99999999-9999-4999-8999-999999999999")

        with when("an administrator of another organization signs in"):
            response = sign_in(context, sites=(_FINANCE,))

        with then("it is refused before anything is granted"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(fake_graph_sites(context).grants, empty())


# --- reading the current state --------------------------------------------------------


def test_the_current_sites_can_be_read_back() -> None:
    with given([*_GIVEN, sites_are_granted(_FINANCE, _LEGAL)]) as context:
        with when("I read the agent's SharePoint access"):
            response = context.client.get(f"{agent_base(context)}/integrations/sharepoint", headers=auth(context))

        with then("I see the mode, who granted it and the sites, and no grant ids"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(
                response.json(),
                equal_to(
                    {"email": ADMIN_EMAIL, "mode": "selected_sites", "read_only": False, "sites": [_FINANCE, _LEGAL]}
                ),
            )
            assert_that(response.text, is_not(contains_string("perm-")))


def test_reading_without_sharepoint_says_not_connected() -> None:
    with given(_GIVEN) as context:
        with when("I read the SharePoint access of an agent without it"):
            response = context.client.get(f"{agent_base(context)}/integrations/sharepoint", headers=auth(context))

        with then("it is not found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
