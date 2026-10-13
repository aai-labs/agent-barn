from unittest.mock import patch
from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, contains_inanyorder, equal_to

from api.domains.events.catalog import (
    ORGANIZATION_MODEL_ALLOWLIST_CHANGED,
    ORGANIZATION_UPDATED,
    PRODUCT_ANALYTICS_HANDLER,
)
from api.domains.events.dispatch import EventDeliveryDispatcher
from api.domains.events.models import OutboxMessage
from api.domains.events.processor import EventDeliveryProcessor
from api.domains.events.repository import OutboxMessageRepository
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.mocks.posthog import MockPostHogModule
from api.tests.steps.agent import MockK8sModule, MockLiteLLMModule
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

ORG_ID = uuid7()


def _given(posthog: MockPostHogModule | None = None):
    owner_id = uuid7()
    return [
        set_env_variable({"ANALYTICS_ENABLED": "true"}),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), posthog or MockPostHogModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_a_user(
            id=owner_id, email=f"owner-{owner_id}@example.com", organization_id=ORG_ID, role=OrganizationRole.OWNER
        ),
        there_is_an_access_token_for_user(user_id=owner_id),
    ]


def _patch(context, body: dict):
    with patch("api.infrastructure.openrouter.client.OpenRouterClient.list_models") as list_models:
        list_models.return_value = [{"id": "openai/gpt-4o"}]
        return context.client.patch(
            f"/api/v1/organizations/{ORG_ID}",
            headers={"Authorization": f"Bearer {context.access_token}", "X-Organization-Id": str(ORG_ID)},
            json=body,
        )


def _events(context, event_name: str) -> list[OutboxMessage]:
    messages = context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
    return [message for message in messages if message.event_name == event_name]


def test_renaming_an_organization_records_organization_updated_with_the_changed_field_names():
    with given(_given()) as context:
        response = _patch(context, {"name": "Renamed Org", "description": "New description"})

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        events = _events(context, ORGANIZATION_UPDATED)
        assert_that(len(events), equal_to(1))
        assert_that(
            events[0].payload, equal_to({"organization_id": str(ORG_ID), "changed_fields": ["description", "name"]})
        )
        assert_that(events[0].actor, equal_to({"type": "USER", "id": str(context.user.id), "organization_id": None}))
        deliveries = context.injector.get(OutboxMessageRepository).list_deliveries_for_event(events[0].event_id)
        assert_that([delivery.handler_name for delivery in deliveries], equal_to([PRODUCT_ANALYTICS_HANDLER]))


def test_resending_the_current_values_records_nothing():
    with given(_given()) as context:
        current = context.client.get(
            f"/api/v1/organizations/{ORG_ID}", headers={"Authorization": f"Bearer {context.access_token}"}
        ).json()

        response = _patch(context, {"name": current["name"], "description": current["description"]})

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(_events(context, ORGANIZATION_UPDATED), equal_to([]))


def test_a_rename_with_an_allowlist_change_records_and_enqueues_both_events():
    with given(_given()) as context:
        with patch.object(EventDeliveryDispatcher, "enqueue_immediate") as enqueue:
            response = _patch(context, {"name": "Renamed Again", "allowed_models": ["openai/gpt-4o"]})

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        updated = _events(context, ORGANIZATION_UPDATED)
        allowlist = _events(context, ORGANIZATION_MODEL_ALLOWLIST_CHANGED)
        assert_that((len(updated), len(allowlist)), equal_to((1, 1)))
        assert_that(allowlist[0].actor["type"], equal_to("MEMBERSHIP"))
        outbox = context.injector.get(OutboxMessageRepository)
        staged = [
            delivery.id
            for event in (updated[0], allowlist[0])
            for delivery in outbox.list_deliveries_for_event(event.event_id)
        ]
        assert_that(enqueue.call_args.args[0], contains_inanyorder(*staged))


def test_a_rename_is_still_sent_when_the_organization_is_deleted_before_delivery():
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        with patch.object(EventDeliveryDispatcher, "enqueue_immediate"):
            _patch(context, {"name": "Renamed Before Delete"})
            deleted = context.client.delete(
                f"/api/v1/organizations/{ORG_ID}", headers={"Authorization": f"Bearer {context.access_token}"}
            )
        assert_that(deleted.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        outbox = context.injector.get(OutboxMessageRepository)
        delivery = outbox.list_deliveries_for_event(_events(context, ORGANIZATION_UPDATED)[0].event_id)[0]
        outbox.mark_delivery_enqueued(delivery.id)

        context.injector.get(EventDeliveryProcessor).process(delivery.id)

        captures = [
            message for batch in posthog.batches for message in batch if message["event"] == ORGANIZATION_UPDATED
        ]
        assert_that([capture["distinct_id"] for capture in captures], equal_to([str(context.user.id)]))
        assert_that(captures[0]["properties"]["$groups"]["organization"], equal_to(str(ORG_ID)))
