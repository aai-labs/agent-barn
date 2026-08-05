from unittest.mock import patch
from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, contains_string, equal_to, is_not, none
from starlette.testclient import TestClient

from api.domains.events.catalog import ORGANIZATION_MODEL_ALLOWLIST_CHANGED
from api.domains.events.models import OutboxMessage
from api.domains.events.processor import EventDeliveryProcessor
from api.domains.events.repository import OutboxMessageRepository
from api.domains.events.security_audit import SecurityAuditRepository
from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
)
from api.tests.steps.agent import MockK8sModule, MockLiteLLMModule
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user


def _outbox_messages(context) -> list[OutboxMessage]:
    return context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)


def test_update_organization_with_invalid_model_id_is_rejected():
    org_a = uuid7()
    owner_a = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=owner_a,
                email="owner-update-models@example.com",
                organization_id=org_a,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_a),
        ]
    ) as context:
        client: TestClient = context.client
        with patch("api.infrastructure.openrouter.client.OpenRouterClient.list_models") as mock_list_models:
            mock_list_models.return_value = [{"id": "openai/gpt-4o"}]
            response = client.patch(
                f"/api/v1/organizations/{org_a}",
                headers={
                    "Authorization": f"Bearer {context.access_token}",
                    "X-Organization-Id": str(org_a),
                },
                json={"allowed_models": ["this-is-not-a-valid-model-id"]},
            )
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(
                response.json()["detail"],
                contains_string("does not match any known models"),
            )


def test_update_organization_allowed_models_by_non_admin_is_rejected():
    org_a = uuid7()
    member_a = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                email="owner-update-models-owner@example.com",
                organization_id=org_a,
                role=OrganizationRole.OWNER,
            ),
            there_is_a_user(
                id=member_a,
                email="member-update-models@example.com",
                organization_id=org_a,
                role=OrganizationRole.MEMBER,
            ),
            there_is_an_access_token_for_user(user_id=member_a),
        ]
    ) as context:
        client: TestClient = context.client
        response = client.patch(
            f"/api/v1/organizations/{org_a}",
            headers={
                "Authorization": f"Bearer {context.access_token}",
                "X-Organization-Id": str(org_a),
            },
            json={"allowed_models": ["*"]},
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_update_organization_preserves_existing_orphaned_model():
    """A model already stored on the org but no longer in the catalog (orphaned)
    must survive a save that re-submits it — only newly-added patterns are
    validated against the live catalog."""
    org_a = uuid7()
    owner_a = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=owner_a,
                email="owner-orphan-models@example.com",
                organization_id=org_a,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_a),
        ]
    ) as context:
        client: TestClient = context.client
        org_repo: OrganizationRepository = context.injector.get(OrganizationRepository)
        org = org_repo.get(org_a)
        assert org is not None
        # gpt-4o is in the catalog; removed/model has been dropped by OpenRouter.
        org.allowed_models = ["openai/gpt-4o", "removed/model"]
        org_repo.save(org)

        with patch("api.infrastructure.openrouter.client.OpenRouterClient.list_models") as mock_list_models:
            mock_list_models.return_value = [{"id": "openai/gpt-4o"}]
            response = client.patch(
                f"/api/v1/organizations/{org_a}",
                headers={
                    "Authorization": f"Bearer {context.access_token}",
                    "X-Organization-Id": str(org_a),
                },
                # UI re-submits the orphaned entry to preserve it.
                json={"allowed_models": ["openai/gpt-4o", "removed/model"]},
            )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["allowed_models"], equal_to(["openai/gpt-4o", "removed/model"]))


def test_update_organization_ignores_null_allowed_models():
    """An explicit allowed_models=null is a no-op: the non-nullable column must
    never be overwritten with NULL, and the stored list is left untouched."""
    org_a = uuid7()
    owner_a = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=owner_a,
                email="owner-null-models@example.com",
                organization_id=org_a,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_a),
        ]
    ) as context:
        client: TestClient = context.client
        org_repo: OrganizationRepository = context.injector.get(OrganizationRepository)
        org = org_repo.get(org_a)
        assert org is not None
        org.allowed_models = ["openai/gpt-4o"]
        org_repo.save(org)

        response = client.patch(
            f"/api/v1/organizations/{org_a}",
            headers={
                "Authorization": f"Bearer {context.access_token}",
                "X-Organization-Id": str(org_a),
            },
            json={"name": "Renamed Org", "allowed_models": None},
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(body["name"], equal_to("Renamed Org"))
        assert_that(body["allowed_models"], equal_to(["openai/gpt-4o"]))


def test_update_organization_allowed_models_emits_model_allowlist_changed_event():
    org_a = uuid7()
    owner_a = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=owner_a,
                email="owner-allowlist-event@example.com",
                organization_id=org_a,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_a),
        ]
    ) as context:
        client: TestClient = context.client

        with patch("api.infrastructure.openrouter.client.OpenRouterClient.list_models") as mock_list_models:
            mock_list_models.return_value = [{"id": "openai/gpt-4o"}]
            response = client.patch(
                f"/api/v1/organizations/{org_a}",
                headers={
                    "Authorization": f"Bearer {context.access_token}",
                    "X-Organization-Id": str(org_a),
                },
                json={"allowed_models": ["openai/gpt-4o"]},
            )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        messages = _outbox_messages(context)
        changed_events = [m for m in messages if m.event_name == ORGANIZATION_MODEL_ALLOWLIST_CHANGED]
        assert_that(len(changed_events), equal_to(1))
        assert_that(changed_events[0].payload["previous_models"], equal_to([]))
        assert_that(changed_events[0].payload["new_models"], equal_to(["openai/gpt-4o"]))


def test_update_organization_same_allowed_models_emits_no_event():
    org_a = uuid7()
    owner_a = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=owner_a,
                email="owner-allowlist-noop@example.com",
                organization_id=org_a,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_a),
        ]
    ) as context:
        client: TestClient = context.client
        org_repo: OrganizationRepository = context.injector.get(OrganizationRepository)
        org = org_repo.get(org_a)
        assert org is not None
        org.allowed_models = ["openai/gpt-4o"]
        org_repo.save(org)

        with patch("api.infrastructure.openrouter.client.OpenRouterClient.list_models") as mock_list_models:
            mock_list_models.return_value = [{"id": "openai/gpt-4o"}]
            response = client.patch(
                f"/api/v1/organizations/{org_a}",
                headers={
                    "Authorization": f"Bearer {context.access_token}",
                    "X-Organization-Id": str(org_a),
                },
                json={"allowed_models": ["openai/gpt-4o"]},
            )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        messages = _outbox_messages(context)
        changed_events = [m for m in messages if m.event_name == ORGANIZATION_MODEL_ALLOWLIST_CHANGED]
        assert_that(len(changed_events), equal_to(0))


def test_model_allowlist_changed_event_projects_to_durable_security_audit_record():
    org_a = uuid7()
    owner_a = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=owner_a,
                email="owner-allowlist-projection@example.com",
                organization_id=org_a,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_a),
        ]
    ) as context:
        client: TestClient = context.client

        with patch("api.infrastructure.openrouter.client.OpenRouterClient.list_models") as mock_list_models:
            mock_list_models.return_value = [{"id": "openai/gpt-4o"}]
            response = client.patch(
                f"/api/v1/organizations/{org_a}",
                headers={
                    "Authorization": f"Bearer {context.access_token}",
                    "X-Organization-Id": str(org_a),
                },
                json={"allowed_models": ["openai/gpt-4o"]},
            )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))

        outbox_repository = context.injector.get(OutboxMessageRepository)
        messages = _outbox_messages(context)
        changed_event = next(m for m in messages if m.event_name == ORGANIZATION_MODEL_ALLOWLIST_CHANGED)
        delivery = outbox_repository.list_deliveries_for_event(changed_event.event_id)[0]
        outbox_repository.mark_delivery_enqueued(delivery.id)
        processed = context.injector.get(EventDeliveryProcessor).process(delivery.id)

        assert_that(processed, equal_to(True))
        audit_record = context.injector.get(SecurityAuditRepository).get_by_event_id(changed_event.event_id)
        assert_that(audit_record, is_not(none()))
        assert audit_record is not None
        assert_that(audit_record.action, equal_to(ORGANIZATION_MODEL_ALLOWLIST_CHANGED))
