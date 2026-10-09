from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event, Lock
from unittest.mock import patch
from uuid import UUID, uuid4, uuid7

import pytest
from hamcrest import assert_that, equal_to, has_entries, has_key, is_not

from api.domains.analytics.event_handlers import ProductAnalyticsHandler
from api.domains.analytics.repository import InstallationRepository
from api.domains.events.catalog import (
    AGENT_CREATED,
    AGENT_UPDATED,
    API_KEY_CREATED,
    ORGANIZATION_CREATED,
    ORGANIZATION_MEMBER_REMOVED,
    ORGANIZATION_ROLE_CHANGED,
    PRODUCT_ANALYTICS_HANDLER,
)
from api.domains.events.handlers import (
    EventDeliveryContext,
    EventHandlerRegistry,
    RetryableEventHandlerError,
    TerminalEventHandlerError,
)
from api.domains.events.models import (
    ActorIdentity,
    ActorIdentityType,
    DomainEventEnvelope,
    EventScope,
    SubjectIdentity,
    SubjectIdentityType,
)
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.infrastructure.posthog.exceptions import RetryablePostHogException, TerminalPostHogException
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.mocks.posthog import MockPostHogModule
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization, there_is_an_organization_with_user_and_access_token
from api.tests.steps.user import there_is_a_user

OCCURRED_AT = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def _given(
    posthog: MockPostHogModule,
    *,
    enabled: bool = True,
    user_details: bool = False,
    web_app_url: str = "https://test-installation.example.com/app",
):
    return [
        set_env_variable(
            {
                "ANALYTICS_ENABLED": str(enabled).lower(),
                "ANALYTICS_INCLUDE_USER_DETAILS": str(user_details).lower(),
                "WEB_APP_URL": web_app_url,
            }
        ),
        prepare_injector(modules=[posthog]),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(),
    ]


def _membership_actor(context) -> ActorIdentity:
    return ActorIdentity(
        type=ActorIdentityType.MEMBERSHIP, id=str(context.organization_user.id), organization_id=context.organization.id
    )


def _envelope(context, event_name: str, payload: dict, actor: ActorIdentity | None = None) -> DomainEventEnvelope:
    return DomainEventEnvelope(
        event_name=event_name,
        schema_version=1,
        occurred_at=OCCURRED_AT,
        event_scope=EventScope.ORGANIZATION,
        organization_id=context.organization.id,
        actor=actor or _membership_actor(context),
        subject=SubjectIdentity(type=SubjectIdentityType.AGENT, id=uuid7(), organization_id=context.organization.id),
        correlation_id=uuid4(),
        payload=payload,
    )


def _agent_created(context, actor: ActorIdentity | None = None) -> DomainEventEnvelope:
    return _envelope(
        context,
        AGENT_CREATED,
        {
            "organization_id": str(context.organization.id),
            "agent_id": str(uuid7()),
            "agent_name": "Secret Project Agent",
            "created_by_user_id": str(context.user.id),
            "runtime": "HERMES",
        },
        actor,
    )


def _delivery(event: DomainEventEnvelope, attempt_count: int = 1) -> EventDeliveryContext:
    return EventDeliveryContext(
        delivery_id=uuid7(),
        event_id=event.event_id,
        handler_name=PRODUCT_ANALYTICS_HANDLER,
        attempt_count=attempt_count,
        correlation_id=event.correlation_id,
        organization_id=event.organization_id,
    )


def _handle(context, event: DomainEventEnvelope, attempt_count: int = 1) -> None:
    context.injector.get(ProductAnalyticsHandler).handle(event, _delivery(event, attempt_count))


def _platform_event(context) -> DomainEventEnvelope:
    return DomainEventEnvelope(
        event_name=API_KEY_CREATED,
        schema_version=1,
        occurred_at=OCCURRED_AT,
        event_scope=EventScope.PLATFORM,
        organization_id=None,
        actor=ActorIdentity(type=ActorIdentityType.USER, id=context.user.id),
        subject=SubjectIdentity(type=SubjectIdentityType.USER, id=context.user.id),
        correlation_id=uuid4(),
        payload={"user_id": str(context.user.id)},
    )


def test_a_platform_event_is_sent_with_only_the_installation_group():
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        _handle(context, _platform_event(context))

        installation_id = str(context.injector.get(InstallationRepository).get_id())
        capture = posthog.batches[0][0]
        assert_that(capture["distinct_id"], equal_to(str(context.user.id)))
        assert_that(capture["properties"]["$groups"], equal_to({"installation": installation_id}))
        assert_that(capture["properties"], is_not(has_key("organization_id")))
        assert_that(capture["properties"]["installation_name"], equal_to("test-installation.example.com"))


def test_without_any_name_the_installation_is_named_by_its_id():
    posthog = MockPostHogModule()
    with given(_given(posthog, web_app_url="")) as context:
        _handle(context, _agent_created(context))

        installation_id = str(context.injector.get(InstallationRepository).get_id())
        capture, group_identify = posthog.batches[0]
        assert_that(capture["properties"]["installation_name"], equal_to(installation_id))
        assert_that(group_identify["properties"]["$group_set"], equal_to({"name": installation_id}))


def test_a_domain_change_renames_the_group_without_changing_installation_identity():
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        handler = context.injector.get(ProductAnalyticsHandler)
        _handle(context, _agent_created(context))
        handler.config.web_app_url = "https://renamed.example.com:8443/app"

        _handle(context, _agent_created(context))

        first_capture, first_identify = posthog.batches[0]
        second_capture, second_identify = posthog.batches[1]
        assert_that(
            second_capture["properties"]["installation_id"], equal_to(first_capture["properties"]["installation_id"])
        )
        assert_that(second_capture["properties"]["$groups"], equal_to(first_capture["properties"]["$groups"]))
        assert_that(second_capture["properties"]["installation_name"], equal_to("renamed.example.com"))
        assert_that(second_identify["properties"]["$group_key"], equal_to(first_identify["properties"]["$group_key"]))
        assert_that(second_identify["properties"]["$group_set"], equal_to({"name": "renamed.example.com"}))


def test_is_registered_in_the_application_handler_registry():
    with given(_given(MockPostHogModule())) as context:
        registry = context.injector.get(EventHandlerRegistry)

        assert_that(registry.get(PRODUCT_ANALYTICS_HANDLER).name, equal_to(PRODUCT_ANALYTICS_HANDLER))


def test_sends_the_event_as_the_acting_user_with_installation_and_organization_groups():
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        event = _agent_created(context)

        _handle(context, event)

        installation_id = str(context.injector.get(InstallationRepository).get_id())
        assert_that(len(posthog.batches), equal_to(1))
        capture, group_identify = posthog.batches[0]
        assert_that(
            capture,
            has_entries(
                {
                    "event": AGENT_CREATED,
                    "distinct_id": str(context.user.id),
                    "uuid": str(event.event_id),
                    "timestamp": OCCURRED_AT.isoformat(),
                }
            ),
        )
        assert_that(
            capture["properties"],
            equal_to(
                {
                    "agent_id": event.payload["agent_id"],
                    "runtime": "HERMES",
                    "source": "agentbarn-api",
                    "organization_id": str(context.organization.id),
                    "installation_id": installation_id,
                    "installation_name": "test-installation.example.com",
                    "$groups": {"installation": installation_id, "organization": str(context.organization.id)},
                    "$geoip_disable": True,
                    "$lib": "agentbarn-api",
                }
            ),
        )
        assert_that(group_identify["event"], equal_to("$groupidentify"))
        assert_that(group_identify["distinct_id"], equal_to(str(context.user.id)))
        assert_that(
            group_identify["properties"],
            has_entries(
                {
                    "$group_type": "installation",
                    "$group_key": installation_id,
                    "$group_set": {"name": "test-installation.example.com"},
                }
            ),
        )


def test_sends_only_the_role_change_fields_for_a_role_change():
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        membership_id = str(uuid7())
        event = _envelope(
            context,
            ORGANIZATION_ROLE_CHANGED,
            {
                "organization_id": str(context.organization.id),
                "membership_id": membership_id,
                "user_id": str(uuid7()),
                "previous_role": "MEMBER",
                "new_role": "ADMIN",
                "actor_display": "Admin Person",
                "subject_display": "Member Person",
            },
        )

        _handle(context, event)

        properties = posthog.batches[0][0]["properties"]
        assert_that(
            {key: properties[key] for key in ("membership_id", "previous_role", "new_role")},
            equal_to({"membership_id": membership_id, "previous_role": "MEMBER", "new_role": "ADMIN"}),
        )
        assert_that(properties, is_not(has_key("actor_display")))
        assert_that(properties, is_not(has_key("subject_display")))
        assert_that(properties, is_not(has_key("user_id")))


def test_sends_changed_field_names_but_never_their_values():
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        event = _envelope(
            context,
            AGENT_UPDATED,
            {
                "organization_id": str(context.organization.id),
                "agent_id": str(uuid7()),
                "field_changes": {"name": {"from": "Old", "to": "New"}, "model": {"from": "a", "to": "b"}},
                "actor_display": "Admin Person",
                "subject_display": "New",
            },
        )

        _handle(context, event)

        properties = posthog.batches[0][0]["properties"]
        assert_that(sorted(properties["changed_fields"]), equal_to(["model", "name"]))
        assert_that(properties, is_not(has_key("field_changes")))


def test_a_member_who_left_is_attributed_to_themselves():
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        organization = context.organization
        there_is_a_user(email="leaver@example.com", role=OrganizationRole.MEMBER)(context)
        leaver, membership = context.user, context.organization_user
        context.injector.get(OrganizationUserRepository).delete(membership)
        event = _envelope(
            context,
            ORGANIZATION_MEMBER_REMOVED,
            {
                "organization_id": str(organization.id),
                "membership_id": str(membership.id),
                "user_id": str(leaver.id),
                "role": "MEMBER",
                "actor_display": "Leaver",
                "subject_display": "Leaver",
            },
            ActorIdentity(type=ActorIdentityType.MEMBERSHIP, id=str(membership.id), organization_id=organization.id),
        )

        _handle(context, event)

        assert_that(posthog.batches[0][0]["distinct_id"], equal_to(str(leaver.id)))


def test_an_actor_whose_membership_is_gone_is_skipped():
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        actor = ActorIdentity(
            type=ActorIdentityType.MEMBERSHIP, id=str(uuid7()), organization_id=context.organization.id
        )

        _handle(context, _agent_created(context, actor))

        assert_that(posthog.batches, equal_to([]))


def test_a_membership_from_another_organization_is_not_resolved():
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        foreign_actor = _membership_actor(context)
        there_is_an_organization(name="Other Organization")(context)

        _handle(context, _agent_created(context, foreign_actor))

        assert_that(posthog.batches, equal_to([]))


def test_a_user_actor_without_membership_is_resolved_by_user_id():
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        actor = ActorIdentity(type=ActorIdentityType.USER, id=context.user.id)

        _handle(context, _agent_created(context, actor))

        assert_that(posthog.batches[0][0]["distinct_id"], equal_to(str(context.user.id)))


@pytest.mark.parametrize("actor_type", [ActorIdentityType.SYSTEM, ActorIdentityType.RUNTIME])
def test_events_without_a_human_actor_are_skipped(actor_type):
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        actor = ActorIdentity(type=actor_type, id="agent-maintenance", organization_id=context.organization.id)

        _handle(context, _agent_created(context, actor))

        assert_that(posthog.batches, equal_to([]))


def test_nothing_is_sent_while_analytics_is_disabled():
    posthog = MockPostHogModule()
    with given(_given(posthog, enabled=False)) as context:
        _handle(context, _agent_created(context))

        assert_that(posthog.batches, equal_to([]))


def test_user_details_are_left_out_by_default():
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        _handle(context, _agent_created(context))

        assert_that(posthog.batches[0][0]["properties"], is_not(has_key("$set")))


def test_user_details_are_set_when_enabled():
    posthog = MockPostHogModule()
    with given(_given(posthog, user_details=True)) as context:
        _handle(context, _agent_created(context))

        assert_that(
            posthog.batches[0][0]["properties"]["$set"],
            equal_to({"email": context.user.email, "name": context.user.full_name}),
        )


@pytest.mark.parametrize("attempt_count", [1, 2])
def test_an_unreachable_posthog_is_retried_on_early_attempts(attempt_count):
    with given(_given(MockPostHogModule(error=RetryablePostHogException("down")))) as context:
        with pytest.raises(RetryableEventHandlerError):
            _handle(context, _agent_created(context), attempt_count)


def test_an_unreachable_posthog_is_given_up_on_the_third_attempt():
    with given(_given(MockPostHogModule(error=RetryablePostHogException("down")))) as context:
        _handle(context, _agent_created(context), attempt_count=3)


def test_a_rejected_batch_is_terminal():
    with given(_given(MockPostHogModule(error=TerminalPostHogException("bad")))) as context:
        with pytest.raises(TerminalEventHandlerError):
            _handle(context, _agent_created(context))


def test_a_redelivered_event_carries_the_same_ids():
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        event = _agent_created(context)

        _handle(context, event)
        _handle(context, event, attempt_count=2)

        first, second = posthog.batches
        assert_that(
            [(m["uuid"], m["timestamp"], m["distinct_id"]) for m in second if m["event"] == AGENT_CREATED],
            equal_to([(m["uuid"], m["timestamp"], m["distinct_id"]) for m in first if m["event"] == AGENT_CREATED]),
        )
        assert_that(UUID(first[1]["uuid"]), is_not(equal_to(event.event_id)))


def test_the_installation_is_identified_once_per_process():
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        _handle(context, _agent_created(context))
        _handle(context, _agent_created(context))

        first, second = posthog.batches
        assert_that([message["event"] for message in first], equal_to([AGENT_CREATED, "$groupidentify"]))
        assert_that([message["event"] for message in second], equal_to([AGENT_CREATED]))


def test_concurrent_first_deliveries_identify_the_installation_only_once():
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        handler = context.injector.get(ProductAnalyticsHandler)
        events = [_agent_created(context), _agent_created(context)]
        ready = Barrier(2)
        second_send = Event()
        first_send_started = Event()
        send_lock = Lock()
        send_batch = handler.posthog_client.send_batch
        resolve_user = handler._resolve_user

        def record_batch(messages):
            with send_lock:
                first_send = not first_send_started.is_set()
                first_send_started.set()
            if first_send:
                # Keep the first capture in flight while the other delivery tries
                # to send. With synchronization it waits until this send finishes.
                second_send.wait(timeout=1)
            else:
                second_send.set()
            send_batch(messages)

        def resolve_when_ready(event, organization_id):
            user = resolve_user(event, organization_id)
            ready.wait(timeout=5)
            return user

        def deliver(event):
            handler.handle(event, _delivery(event))

        with (
            patch.object(handler, "_resolve_user", side_effect=resolve_when_ready),
            patch.object(handler.posthog_client, "send_batch", side_effect=record_batch),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            list(pool.map(deliver, events))

        captures = [message for batch in posthog.batches for message in batch]
        assert_that(
            sorted(message["uuid"] for message in captures if message["event"] == AGENT_CREATED),
            equal_to(sorted(str(event.event_id) for event in events)),
        )
        assert_that(sum(message["event"] == "$groupidentify" for message in captures), equal_to(1))


def test_the_installation_is_identified_again_after_a_failed_send():
    posthog = MockPostHogModule(error=RetryablePostHogException("down"))
    with given(_given(posthog)) as context:
        with pytest.raises(RetryableEventHandlerError):
            _handle(context, _agent_created(context))
        posthog.error = None

        _handle(context, _agent_created(context))

        assert_that([message["event"] for message in posthog.batches[0]], equal_to([AGENT_CREATED, "$groupidentify"]))


def test_organization_created_is_sent_with_the_organization_group_and_no_extra_fields():
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        event = _envelope(
            context,
            ORGANIZATION_CREATED,
            {"organization_id": str(context.organization.id), "created_by_user_id": str(context.user.id)},
            ActorIdentity(type=ActorIdentityType.USER, id=context.user.id),
        )

        _handle(context, event)

        capture = posthog.batches[0][0]
        assert_that(capture["event"], equal_to(ORGANIZATION_CREATED))
        assert_that(capture["distinct_id"], equal_to(str(context.user.id)))
        assert_that(
            set(capture["properties"]),
            equal_to(
                {
                    "source",
                    "installation_id",
                    "installation_name",
                    "organization_id",
                    "$groups",
                    "$geoip_disable",
                    "$lib",
                }
            ),
        )
