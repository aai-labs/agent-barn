"""The pod-facing SharePoint token endpoint for selected-sites mode: an agent trades its ingest key
for a short-lived app-only Microsoft token. The Teams app's secret never leaves the API."""

from datetime import UTC, datetime, timedelta

from fastapi import status
from hamcrest import assert_that, contains_string, equal_to, has_entries, has_length, not_

from api.domains.agents.microsoft_identity import MicrosoftIdentityError, MicrosoftIdentityUnavailable
from api.domains.agents.repository import AgentRepository
from api.infrastructure.crypto import encrypt_token
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_ingest_server,
    prepare_injector,
    set_env_variable,
)
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
    TEAMS_APP_ID,
    TEAMS_APP_PASSWORD,
    TEAMS_TENANT_ID,
    FakeMicrosoftIdentityModule,
    agent_base,
    app_tokens,
    auth,
    fake_identity,
    sharepoint_is_signed_in,
    sites_are_granted,
    there_is_a_teams_connection,
)

_INGEST_KEY = "test-ingest-key-abc"
_FINANCE = "https://contoso.sharepoint.com/sites/finance"


def _agent_has_an_ingest_key():
    def step(context):
        repository: AgentRepository = context.injector.get(AgentRepository)
        agent = repository.get_by_id(context.agent.id)
        assert agent is not None
        agent.ingest_key_encrypted = encrypt_token(_INGEST_KEY, TEST_ENCRYPTION_KEY)
        repository.save(agent)

    return step


_BASE = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "SKIP_TEAMS_TOKEN_VALIDATION": "true",
            "WEB_APP_URL": "https://farm.example.com",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), FakeMicrosoftIdentityModule()]),
    prepare_api_server(),
    create_test_client(),
    prepare_ingest_server(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_an_agent(),
    _agent_has_an_ingest_key(),
    there_is_a_teams_connection(),
]
_GRANTED = [*_BASE, sites_are_granted(_FINANCE)]


def _request_token(context, key: str = _INGEST_KEY):
    return context.ingest_client.post(
        f"/ingest/v1/agents/{context.agent.id}/integrations/sharepoint/token",
        headers={"Authorization": f"Bearer {key}"},
    )


def test_a_wrong_ingest_key_is_rejected() -> None:
    with given(_GRANTED) as context:
        with when("the pod presents the wrong key"):
            response = _request_token(context, key="not-the-key")

        with then("it is unauthorised and Microsoft is not contacted"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
            assert_that(fake_identity(context).app_token_requests, equal_to([]))


def test_an_agent_without_sharepoint_is_told_to_connect_it() -> None:
    with given(_BASE) as context:
        with when("the agent asks for a token before any site was granted"):
            response = _request_token(context)

        with then("it is not found, with a message the agent can relay"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(response.json()["detail"], contains_string("isn't connected"))


def test_an_agent_on_a_personal_sign_in_gets_no_app_token() -> None:
    with given([*_BASE, sharepoint_is_signed_in()]) as context:
        with when("an agent whose SharePoint is a personal sign-in asks for a token"):
            response = _request_token(context)

        with then("it is refused: app-only tokens are only for selected sites"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(fake_identity(context).app_token_requests, equal_to([]))


def test_the_token_is_minted_with_the_teams_apps_credentials() -> None:
    with given(_GRANTED) as context:
        with when("the agent asks for a token"):
            response = _request_token(context)

        with then("it gets an app-only token and when it expires, and nothing else"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            body = response.json()
            assert_that(body, has_entries(access_token="app-only-token"))
            expires_at = datetime.fromisoformat(body["expires_at"])
            assert_that(expires_at > datetime.now(UTC) + timedelta(minutes=50), equal_to(True))
            assert_that(response.text, not_(contains_string(TEAMS_APP_PASSWORD)))

        with then("the token came from the agent's Teams app"):
            assert_that(
                fake_identity(context).app_token_requests,
                equal_to(
                    [{"tenant_id": TEAMS_TENANT_ID, "client_id": TEAMS_APP_ID, "client_secret": TEAMS_APP_PASSWORD}]
                ),
            )


def test_a_still_valid_token_is_reused() -> None:
    with given(_GRANTED) as context:
        _request_token(context)

        with when("the agent asks again straight away"):
            response = _request_token(context)

        with then("the same token comes back without asking Microsoft again"):
            assert_that(response.json()["access_token"], equal_to("app-only-token"))
            assert_that(fake_identity(context).app_token_requests, has_length(1))


def test_a_token_about_to_expire_is_replaced() -> None:
    with given(_GRANTED) as context:
        identity = fake_identity(context)
        identity.app_token_result = app_tokens("short-lived", expires_in=120)
        _request_token(context)
        identity.app_token_result = app_tokens("fresh")

        with when("the agent asks for a token while the cached one has two minutes left"):
            response = _request_token(context)

        with then("a new one is fetched rather than handing out one about to lapse"):
            assert_that(response.json()["access_token"], equal_to("fresh"))
            assert_that(identity.app_token_requests, has_length(2))


def test_microsoft_refusing_the_teams_app_is_a_conflict_to_fix_in_setup() -> None:
    with given(_GRANTED) as context:
        fake_identity(context).app_token_result = MicrosoftIdentityError("invalid_client", "AADSTS7000215")

        with when("Microsoft rejects the Teams app's credentials"):
            response = _request_token(context)

        with then("the agent is told the app's setup needs attention"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(response.json()["detail"], contains_string("Teams app"))


def test_microsoft_being_unreachable_is_a_bad_gateway() -> None:
    with given(_GRANTED) as context:
        fake_identity(context).app_token_result = MicrosoftIdentityUnavailable("timed out")

        with when("Microsoft can't be reached"):
            response = _request_token(context)

        with then("the agent can retry later"):
            assert_that(response.status_code, equal_to(status.HTTP_502_BAD_GATEWAY))


def test_a_disabled_teams_connection_stops_token_issue() -> None:
    with given(_GRANTED) as context:
        connection = context.teams_connection
        disabled = context.client.patch(
            f"{agent_base(context)}/connections/{connection['id']}",
            json={"enabled": False, "revision": connection["revision"]},
            headers=auth(context),
        )
        assert disabled.status_code == status.HTTP_200_OK, disabled.text

        with when("the agent asks for a token"):
            response = _request_token(context)

        with then("it is refused until the connection is turned on again"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(fake_identity(context).app_token_requests, equal_to([]))
