from unittest.mock import patch
from uuid import uuid7

import pytest
from fastapi import status
from hamcrest import assert_that, contains_string, equal_to, has_length, is_not, none
from sqlmodel import Session
from starlette.testclient import TestClient

from api.domains.events.catalog import ORGANIZATION_MODEL_ALLOWLIST_CHANGED
from api.domains.events.models import OutboxMessage
from api.domains.events.processor import EventDeliveryProcessor
from api.domains.events.repository import OutboxMessageRepository
from api.domains.events.security_audit import SecurityAuditRepository
from api.domains.llm_providers.models import (
    OPENROUTER_CONNECTION_ID,
    LlmProviderConnection,
    LlmProviderConnectionOrganization,
    OrganizationAccess,
)
from api.domains.organizations.models import Organization
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

LIST_MODELS = "api.infrastructure.openrouter.client.OpenRouterClient.list_models"
MODEL = "openai/gpt-4o"
OTHER_MODEL = "openai/gpt-5-mini"
ENTRY = f"openrouter/{MODEL}"
OTHER_ENTRY = f"openrouter/{OTHER_MODEL}"
ALLOWLIST_EVENT = ORGANIZATION_MODEL_ALLOWLIST_CHANGED
NO_PROVIDER = "This organization has no LLM provider. Ask a Platform Administrator."


def _setup(*steps):
    return [
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        *steps,
    ]


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
                json={"allowed_models": ["openrouter/this-is-not-a-valid-model-id"]},
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
            json={"allowed_models": ["openrouter/*"]},
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
        org.allowed_models = ["openrouter/openai/gpt-4o", "openrouter/removed/model"]
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
                json={"allowed_models": ["openrouter/openai/gpt-4o", "openrouter/removed/model"]},
            )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            response.json()["allowed_models"], equal_to(["openrouter/openai/gpt-4o", "openrouter/removed/model"])
        )


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
        org.allowed_models = ["openrouter/openai/gpt-4o"]
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
        assert_that(body["allowed_models"], equal_to(["openrouter/openai/gpt-4o"]))


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
                json={"allowed_models": ["openrouter/openai/gpt-4o"]},
            )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        messages = _outbox_messages(context)
        changed_events = [m for m in messages if m.event_name == ORGANIZATION_MODEL_ALLOWLIST_CHANGED]
        assert_that(len(changed_events), equal_to(1))
        assert_that(changed_events[0].payload["added"], equal_to(["openrouter/openai/gpt-4o"]))
        assert_that(changed_events[0].payload["removed"], equal_to([]))
        # Regression: actor_display must be the acting user's name, not the
        # ActorIdentity type string ("MEMBERSHIP"/"USER").
        assert_that(changed_events[0].payload["actor_display"], equal_to("Test User"))


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
        org.allowed_models = ["openrouter/openai/gpt-4o"]
        org_repo.save(org)

        with patch("api.infrastructure.openrouter.client.OpenRouterClient.list_models") as mock_list_models:
            mock_list_models.return_value = [{"id": "openai/gpt-4o"}]
            response = client.patch(
                f"/api/v1/organizations/{org_a}",
                headers={
                    "Authorization": f"Bearer {context.access_token}",
                    "X-Organization-Id": str(org_a),
                },
                json={"allowed_models": ["openrouter/openai/gpt-4o"]},
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
                json={"allowed_models": ["openrouter/openai/gpt-4o"]},
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


def _engine(context):
    return context.injector.get(PostgresRepositoryDelegate).engine


def _owner_with_allowlist(allowed_models: list[str]):
    def step(context):
        there_is_a_user(email="owner-access@example.com", organization_id=uuid7(), role=OrganizationRole.OWNER)(context)
        there_is_an_access_token_for_user(user_id=context.user.id)(context)
        with Session(_engine(context)) as session:
            organization = session.get_one(Organization, context.organization.id)
            organization.allowed_models = allowed_models
            session.add(organization)
            session.commit()

    return step


def _set_openrouter_access(context, access: OrganizationAccess, listed: str | None = None) -> None:
    with Session(_engine(context)) as session:
        if listed == "other":
            other = Organization(name="Other Org")
            session.add(other)
            session.flush()
            listed_id = other.id
        else:
            listed_id = context.organization.id
        connection = session.get_one(LlmProviderConnection, OPENROUTER_CONNECTION_ID)
        connection.organization_access = access
        session.add(connection)
        if listed is not None:
            session.add(LlmProviderConnectionOrganization(connection_id=connection.id, organization_id=listed_id))
        session.commit()


def openrouter_access(access: OrganizationAccess, listed: str | None = None):
    def step(context):
        _set_openrouter_access(context, access, listed)

    return step


def _save_allowlist(context, allowed_models: list[str], catalogue=None):
    with patch(LIST_MODELS, side_effect=catalogue or (lambda: [{"id": MODEL}, {"id": OTHER_MODEL}])) as listed:
        response = context.client.patch(
            f"/api/v1/organizations/{context.organization.id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
            json={"allowed_models": allowed_models},
        )
    return response, listed


def _stored_allowlist(context) -> list[str]:
    with Session(_engine(context)) as session:
        return session.get_one(Organization, context.organization.id).allowed_models


def _allowlist_events(context) -> list[OutboxMessage]:
    return [message for message in _outbox_messages(context) if message.event_name == ALLOWLIST_EVENT]


@pytest.mark.parametrize(
    ("access", "listed"),
    [(OrganizationAccess.NONE, None), (OrganizationAccess.ONLY, "other"), (OrganizationAccess.ALL_EXCEPT, "self")],
)
def test_an_organization_without_openrouter_access_cannot_allow_models(access, listed):
    with given(_setup(_owner_with_allowlist([]), openrouter_access(access, listed))) as context:
        response, catalogue = _save_allowlist(context, [ENTRY])

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json()["detail"], equal_to(NO_PROVIDER))
        catalogue.assert_not_called()
        assert_that((_stored_allowlist(context), _allowlist_events(context)), equal_to(([], [])))


def test_an_organization_without_openrouter_access_can_empty_its_allowlist():
    with given(_setup(_owner_with_allowlist([ENTRY]), openrouter_access(OrganizationAccess.NONE))) as context:
        response, _ = _save_allowlist(context, [])

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(_stored_allowlist(context), equal_to([]))


def test_access_withdrawn_after_the_first_check_still_refuses_the_save():
    with given(_setup(_owner_with_allowlist([]))) as context:

        def withdraw_while_the_catalogue_is_read():
            _set_openrouter_access(context, OrganizationAccess.NONE)
            return [{"id": MODEL}]

        response, catalogue = _save_allowlist(context, [ENTRY], catalogue=withdraw_while_the_catalogue_is_read)

        catalogue.assert_called_once()
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json()["detail"], equal_to(NO_PROVIDER))
        assert_that((_stored_allowlist(context), _allowlist_events(context)), equal_to(([], [])))


@pytest.mark.parametrize(
    ("access", "listed"),
    [(OrganizationAccess.ALL, None), (OrganizationAccess.ONLY, "self"), (OrganizationAccess.ALL_EXCEPT, "other")],
)
def test_an_organization_with_openrouter_access_saves_its_allowlist(access, listed):
    with given(_setup(_owner_with_allowlist([ENTRY]), openrouter_access(access, listed))) as context:
        response, _ = _save_allowlist(context, [ENTRY, OTHER_ENTRY])

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(_stored_allowlist(context), equal_to([ENTRY, OTHER_ENTRY]))
        assert_that(_allowlist_events(context), has_length(1))


def test_an_entry_naming_another_connection_is_refused():
    with given(_setup(_owner_with_allowlist([ENTRY]))) as context:
        response, _ = _save_allowlist(context, [ENTRY, OTHER_MODEL])

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json()["detail"], contains_string(f"'{OTHER_MODEL}' does not match any known models"))
        assert_that((_stored_allowlist(context), _allowlist_events(context)), equal_to(([ENTRY], [])))


def test_an_entry_sent_with_the_gateway_prefix_is_stored_without_it():
    with given(_setup(_owner_with_allowlist([]))) as context:
        response, _ = _save_allowlist(context, [f"litellm/{ENTRY}"])

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(_stored_allowlist(context), equal_to([ENTRY]))
