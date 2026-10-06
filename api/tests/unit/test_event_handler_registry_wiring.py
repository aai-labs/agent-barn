from unittest.mock import Mock

import pytest
from hamcrest import assert_that, equal_to, is_

from api.domains.agents.event_handlers import AgentLifecycleEmailHandler
from api.domains.analytics.event_handlers import ProductAnalyticsHandler
from api.domains.events.catalog import (
    AGENT_ACCESS_GRANTED,
    AGENT_ACCESS_REVOKED,
    AGENT_CREATED,
    AGENT_DELETED,
    AGENT_GENERAL_ACCESS_CHANGED,
    AGENT_LIFECYCLE_EMAIL_HANDLER,
    AGENT_SECRET_ADDED,
    AGENT_SECRET_REMOVED,
    AGENT_SECRET_UPDATED,
    AGENT_STARTED,
    AGENT_STOPPED,
    AGENT_TEMPLATE_OVERRIDE_DRAFT_SAVED,
    AGENT_TEMPLATE_OVERRIDE_PUBLISHED,
    AGENT_TEMPLATE_OVERRIDE_SELECTED,
    AGENT_UPDATED,
    COMMUNICATION_CONNECTION_HEALTH_CHANGED,
    COMMUNICATION_CONNECTION_RECONNECT_REQUESTED,
    COMMUNICATION_DELIVERY_DEAD_LETTERED,
    COMMUNICATION_DELIVERY_RECOVERED,
    COMMUNICATION_DELIVERY_RETRY_REQUESTED,
    EVENT_REGISTRY,
    ORGANIZATION_MEMBER_ADDED,
    ORGANIZATION_MEMBER_REMOVED,
    ORGANIZATION_MODEL_ALLOWLIST_CHANGED,
    ORGANIZATION_OWNERSHIP_TRANSFERRED,
    ORGANIZATION_ROLE_CHANGED,
    ORGANIZATION_VALUE_SETTINGS_CHANGED,
    PLATFORM_USER_PRIVILEGE_GRANTED,
    PLATFORM_USER_PRIVILEGE_REVOKED,
    PRODUCT_ANALYTICS_HANDLER,
    SECURITY_AUDIT_HANDLER,
    TEMPLATE_CREATED,
    TEMPLATE_DELETED,
    TEMPLATE_UPDATED,
)
from api.domains.events.handlers import EventHandlerRegistry
from api.domains.events.security_audit import SecurityAuditProjection


def _build_production_handler_registry() -> EventHandlerRegistry:
    return EventHandlerRegistry(
        [
            AgentLifecycleEmailHandler(repository=Mock(), email_service=Mock()),
            SecurityAuditProjection(repository=Mock()),
            ProductAnalyticsHandler(
                config=Mock(),
                installation_repository=Mock(),
                organization_user_repository=Mock(),
                user_repository=Mock(),
                posthog_client=Mock(),
            ),
        ]
    )


@pytest.mark.parametrize(
    ("event_name", "expected_handlers"),
    [
        (AGENT_CREATED, {PRODUCT_ANALYTICS_HANDLER}),
        (AGENT_UPDATED, {SECURITY_AUDIT_HANDLER, PRODUCT_ANALYTICS_HANDLER}),
        (AGENT_STARTED, {AGENT_LIFECYCLE_EMAIL_HANDLER, PRODUCT_ANALYTICS_HANDLER}),
        (AGENT_STOPPED, {AGENT_LIFECYCLE_EMAIL_HANDLER, PRODUCT_ANALYTICS_HANDLER}),
        (AGENT_DELETED, {SECURITY_AUDIT_HANDLER, PRODUCT_ANALYTICS_HANDLER}),
        (ORGANIZATION_MEMBER_ADDED, {SECURITY_AUDIT_HANDLER, PRODUCT_ANALYTICS_HANDLER}),
        (ORGANIZATION_MEMBER_REMOVED, {SECURITY_AUDIT_HANDLER, PRODUCT_ANALYTICS_HANDLER}),
        (ORGANIZATION_ROLE_CHANGED, {SECURITY_AUDIT_HANDLER, PRODUCT_ANALYTICS_HANDLER}),
        (ORGANIZATION_OWNERSHIP_TRANSFERRED, {SECURITY_AUDIT_HANDLER, PRODUCT_ANALYTICS_HANDLER}),
        (AGENT_ACCESS_GRANTED, {SECURITY_AUDIT_HANDLER}),
        (TEMPLATE_CREATED, {SECURITY_AUDIT_HANDLER}),
    ],
)
def test_product_analytics_is_added_to_exactly_the_slice_events(event_name, expected_handlers):
    assert_that(set(EVENT_REGISTRY.handler_names_for(event_name, 1)), equal_to(expected_handlers))


def test_every_catalog_handler_name_has_a_registered_handler():
    """Regression test: every handler name a Domain Event declares in the catalog must
    resolve to a registered Event Handler, or its deliveries permanently dead-letter
    with UNKNOWN_HANDLER as soon as a worker claims them."""
    handlers = _build_production_handler_registry()

    for event_name in (
        AGENT_CREATED,
        ORGANIZATION_ROLE_CHANGED,
        AGENT_ACCESS_GRANTED,
        AGENT_ACCESS_REVOKED,
        AGENT_GENERAL_ACCESS_CHANGED,
        AGENT_STARTED,
        AGENT_STOPPED,
        AGENT_TEMPLATE_OVERRIDE_DRAFT_SAVED,
        AGENT_TEMPLATE_OVERRIDE_PUBLISHED,
        AGENT_TEMPLATE_OVERRIDE_SELECTED,
        PLATFORM_USER_PRIVILEGE_GRANTED,
        PLATFORM_USER_PRIVILEGE_REVOKED,
        AGENT_UPDATED,
        AGENT_DELETED,
        AGENT_SECRET_ADDED,
        AGENT_SECRET_UPDATED,
        AGENT_SECRET_REMOVED,
        TEMPLATE_CREATED,
        TEMPLATE_UPDATED,
        TEMPLATE_DELETED,
        ORGANIZATION_MODEL_ALLOWLIST_CHANGED,
        ORGANIZATION_VALUE_SETTINGS_CHANGED,
        ORGANIZATION_MEMBER_ADDED,
        ORGANIZATION_MEMBER_REMOVED,
        ORGANIZATION_OWNERSHIP_TRANSFERRED,
        COMMUNICATION_CONNECTION_HEALTH_CHANGED,
        COMMUNICATION_CONNECTION_RECONNECT_REQUESTED,
        COMMUNICATION_DELIVERY_DEAD_LETTERED,
        COMMUNICATION_DELIVERY_RETRY_REQUESTED,
        COMMUNICATION_DELIVERY_RECOVERED,
    ):
        for handler_name in EVENT_REGISTRY.handler_names_for(event_name, 1):
            assert_that(handlers.supports(handler_name, event_name, 1), is_(True))
