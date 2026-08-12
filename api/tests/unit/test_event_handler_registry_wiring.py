from unittest.mock import Mock

from api.domains.agents.event_handlers import AgentLifecycleEmailHandler
from api.domains.events.catalog import (
    AGENT_ACCESS_GRANTED,
    AGENT_ACCESS_REVOKED,
    AGENT_DELETED,
    AGENT_GENERAL_ACCESS_CHANGED,
    AGENT_SECRET_ADDED,
    AGENT_SECRET_REMOVED,
    AGENT_SECRET_UPDATED,
    AGENT_STARTED,
    AGENT_STOPPED,
    AGENT_UPDATED,
    EVENT_REGISTRY,
    ORGANIZATION_MEMBER_ADDED,
    ORGANIZATION_MEMBER_REMOVED,
    ORGANIZATION_MODEL_ALLOWLIST_CHANGED,
    ORGANIZATION_OWNERSHIP_TRANSFERRED,
    ORGANIZATION_ROLE_CHANGED,
    PLATFORM_USER_PRIVILEGE_GRANTED,
    PLATFORM_USER_PRIVILEGE_REVOKED,
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
        ]
    )


def test_every_catalog_handler_name_has_a_registered_handler():
    """Regression test: every handler name a Domain Event declares in the catalog must
    resolve to a registered Event Handler, or its deliveries permanently dead-letter
    with UNKNOWN_HANDLER as soon as a worker claims them."""
    handlers = _build_production_handler_registry()

    for event_name in (
        ORGANIZATION_ROLE_CHANGED,
        AGENT_ACCESS_GRANTED,
        AGENT_ACCESS_REVOKED,
        AGENT_GENERAL_ACCESS_CHANGED,
        AGENT_STARTED,
        AGENT_STOPPED,
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
        ORGANIZATION_MEMBER_ADDED,
        ORGANIZATION_MEMBER_REMOVED,
        ORGANIZATION_OWNERSHIP_TRANSFERRED,
    ):
        for handler_name in EVENT_REGISTRY.handler_names_for(event_name, 1):
            assert handlers.supports(handler_name, event_name, 1)
