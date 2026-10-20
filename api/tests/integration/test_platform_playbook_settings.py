from unittest.mock import Mock
from uuid import uuid7

import pytest
from fastapi import status
from hamcrest import assert_that, contains_exactly, equal_to, has_entries, has_length
from sqlmodel import Session, select

from api.domains.events.models import OutboxMessage
from api.domains.playbooks.platform_models import PlatformPlaybookSettings
from api.infrastructure.openrouter.client import OpenRouterClient, OpenRouterError
from api.tests.core.givenpy import given, then, when
from api.tests.steps.playbooks import playbooks_api_setup
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

BASE = "/api/v1/platform/settings/playbooks"
CATALOG = [
    {"id": "openai/gpt-4.1-mini", "name": "GPT-4.1 mini", "output_modalities": ["text"]},
    {"id": "anthropic/claude-sonnet", "name": "Claude Sonnet", "output_modalities": ["text"]},
    {"id": "image/only", "name": "Image model", "output_modalities": ["image"]},
]


def a_platform_admin_without_membership():
    def step(context):
        organization = context.organization
        del context.organization
        try:
            user_id = uuid7()
            there_is_a_user(id=user_id, email=f"platform-{user_id}@example.com", is_platform_admin=True)(context)
            there_is_an_access_token_for_user(user_id)(context)
        finally:
            context.organization = organization

    return step


def the_model_catalog_is(models):
    def step(context):
        context.catalog = Mock(return_value=models) if isinstance(models, list) else Mock(side_effect=models)
        context.injector.get(OpenRouterClient).list_models = context.catalog

    return step


def _auth(context):
    return {"Authorization": f"Bearer {context.access_token}"}


def _changed_events(context):
    with Session(context.postgres_delegate.engine) as session:
        return session.exec(
            select(OutboxMessage).where(OutboxMessage.event_name == "platform.playbook_model.changed")
        ).all()


@pytest.mark.parametrize(
    "method,path,payload",
    [("GET", "", None), ("GET", "/models", None), ("PUT", "", {"model": "openrouter/anthropic/claude-sonnet"})],
)
def test_an_organization_owner_cannot_manage_the_platform_playbook_model(method, path, payload):
    with given(playbooks_api_setup(the_model_catalog_is(CATALOG))) as context:
        with when("an Organization Owner calls the Platform setting"):
            response = context.client.request(method, BASE + path, headers=_auth(context), json=payload)

        with then("it is forbidden"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_the_deployment_default_applies_until_a_model_is_chosen():
    with given(playbooks_api_setup(a_platform_admin_without_membership())) as context:
        with when("a Platform Administrator reads the setting"):
            response = context.client.get(BASE, headers=_auth(context))

        with then("the deployment default is reported with no change time"):
            assert_that(response.json(), has_entries(model="openrouter/openai/gpt-4.1-mini", updated_at=None))


def test_the_catalog_offers_only_text_models():
    with given(playbooks_api_setup(a_platform_admin_without_membership(), the_model_catalog_is(CATALOG))) as context:
        with when("a Platform Administrator lists the models"):
            response = context.client.get(BASE + "/models", headers=_auth(context))

        with then("image-only models are left out"):
            assert_that(
                [item["value"] for item in response.json()],
                contains_exactly("openrouter/openai/gpt-4.1-mini", "openrouter/anthropic/claude-sonnet"),
            )


def test_choosing_a_model_persists_it_with_one_audit_event():
    with given(playbooks_api_setup(a_platform_admin_without_membership(), the_model_catalog_is(CATALOG))) as context:
        with when("a Platform Administrator saves the same new model twice"):
            first = context.client.put(
                BASE, headers=_auth(context), json={"model": "openrouter/anthropic/claude-sonnet"}
            )
            context.client.put(BASE, headers=_auth(context), json={"model": "openrouter/anthropic/claude-sonnet"})

        with then("the choice is stored once and audited once"):
            assert_that(first.status_code, equal_to(status.HTTP_200_OK))
            with Session(context.postgres_delegate.engine) as session:
                row = session.get(PlatformPlaybookSettings, 1)
            assert row is not None
            assert_that(row.model, equal_to("openrouter/anthropic/claude-sonnet"))
            events = _changed_events(context)
            assert_that(events, has_length(1))
            assert_that(
                events[0].payload,
                has_entries(previous="openrouter/openai/gpt-4.1-mini", current="openrouter/anthropic/claude-sonnet"),
            )


@pytest.mark.parametrize(
    "model", ["openrouter/image/only", "openrouter/unknown/model", "litellm/openrouter/openai/gpt-4.1-mini"]
)
def test_unsupported_models_are_refused(model):
    with given(playbooks_api_setup(a_platform_admin_without_membership(), the_model_catalog_is(CATALOG))) as context:
        with when("a Platform Administrator saves an unsupported model"):
            response = context.client.put(BASE, headers=_auth(context), json={"model": model})

        with then("it is refused and nothing changes"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))
            assert_that(_changed_events(context), has_length(0))


def test_an_unavailable_catalog_changes_nothing():
    with given(
        playbooks_api_setup(
            a_platform_admin_without_membership(), the_model_catalog_is(OpenRouterError("catalog down"))
        )
    ) as context:
        with when("a Platform Administrator saves while the catalog is unavailable"):
            response = context.client.put(
                BASE, headers=_auth(context), json={"model": "openrouter/anthropic/claude-sonnet"}
            )

        with then("the request fails without changing the setting"):
            assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))
            assert_that(_changed_events(context), has_length(0))
