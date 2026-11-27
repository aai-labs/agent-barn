"""Every Domain Event reaches the handlers the catalog names for it.

A handler named for an Event that does not list it as supported dead-letters every
delivery (UNKNOWN_HANDLER or UNSUPPORTED_EVENT) as soon as a worker claims it, so the
audit record, email or projection it stands for silently never happens. This walks the
whole catalog against the registry the workers are built with, rather than a
hand-picked list of Events.
"""

from hamcrest import assert_that, equal_to

from api.domains.events.catalog import EVENT_REGISTRY
from api.domains.events.handlers import EventHandlerRegistry
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule


def test_every_handler_a_catalog_event_names_supports_that_event():
    with given(
        [
            set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        ]
    ) as context:
        handlers = context.injector.get(EventHandlerRegistry)

        unsupported = [
            (definition.event_name, handler_name)
            for definition in EVENT_REGISTRY.list_definitions()
            for handler_name in definition.handler_names
            if not handlers.supports(handler_name, definition.event_name, definition.schema_version)
        ]

        assert_that(unsupported, equal_to([]))
