from unittest.mock import Mock
from uuid import uuid7

import pytest
from hamcrest import assert_that, equal_to, has_entries, has_length
from sqlmodel import Session, select
from starlette.testclient import TestClient

from api.core.config import Config
from api.domains.agent_memory.platform_models import PlatformMemorySettings
from api.domains.events.models import OutboxMessage
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError
from api.infrastructure.openrouter.client import OpenRouterClient
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.memory_app import create_memory_app
from api.tests.core.givenpy import given
from api.tests.steps.agent_memory import agent_memory_api_setup
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

BASE = "/api/v1/platform/settings/agent-memory"
CATALOG = [
    {
        "id": "openai/gpt-4.1-mini",
        "name": "GPT-4.1 mini",
        "output_modalities": ["text"],
        "supported_parameters": ["tools", "response_format"],
    },
    {
        "id": "openai/alternate",
        "name": "Alternate",
        "output_modalities": ["text"],
        "supported_parameters": ["tools", "structured_outputs"],
    },
    {
        "id": "text/no-tools",
        "name": "No tools",
        "output_modalities": ["text"],
        "supported_parameters": ["response_format"],
    },
    {
        "id": "text/no-structure",
        "name": "No structured responses",
        "output_modalities": ["text"],
        "supported_parameters": ["tools"],
    },
    {"id": "image/only", "name": "Image model", "output_modalities": ["image"], "supported_parameters": []},
]


def setup(context):
    config = context.injector.get(Config)
    config.memory_litellm_key_hashes = "a" * 64
    config.memory_litellm_active_key_hash = ""
    config.hindsight_api_key = "backend-service-test-key"
    delegate = context.injector.get(PostgresRepositoryDelegate)
    with delegate.engine.begin() as connection:
        connection.exec_driver_sql("TRUNCATE platform_memory_settings")


def admin(context):
    organization = context.organization
    del context.organization
    try:
        user_id = uuid7()
        there_is_a_user(id=user_id, email=f"platform-{user_id}@example.com", is_platform_admin=True)(context)
        there_is_an_access_token_for_user(user_id)(context)
    finally:
        context.organization = organization


def auth(context):
    return {"Authorization": f"Bearer {context.access_token}"}


@pytest.mark.parametrize(
    "method,path,payload",
    [("GET", "", None), ("GET", "/models", None), ("PUT", "", {"model": "openrouter/openai/alternate"})],
)
def test_organization_owner_cannot_manage_platform_memory(method, path, payload):
    with given(agent_memory_api_setup(setup)) as context:
        response = context.client.request(method, BASE + path, headers=auth(context), json=payload)
        assert_that(response.status_code, equal_to(403))


def test_platform_admin_without_membership_can_select_and_persist_global_memory_model(monkeypatch):
    with given(agent_memory_api_setup(setup, admin)) as context:
        monkeypatch.setattr(context.injector.get(OpenRouterClient), "list_models", Mock(return_value=CATALOG))
        read = context.client.get(BASE, headers=auth(context))
        assert_that(read.json(), has_entries(model="openrouter/openai/gpt-4.1-mini"))
        models = context.client.get(BASE + "/models", headers=auth(context)).json()
        assert_that(models, has_length(2))
        response = context.client.put(BASE, headers=auth(context), json={"model": "openrouter/openai/alternate"})
        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(response.json(), has_entries(model="openrouter/openai/alternate"))
        assert_that(
            context.client.get(BASE, headers=auth(context)).json(), has_entries(model="openrouter/openai/alternate")
        )
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            row = session.get(PlatformMemorySettings, 1)
            assert row is not None
            assert_that(row.model, equal_to("openrouter/openai/alternate"))
            events = session.exec(
                select(OutboxMessage).where(OutboxMessage.event_name == "platform.memory_model.changed")
            ).all()
            assert_that(events, has_length(1))
        context.client.put(BASE, headers=auth(context), json={"model": "openrouter/openai/alternate"})
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            assert_that(
                session.exec(
                    select(OutboxMessage).where(OutboxMessage.event_name == "platform.memory_model.changed")
                ).all(),
                has_length(1),
            )


@pytest.mark.parametrize(
    "model",
    [
        "openrouter/text/no-tools",
        "openrouter/text/no-structure",
        "openrouter/image/only",
        "openrouter/unknown/model",
        "litellm/openrouter/openai/alternate",
    ],
)
def test_unsupported_model_cannot_change_the_platform_choice(model, monkeypatch):
    with given(agent_memory_api_setup(setup, admin)) as context:
        monkeypatch.setattr(context.injector.get(OpenRouterClient), "list_models", Mock(return_value=CATALOG))
        response = context.client.put(BASE, headers=auth(context), json={"model": model})
        assert_that(response.status_code, equal_to(422))
        assert_that(
            context.client.get(BASE, headers=auth(context)).json(), has_entries(model="openrouter/openai/gpt-4.1-mini")
        )


def test_failed_model_key_update_does_not_persist_a_new_setting(monkeypatch):
    with given(agent_memory_api_setup(setup, admin)) as context:
        monkeypatch.setattr(context.injector.get(OpenRouterClient), "list_models", Mock(return_value=CATALOG))
        context.injector.get(LiteLLMClient).allow_memory_models.side_effect = LiteLLMError("key unavailable")
        response = context.client.put(BASE, headers=auth(context), json={"model": "openrouter/openai/alternate"})
        assert_that(response.status_code, equal_to(503))
        assert_that(
            context.client.get(BASE, headers=auth(context)).json(), has_entries(model="openrouter/openai/gpt-4.1-mini")
        )


@pytest.mark.parametrize("token", [None, "agent-test-key", "backend-service-test-key"])
def test_runtime_model_endpoint_only_accepts_the_hindsight_service_credential(token):
    with given(agent_memory_api_setup(setup)) as context:
        with TestClient(create_memory_app(context.injector)) as client:
            response = client.get(
                "/memory/runtime/v1/model", headers={"Authorization": f"Bearer {token}"} if token else {}
            )
            assert_that(response.status_code, equal_to(200 if token == "backend-service-test-key" else 401))


@pytest.mark.parametrize("hashes,active", [("", ""), ("a" * 64 + "," + "b" * 64, ""), ("a" * 64, "b" * 64)])
def test_unknown_or_ambiguous_active_key_cannot_change_settings(hashes, active, monkeypatch):
    with given(agent_memory_api_setup(setup, admin)) as context:
        monkeypatch.setattr(context.injector.get(OpenRouterClient), "list_models", Mock(return_value=CATALOG))
        config = context.injector.get(Config)
        config.memory_litellm_key_hashes = hashes
        config.memory_litellm_active_key_hash = active
        key_update = context.injector.get(LiteLLMClient).allow_memory_models
        response = context.client.put(BASE, headers=auth(context), json={"model": "openrouter/openai/alternate"})
        assert_that(response.status_code, equal_to(503))
        assert_that(
            context.client.get(BASE, headers=auth(context)).json(), has_entries(model="openrouter/openai/gpt-4.1-mini")
        )
        key_update.assert_not_called()


def test_configured_default_is_returned_before_a_choice_is_saved():
    with given(agent_memory_api_setup(setup, admin)) as context:
        context.injector.get(Config).memory_default_model = "openrouter/custom/default"
        assert_that(
            context.client.get(BASE, headers=auth(context)).json(), has_entries(model="openrouter/custom/default")
        )
        with TestClient(create_memory_app(context.injector)) as client:
            response = client.get(
                "/memory/runtime/v1/model", headers={"Authorization": "Bearer backend-service-test-key"}
            )
            assert_that(response.json(), has_entries(model="openrouter/custom/default"))
