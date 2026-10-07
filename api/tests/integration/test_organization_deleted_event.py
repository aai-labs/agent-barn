from unittest.mock import patch
from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, equal_to

from api.domains.analytics.repository import InstallationRepository
from api.domains.events.catalog import ORGANIZATION_DELETED, PRODUCT_ANALYTICS_HANDLER
from api.domains.events.dispatch import EventDeliveryDispatcher
from api.domains.events.models import OutboxMessage
from api.domains.events.processor import EventDeliveryProcessor
from api.domains.events.repository import OutboxMessageRepository
from api.domains.organizations.models import Organization
from api.domains.users.organization_users.models import OrganizationRole, OrganizationUser
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.mocks.posthog import MockPostHogModule
from api.tests.steps.agent import MockK8sModule, MockLiteLLMModule
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

ORG_ID = uuid7()
OWNER_ID = uuid7()


def _given(posthog: MockPostHogModule):
    return [
        set_env_variable({"ANALYTICS_ENABLED": "true"}),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), posthog]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_a_user(
            id=OWNER_ID, email="owner-deleted-event@example.com", organization_id=ORG_ID, role=OrganizationRole.OWNER
        ),
        there_is_an_access_token_for_user(user_id=OWNER_ID),
    ]


def _delete(context):
    return context.client.delete(
        f"/api/v1/organizations/{ORG_ID}", headers={"Authorization": f"Bearer {context.access_token}"}
    )


def _deleted_events(context) -> list[OutboxMessage]:
    messages = context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
    return [message for message in messages if message.event_name == ORGANIZATION_DELETED]


def test_deleting_an_organization_records_organization_deleted_that_outlives_it():
    with given(_given(MockPostHogModule())) as context:
        with patch.object(EventDeliveryDispatcher, "enqueue_immediate") as enqueue:
            response = _delete(context)

        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        delegate = context.injector.get(PostgresRepositoryDelegate)
        assert_that(delegate.find_by_id(Organization, ORG_ID), equal_to(None))
        assert_that(delegate.find_all(OrganizationUser, organization_id=ORG_ID), equal_to([]))
        events = _deleted_events(context)
        assert_that(len(events), equal_to(1))
        assert_that(events[0].organization_id, equal_to(ORG_ID))
        assert_that(events[0].actor, equal_to({"type": "USER", "id": str(OWNER_ID), "organization_id": None}))
        deliveries = context.injector.get(OutboxMessageRepository).list_deliveries_for_event(events[0].event_id)
        assert_that([delivery.handler_name for delivery in deliveries], equal_to([PRODUCT_ANALYTICS_HANDLER]))
        assert_that(enqueue.call_args.args[0], equal_to([deliveries[0].id]))


def test_organization_deleted_is_sent_as_the_deleter_with_the_organization_group():
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        with patch.object(EventDeliveryDispatcher, "enqueue_immediate"):
            _delete(context)
        outbox = context.injector.get(OutboxMessageRepository)
        delivery = outbox.list_deliveries_for_event(_deleted_events(context)[0].event_id)[0]
        outbox.mark_delivery_enqueued(delivery.id)

        processed = context.injector.get(EventDeliveryProcessor).process(delivery.id)

        assert_that(processed, equal_to(True))
        capture = posthog.batches[0][0]
        assert_that(capture["event"], equal_to(ORGANIZATION_DELETED))
        assert_that(capture["distinct_id"], equal_to(str(OWNER_ID)))
        installation_id = str(context.injector.get(InstallationRepository).get_id())
        assert_that(
            capture["properties"]["$groups"], equal_to({"installation": installation_id, "organization": str(ORG_ID)})
        )
