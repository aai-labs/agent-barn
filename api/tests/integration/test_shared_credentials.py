from fastapi import status
from hamcrest import assert_that, equal_to, has_item, not_
from starlette.testclient import TestClient

from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    MockK8sModule,
    MockLiteLLMModule,
    TEST_ENCRYPTION_KEY,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)

_BASE = "/api/v1/shared-credentials"

_JIRA_CONTENT = {
    "site_url": "https://test.atlassian.net",
    "email": "admin@example.com",
    "api_token": "test-jira-token",
}

_GITHUB_CONTENT = {
    "token": "ghp_test_token_12345",
    "owner": "test-org",
    "org": "test-org",
    "repos": [],
}

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


# --- Create ---


def test_create_shared_credential_returns_201():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a shared credential"):
            response = client.post(
                _BASE,
                json={
                    "provider": "jira",
                    "name": "Production Jira",
                    "content": _JIRA_CONTENT,
                },
                headers=_auth(context),
            )

        with then("it returns 201 with the credential metadata"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["name"], equal_to("Production Jira"))
            assert_that(body["provider"], equal_to("jira"))
            assert_that(body["organization_id"], equal_to(str(context.organization.id)))
            assert_that(body["agent_count"], equal_to(0))
            assert "content" not in body


def test_create_shared_credential_rejects_oauth_provider():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I try to create a shared credential for Gmail (OAuth provider)"):
            response = client.post(
                _BASE,
                json={
                    "provider": "gmail",
                    "name": "Shared Gmail",
                    "content": {
                        "client_id": "",
                        "client_secret": "",
                        "refresh_token": "tok",
                    },
                },
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_create_shared_credential_rejects_invalid_content():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a shared credential with invalid content"):
            response = client.post(
                _BASE,
                json={
                    "provider": "jira",
                    "name": "Bad Jira",
                    "content": {"wrong_field": "value"},
                },
                headers=_auth(context),
            )

        with then("it returns 422"):
            assert_that(
                response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY)
            )


def test_create_shared_credential_rejects_duplicate_name():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create two shared credentials with the same name"):
            client.post(
                _BASE,
                json={
                    "provider": "jira",
                    "name": "Duplicate Name",
                    "content": _JIRA_CONTENT,
                },
                headers=_auth(context),
            )
            response = client.post(
                _BASE,
                json={
                    "provider": "github",
                    "name": "Duplicate Name",
                    "content": _GITHUB_CONTENT,
                },
                headers=_auth(context),
            )

        with then("the second create fails with 409"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_create_shared_credential_without_auth_returns_401():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a shared credential without auth"):
            response = client.post(
                _BASE,
                json={
                    "provider": "jira",
                    "name": "No Auth",
                    "content": _JIRA_CONTENT,
                },
            )

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


# --- List ---


def test_list_shared_credentials_returns_200():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create two credentials and list them"):
            client.post(
                _BASE,
                json={
                    "provider": "jira",
                    "name": "Jira Prod",
                    "content": _JIRA_CONTENT,
                },
                headers=_auth(context),
            )
            client.post(
                _BASE,
                json={
                    "provider": "github",
                    "name": "GitHub Prod",
                    "content": _GITHUB_CONTENT,
                },
                headers=_auth(context),
            )
            response = client.get(_BASE, headers=_auth(context))

        with then("both credentials are returned with pagination"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            names = [c["name"] for c in body["items"]]
            assert_that(names, has_item("Jira Prod"))
            assert_that(names, has_item("GitHub Prod"))
            assert_that(body["total"], equal_to(2))


def test_list_shared_credentials_search_filter():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create credentials and search by name"):
            client.post(
                _BASE,
                json={
                    "provider": "jira",
                    "name": "Jira Prod",
                    "content": _JIRA_CONTENT,
                },
                headers=_auth(context),
            )
            client.post(
                _BASE,
                json={
                    "provider": "github",
                    "name": "GitHub Prod",
                    "content": _GITHUB_CONTENT,
                },
                headers=_auth(context),
            )
            response = client.get(
                _BASE, params={"search": "jira"}, headers=_auth(context)
            )

        with then("only matching credentials are returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            names = [c["name"] for c in body["items"]]
            assert_that(names, has_item("Jira Prod"))
            assert_that(names, not_(has_item("GitHub Prod")))
            assert_that(body["total"], equal_to(1))


def test_list_shared_credentials_provider_filter():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create credentials and filter by provider"):
            client.post(
                _BASE,
                json={
                    "provider": "jira",
                    "name": "Jira Prod",
                    "content": _JIRA_CONTENT,
                },
                headers=_auth(context),
            )
            client.post(
                _BASE,
                json={
                    "provider": "github",
                    "name": "GitHub Prod",
                    "content": _GITHUB_CONTENT,
                },
                headers=_auth(context),
            )
            response = client.get(
                _BASE, params={"provider": "github"}, headers=_auth(context)
            )

        with then("only matching credentials are returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            names = [c["name"] for c in body["items"]]
            assert_that(names, has_item("GitHub Prod"))
            assert_that(names, not_(has_item("Jira Prod")))


# --- Get ---


def test_get_shared_credential_returns_200():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create and then get a credential"):
            create_resp = client.post(
                _BASE,
                json={
                    "provider": "jira",
                    "name": "Jira Prod",
                    "content": _JIRA_CONTENT,
                },
                headers=_auth(context),
            )
            cred_id = create_resp.json()["id"]
            response = client.get(f"{_BASE}/{cred_id}", headers=_auth(context))

        with then("it returns 200 with the credential data"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["name"], equal_to("Jira Prod"))


def test_get_nonexistent_shared_credential_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I get a non-existent credential"):
            from uuid import uuid4

            response = client.get(f"{_BASE}/{uuid4()}", headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


# --- Update ---


def test_update_shared_credential_name_returns_200():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create and then rename a credential"):
            create_resp = client.post(
                _BASE,
                json={
                    "provider": "jira",
                    "name": "Old Name",
                    "content": _JIRA_CONTENT,
                },
                headers=_auth(context),
            )
            cred_id = create_resp.json()["id"]
            response = client.patch(
                f"{_BASE}/{cred_id}",
                json={"name": "New Name"},
                headers=_auth(context),
            )

        with then("it returns 200 with the updated name"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["name"], equal_to("New Name"))


def test_update_shared_credential_content_returns_200():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create and then update content"):
            create_resp = client.post(
                _BASE,
                json={
                    "provider": "jira",
                    "name": "Jira Prod",
                    "content": _JIRA_CONTENT,
                },
                headers=_auth(context),
            )
            cred_id = create_resp.json()["id"]
            response = client.patch(
                f"{_BASE}/{cred_id}",
                json={
                    "content": {
                        "site_url": "https://new.atlassian.net",
                        "email": "new@example.com",
                        "api_token": "new-token",
                    }
                },
                headers=_auth(context),
            )

        with then("it returns 200"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))


# --- Delete ---


def test_delete_shared_credential_returns_204():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create and then delete a credential"):
            create_resp = client.post(
                _BASE,
                json={
                    "provider": "jira",
                    "name": "To Delete",
                    "content": _JIRA_CONTENT,
                },
                headers=_auth(context),
            )
            cred_id = create_resp.json()["id"]
            response = client.delete(f"{_BASE}/{cred_id}", headers=_auth(context))

        with then("it returns 204"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))


def test_delete_nonexistent_shared_credential_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I delete a non-existent credential"):
            from uuid import uuid4

            response = client.delete(f"{_BASE}/{uuid4()}", headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


# --- Briefs ---


def test_list_briefs_returns_200():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create credentials and list briefs"):
            client.post(
                _BASE,
                json={
                    "provider": "jira",
                    "name": "Jira Prod",
                    "content": _JIRA_CONTENT,
                },
                headers=_auth(context),
            )
            response = client.get(f"{_BASE}/briefs", headers=_auth(context))

        with then("it returns a flat list of briefs"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(len(body), equal_to(1))
            assert_that(body[0]["name"], equal_to("Jira Prod"))
            assert "agent_count" not in body[0]
