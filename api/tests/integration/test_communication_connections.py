from uuid import UUID

from fastapi import status
from hamcrest import all_of, assert_that, contains_inanyorder, contains_string, equal_to, has_entries, has_key, not_
from starlette.testclient import TestClient

from api.domains.communications.repository import CommunicationConnectionRepository
from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.organization_users.repository import OrganizationUserRepository
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
    there_is_agent_access,
    there_is_an_agent,
    there_is_an_agent_in_another_org,
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


def _discord_payload(name: str = "Community Discord", bot_token: str = "token-one") -> dict:
    return {
        "platform_key": "discord",
        "display_name": name,
        "settings": {"guild_ids": ["guild-one"]},
        "credentials": {"bot_token": bot_token},
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
            catalogue = response.json()
            assert_that(
                [item["key"] for item in catalogue],
                contains_inanyorder("discord", "slack", "telegram"),
            )
            slack = next(item for item in catalogue if item["key"] == "slack")
            assert_that(
                slack["setup_hint"],
                all_of(
                    contains_string("channels:read"),
                    contains_string("groups:read"),
                    contains_string("im:read"),
                    contains_string("mpim:read"),
                    contains_string("users:read"),
                ),
            )


def test_list_connections_without_authentication_returns_401() -> None:
    with given(_GIVEN) as context:
        with when("I list Communication Connections without a token"):
            response = context.client.get(_base(context))

        with then("authentication is required"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_create_connection_rejects_unknown_platform() -> None:
    with given(_GIVEN) as context:
        payload = _discord_payload()
        payload["platform_key"] = "carrier-pigeon"

        with when("I create a Connection for a plugin that is not shipped"):
            response = context.client.post(_base(context), json=payload, headers=_auth(context))

        with then("the platform key fails domain validation"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_create_connection_rejects_incomplete_payload() -> None:
    with given(_GIVEN) as context:
        with when("I omit the required credentials"):
            response = context.client.post(
                _base(context),
                json={"platform_key": "discord", "display_name": "Incomplete"},
                headers=_auth(context),
            )

        with then("request validation reports the missing field"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_create_connection_requires_agent_update_permission() -> None:
    with given(_GIVEN) as context:
        context.organization_user.role = OrganizationRole.MEMBER
        context.injector.get(OrganizationUserRepository).save(context.organization_user)
        there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID)(context)

        with when("I create a Connection without Agent update permission"):
            response = context.client.post(
                _base(context),
                json=_discord_payload(),
                headers=_auth(context),
            )

        with then("the visible Agent rejects the mutation"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_other_organization_agent_is_hidden() -> None:
    with given([*_GIVEN, there_is_an_agent_in_another_org()]) as context:
        with when("I list Connections through the original Organization route"):
            response = context.client.get(_base(context), headers=_auth(context))

        with then("the cross-Organization Agent is hidden"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_agent_can_have_multiple_connections_for_the_same_platform() -> None:
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create two Discord connections"):
            first = client.post(_base(context), json=_discord_payload(), headers=_auth(context))
            second = client.post(
                _base(context),
                json=_discord_payload("Partner Discord", "token-two"),
                headers=_auth(context),
            )
            listed = client.get(_base(context), headers=_auth(context))

        with then("both connections belong to the Agent without exposing credentials"):
            assert_that(first.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(second.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(listed.status_code, equal_to(status.HTTP_200_OK))
            assert_that(len(listed.json()), equal_to(2))
            assert_that(first.json(), has_entries(platform_key="discord", display_name="Community Discord", revision=1))
            assert_that(first.json(), not_(has_key("credentials")))


def test_duplicate_active_connection_name_returns_conflict() -> None:
    with given(_GIVEN) as context:
        client: TestClient = context.client
        client.post(_base(context), json=_discord_payload(), headers=_auth(context))

        with when("I reuse the active display name with different casing"):
            response = client.post(
                _base(context),
                json=_discord_payload("community discord", "token-two"),
                headers=_auth(context),
            )

        with then("the database-backed invariant returns a conflict"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_stale_connection_update_returns_conflict() -> None:
    with given(_GIVEN) as context:
        client: TestClient = context.client
        created = client.post(_base(context), json=_discord_payload(), headers=_auth(context)).json()
        url = f"{_base(context)}/{created['id']}"
        current = client.patch(
            url,
            json={"revision": 1, "display_name": "Updated Discord"},
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


def test_connection_settings_name_and_credentials_can_be_updated() -> None:
    with given(_GIVEN) as context:
        client: TestClient = context.client
        created = client.post(_base(context), json=_discord_payload(), headers=_auth(context)).json()

        with when("I update every editable schema-driven field"):
            response = client.patch(
                f"{_base(context)}/{created['id']}",
                json={
                    "revision": created["revision"],
                    "display_name": "Renamed Discord",
                    "settings": {"guild_ids": ["guild-two"]},
                    "credentials": {"bot_token": "rotated-token"},
                },
                headers=_auth(context),
            )

        with then("the public configuration changes without exposing credentials"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                response.json(),
                has_entries(
                    display_name="Renamed Discord",
                    settings={
                        "guild_ids": ["guild-two"],
                        "allowed_channel_ids": [],
                        "allowed_user_ids": [],
                        "allowed_role_ids": [],
                        "group_policy": "allowlist",
                        "dm_policy": "off",
                        "require_mention": True,
                        "home_channel_id": None,
                    },
                    external_identity="validation-skipped",
                    revision=2,
                ),
            )
            assert_that(response.json(), not_(has_key("credentials")))


def test_unknown_connection_update_returns_404() -> None:
    with given(_GIVEN) as context:
        with when("I update a Connection that does not exist"):
            response = context.client.patch(
                f"{_base(context)}/00000000-0000-0000-0000-000000000099",
                json={"revision": 1, "enabled": False},
                headers=_auth(context),
            )

        with then("the subordinate resource is hidden as not found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_ingress_lease_allows_only_one_gateway_replica() -> None:
    with given(_GIVEN) as context:
        created = context.client.post(_base(context), json=_discord_payload(), headers=_auth(context)).json()
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
