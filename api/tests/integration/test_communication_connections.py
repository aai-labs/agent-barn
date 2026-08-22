from uuid import UUID

from fastapi import status
from hamcrest import assert_that, contains_inanyorder, equal_to, has_entries, has_key, not_
from starlette.testclient import TestClient

from api.domains.communications.repository import CommunicationConnectionRepository
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
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

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "SKIP_SLACK_TOKEN_VALIDATION": "true",
            "SKIP_TELEGRAM_TOKEN_VALIDATION": "true",
            "SKIP_DISCORD_TOKEN_VALIDATION": "true",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_an_agent(),
]


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _base(context) -> str:
    return f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections"


def _teams_payload(name: str = "Community Teams", app_id: str = "app-one") -> dict:
    return {
        "platform_key": "teams",
        "display_name": name,
        "settings": {"tenant_id": "tenant-one"},
        "credentials": {"app_id": app_id, "app_password": "secret"},
    }


def test_platform_catalog_lists_the_shipped_plugins() -> None:
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I list the shipped Communication Platforms"):
            response = client.get(
                f"/api/v1/organizations/{context.organization.id}/communication-platforms",
                headers=_auth(context),
            )

        with then("the stable plugin catalogue is returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                [item["key"] for item in response.json()],
                contains_inanyorder("discord", "slack", "teams", "telegram"),
            )


def test_agent_can_have_multiple_connections_for_the_same_platform() -> None:
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create two Teams connections"):
            first = client.post(_base(context), json=_teams_payload(), headers=_auth(context))
            second = client.post(
                _base(context),
                json=_teams_payload("Partner Teams", "app-two"),
                headers=_auth(context),
            )
            listed = client.get(_base(context), headers=_auth(context))

        with then("both connections belong to the Agent without exposing credentials"):
            assert_that(first.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(second.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(listed.status_code, equal_to(status.HTTP_200_OK))
            assert_that(len(listed.json()), equal_to(2))
            assert_that(first.json(), has_entries(platform_key="teams", display_name="Community Teams", revision=1))
            assert_that(first.json(), not_(has_key("credentials")))


def test_duplicate_active_connection_name_returns_conflict() -> None:
    with given(_GIVEN) as context:
        client: TestClient = context.client
        client.post(_base(context), json=_teams_payload(), headers=_auth(context))

        with when("I reuse the active display name with different casing"):
            response = client.post(
                _base(context),
                json=_teams_payload("community teams", "app-two"),
                headers=_auth(context),
            )

        with then("the database-backed invariant returns a conflict"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_stale_connection_update_returns_conflict() -> None:
    with given(_GIVEN) as context:
        client: TestClient = context.client
        created = client.post(_base(context), json=_teams_payload(), headers=_auth(context)).json()
        url = f"{_base(context)}/{created['id']}"
        current = client.patch(
            url,
            json={"revision": 1, "display_name": "Updated Teams"},
            headers=_auth(context),
        )

        with when("I update using the superseded revision"):
            stale = client.patch(
                url,
                json={"revision": 1, "enabled": False},
                headers=_auth(context),
            )

        with then("optimistic concurrency rejects the stale write"):
            assert_that(current.status_code, equal_to(status.HTTP_200_OK))
            assert_that(current.json()["revision"], equal_to(2))
            assert_that(stale.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_ingress_lease_allows_only_one_gateway_replica() -> None:
    with given(_GIVEN) as context:
        created = context.client.post(_base(context), json=_teams_payload(), headers=_auth(context)).json()
        connection_id = UUID(created["id"])
        repository = context.injector.get(CommunicationConnectionRepository)

        with when("two gateway replicas contend for one Connection"):
            first = repository.claim_ingress_lease(connection_id, "gateway-a")
            second = repository.claim_ingress_lease(connection_id, "gateway-b")
            repository.release_ingress_lease(connection_id, "gateway-a")
            after_release = repository.claim_ingress_lease(connection_id, "gateway-b")

        with then("the lease serializes provider ownership and can be transferred"):
            assert_that(first, equal_to(True))
            assert_that(second, equal_to(False))
            assert_that(after_release, equal_to(True))
