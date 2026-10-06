from datetime import UTC, datetime, timedelta
from uuid import uuid7

from hamcrest import assert_that, equal_to, has_entries

from api.domains.api_keys.repository import ApiKeyRepository
from api.domains.api_keys.service import hash_token
from api.domains.events.repository import OutboxMessageRepository
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user


def _setup(*, platform_admin: bool = False):
    return given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(email="key-user@example.com", is_platform_admin=platform_admin, organization_id=uuid7()),
            there_is_an_access_token_for_user(),
        ]
    )


def _create(context, mode="READ_ONLY", expires_at=None):
    body = {"name": "Automation", "access_mode": mode}
    if expires_at is not None:
        body["expires_at"] = expires_at
    return context.client.post(
        "/api/v1/auth/me/api-keys",
        json=body,
        headers={"Authorization": f"Bearer {context.access_token}"},
    )


def test_key_is_stored_as_hash_and_authenticates_reads():
    with _setup() as context:
        response = _create(context)
        assert_that(response.status_code, equal_to(201))
        token = response.json()["token"]
        key = context.injector.get(ApiKeyRepository).get_by_hash(hash_token(token))
        assert_that(key is not None, equal_to(True))
        assert_that(key.token_hash == token, equal_to(False))
        assert_that(
            context.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code,
            equal_to(200),
        )


def test_read_only_key_cannot_write_but_full_key_can():
    with _setup() as context:
        read_token = _create(context).json()["token"]
        full_token = _create(context, "FULL").json()["token"]
        endpoint = "/api/v1/auth/me/api-keys"
        assert_that(
            context.client.post(
                endpoint, json={"name": "child"}, headers={"Authorization": f"Bearer {read_token}"}
            ).status_code,
            equal_to(403),
        )
        assert_that(
            context.client.post(
                endpoint, json={"name": "child"}, headers={"Authorization": f"Bearer {full_token}"}
            ).status_code,
            equal_to(201),
        )


def test_revoke_invalidates_key_and_emits_audit_event():
    with _setup() as context:
        created = _create(context).json()
        token = created["token"]
        response = context.client.delete(
            f"/api/v1/auth/me/api-keys/{created['api_key']['id']}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(204))
        assert_that(
            context.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code,
            equal_to(401),
        )
        event = context.injector.get(OutboxMessageRepository).get_latest()
        assert_that(event.event_name, equal_to("api_key.revoked"))


def test_expired_key_is_rejected():
    with _setup() as context:
        created = _create(context, expires_at=(datetime.now(UTC) + timedelta(minutes=1)).isoformat()).json()
        key = context.injector.get(ApiKeyRepository).get_by_hash(hash_token(created["token"]))
        key.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        context.injector.get(ApiKeyRepository).delegate.save(key)
        assert_that(
            context.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {created['token']}"}).status_code,
            equal_to(401),
        )


def test_platform_admin_full_key_can_read_platform_routes():
    with _setup(platform_admin=True) as context:
        token = _create(context, "FULL").json()["token"]
        response = context.client.get("/api/v1/platform/users", headers={"Authorization": f"Bearer {token}"})
        assert_that(response.status_code, equal_to(200))
        assert_that(response.json(), has_entries(page=1))


def test_key_context_lists_current_memberships_and_discovery_is_public():
    with _setup() as context:
        token = _create(context).json()["token"]
        response = context.client.get("/api/v1/auth/context", headers={"Authorization": f"Bearer {token}"})
        assert_that(response.status_code, equal_to(200))
        assert_that(response.json()["api_key_access_mode"], equal_to("READ_ONLY"))
        assert_that(response.json()["organizations"][0]["organization_id"], equal_to(str(context.organization.id)))
        discovery = context.client.get("/api/v1/discovery")
        assert_that(discovery.status_code, equal_to(200))
        assert_that(
            any(item["path"] == "/organizations/{organization_id}/agents" for item in discovery.json()["operations"]),
            equal_to(True),
        )
        create_agent = next(
            item
            for item in discovery.json()["operations"]
            if item["path"] == "/organizations/{organization_id}/agents" and item["method"] == "POST"
        )
        assert_that(create_agent["api_key_access_mode"], equal_to("FULL"))
        assert_that(create_agent["scope"], equal_to("organization"))
        assert_that(bool(create_agent["security"]), equal_to(True))
        assert_that(context.client.get("/api/v1/llms.txt").status_code, equal_to(200))
        assert_that(context.client.get("/api/v1/developer/quickstart.md").status_code, equal_to(200))


def test_key_is_invalidated_by_password_security_stamp_change():
    with _setup() as context:
        token = _create(context).json()["token"]
        context.user.security_stamp = uuid7().hex
        context.injector.get(ApiKeyRepository).delegate.save(context.user)
        response = context.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert_that(response.status_code, equal_to(401))


def test_one_key_uses_current_memberships_across_organizations():
    first_org = uuid7()
    second_org = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(email="multi-key@example.com", organization_id=first_org),
            there_is_a_user(email="multi-key@example.com", organization_id=second_org),
            there_is_an_access_token_for_user(),
        ]
    ) as context:
        token = _create(context).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert_that(
            context.client.get(f"/api/v1/organizations/{first_org}", headers=headers).status_code, equal_to(200)
        )
        assert_that(
            context.client.get(f"/api/v1/organizations/{second_org}", headers=headers).status_code, equal_to(200)
        )
        assert_that(context.client.get(f"/api/v1/organizations/{uuid7()}", headers=headers).status_code, equal_to(403))
        assert_that(context.client.get("/api/v1/platform/users", headers=headers).status_code, equal_to(403))


def test_malformed_key_returns_401():
    with _setup() as context:
        response = context.client.get("/api/v1/auth/me", headers={"Authorization": "Bearer abk_%%%%"})
        assert_that(response.status_code, equal_to(401))


def test_key_creation_rejects_whitespace_name_and_naive_expiration():
    with _setup() as context:
        headers = {"Authorization": f"Bearer {context.access_token}"}
        name_response = context.client.post(
            "/api/v1/auth/me/api-keys",
            json={"name": "   "},
            headers=headers,
        )
        assert_that(name_response.status_code, equal_to(422))
        expiry_response = context.client.post(
            "/api/v1/auth/me/api-keys",
            json={"name": "Bad expiry", "expires_at": "2099-01-01T00:00:00"},
            headers=headers,
        )
        assert_that(expiry_response.status_code, equal_to(422))


def test_key_management_is_owner_scoped():
    with _setup() as context:
        created = _create(context).json()
        there_is_a_user(email="another-key-user@example.com", organization_id=uuid7())(context)
        there_is_an_access_token_for_user()(context)
        headers = {"Authorization": f"Bearer {context.access_token}"}
        listed = context.client.get("/api/v1/auth/me/api-keys", headers=headers)
        assert_that(listed.status_code, equal_to(200))
        assert_that(listed.json(), equal_to([]))
        revoke = context.client.delete(f"/api/v1/auth/me/api-keys/{created['api_key']['id']}", headers=headers)
        assert_that(revoke.status_code, equal_to(404))
