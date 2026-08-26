import json
from typing import cast
from unittest.mock import MagicMock, patch
from uuid import uuid7

import httpx
from fastapi import HTTPException, status
from hamcrest import (
    assert_that,
    contains_string,
    equal_to,
    greater_than,
    has_item,
    has_key,
    is_in,
    is_not,
    none,
)
from starlette.testclient import TestClient

from api.domains.agents.models import (
    AgentStatus,
    AgentTemplateOverrideSourceType,
    AgentTemplateOverrideVersion,
    AgentType,
    SecretProvider,
)
from api.domains.agents.override_repository import AgentOverrideRepository
from api.domains.agents.repository import AgentRepository
from api.domains.events.catalog import (
    AGENT_CREATED,
    AGENT_DELETED,
    AGENT_SECRET_ADDED,
    AGENT_SECRET_REMOVED,
    AGENT_SECRET_UPDATED,
    AGENT_STARTED,
    AGENT_STOPPED,
    AGENT_TEMPLATE_OVERRIDE_DRAFT_SAVED,
    AGENT_TEMPLATE_OVERRIDE_PUBLISHED,
    AGENT_TEMPLATE_OVERRIDE_SELECTED,
    AGENT_UPDATED,
)
from api.domains.events.models import EventDeliveryStatus, OutboxMessage
from api.domains.events.processor import EventDeliveryProcessor
from api.domains.events.repository import OutboxMessageRepository
from api.domains.events.security_audit import SecurityAuditRepository
from api.domains.organizations.repository import OrganizationRepository
from api.domains.templates.models import AgentTemplate, PlatformTemplate
from api.domains.templates.repository import TemplateRepository
from api.infrastructure.integration_validators.result import IntegrationValidationResult
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    FAKE_LITELLM_KEY,
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    skill_is_assigned_to_agent,
    there_is_a_skill,
    there_is_a_skill_for_another_org,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.template import (
    there_is_a_template,
    there_is_a_template_skill,
    there_is_a_template_skill_group,
)

_BASE = "/api/v1/organizations/{organization_id}/agents"

# Agents run in k3d while the API runs outside it (compose or the host), so the
# pod-facing ingest URL is an override, not the in-cluster default.
_INGEST_BASE_URL = "http://host.docker.internal:8001/ingest/v1"

_VALID_CREATE = {
    "name": "My Agent",
    "template_key": "test-template",
}

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "API_EXTERNAL_URL": "https://api.test.com",
            "SKIP_SLACK_TOKEN_VALIDATION": "true",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_a_template(),
]

_VALID_CREATE_HERMES = {
    "name": "My Hermes Agent",
    "agent_type": "hermes",
    "template_key": "test-template",
}

_GIVEN_WITH_HERMES_IMAGE = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "API_EXTERNAL_URL": "https://api.test.com",
            "HERMES_IMAGE": "nousresearch/hermes-agent:v1.0",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_a_template(),
]


# Same as _GIVEN but with no server-owned Google OAuth client. Set here rather than in a
# later step because Config is built (and cached) when the injector is prepared, and a
# developer's root .env may define real Google credentials.
_GIVEN_WITHOUT_GOOGLE_CLIENT = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "API_EXTERNAL_URL": "https://api.test.com",
            "SKIP_SLACK_TOKEN_VALIDATION": "true",
            "GOOGLE_CLOUD_CLIENT_ID": "",
            "GOOGLE_CLOUD_CLIENT_SECRET": "",
        }
    ),
    *_GIVEN[1:],
]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _outbox_messages(context) -> list[OutboxMessage]:
    return context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)


def _pin_override_to_source(
    context, source: AgentTemplate | PlatformTemplate, source_type: AgentTemplateOverrideSourceType
):
    version = AgentTemplateOverrideVersion(
        organization_id=context.agent.organization_id,
        agent_id=context.agent.id,
        version=1,
        created_by_user_id=context.user.id,
        source_type=source_type,
        source_template_key=source.template_key,
        source_template_version=source.version,
        source_platform_template_id=source.id if source_type == AgentTemplateOverrideSourceType.PLATFORM else None,
        source_agent_template_id=source.id if source_type == AgentTemplateOverrideSourceType.ORGANIZATION else None,
        template_name=source.template_name,
        description=source.description,
        soul_md=source.soul_md,
        identity_md=source.identity_md,
        user_md=source.user_md,
        tools_md=source.tools_md,
        agents_md=source.agents_md,
        boot_md=source.boot_md,
        bootstrap_md=source.bootstrap_md,
        heartbeat_md=source.heartbeat_md,
    )
    delegate = context.injector.get(PostgresRepositoryDelegate)
    delegate.save(version)
    context.agent.platform_template_id = None
    context.agent.agent_template_id = None
    context.agent.agent_template_override_version_id = version.id
    context.injector.get(AgentRepository).save(context.agent)
    return version


def test_create_agent_rejects_model_not_in_org_allowlist():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        litellm: MagicMock = context.injector.get(LiteLLMClient)
        org_repo: OrganizationRepository = context.injector.get(OrganizationRepository)
        org = org_repo.get(context.organization.id)
        assert org is not None
        org.allowed_models = []
        org_repo.save(org)

        with when("I create an agent with a model while the org allowlist is empty"):
            payload = {**_VALID_CREATE, "model": "litellm/openrouter/openai/gpt-4o"}
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("not in the allowed model list"))
            litellm.generate_key.assert_not_called()


def test_create_agent_emits_created_domain_event():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a Slack agent with valid data"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("an Agent created Domain Event is persisted"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            messages = _outbox_messages(context)
            created_events = [message for message in messages if message.event_name == AGENT_CREATED]
            assert_that(len(created_events), equal_to(1))
            assert_that(created_events[0].payload["agent_name"], equal_to("My Agent"))
            assert_that(created_events[0].payload["created_by_user_id"], equal_to(str(context.user.id)))


def test_create_agent_missing_template_key_returns_422():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        payload = {**_VALID_CREATE}
        del payload["template_key"]

        with when("I create an agent without template_key"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 422"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_create_agent_rejects_template_slug_after_key_migration():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        payload = {**_VALID_CREATE, "template_slug": _VALID_CREATE["template_key"]}
        del payload["template_key"]

        with when("I create an agent using the removed template_slug field"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 422"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_create_agent_unknown_template_key_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        litellm: MagicMock = context.injector.get(LiteLLMClient)
        payload = {**_VALID_CREATE, "template_key": "no-such-template"}

        with when("I create an agent referencing a non-existent template"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            litellm.generate_key.assert_not_called()


def test_create_agent_missing_shared_credential_returns_404_before_litellm_key_generation():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        litellm: MagicMock = context.injector.get(LiteLLMClient)
        payload = {
            **_VALID_CREATE,
            "shared_credentials": [{"shared_credential_id": str(uuid7())}],
        }

        with when("I create an agent with a missing shared credential"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 404 without allocating a LiteLLM key"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            litellm.generate_key.assert_not_called()


def test_create_agent_no_auth_returns_401():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create an agent without a token"):
            response = client.post(_BASE, json=_VALID_CREATE)

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_create_agent_pins_latest_template_version():
    with given([*_GIVEN, there_is_a_template(version=2, soul_md="# Soul v2")]) as context:
        client: TestClient = context.client

        with when("I create an agent referencing a lineage with two versions"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("it returns 201 pinned to the latest version"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["template_key"], equal_to("test-template"))
            assert_that(body["template_version"], equal_to(2))


def test_create_agent_pins_specific_version():
    with given([*_GIVEN, there_is_a_template(version=2, soul_md="# Soul v2")]) as context:
        client: TestClient = context.client

        with when("I create an agent requesting v1 of a two-version lineage"):
            payload = {**_VALID_CREATE, "template_version": 1}
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it pins to the requested version, not the latest"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["template_version"], equal_to(1))


def test_create_agent_unknown_version_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create an agent requesting a non-existent version"):
            payload = {**_VALID_CREATE, "template_version": 99}
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_create_agent_does_not_create_template_rows():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create an agent from the shared template"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("the lineage still has only its original version"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            template_repository: TemplateRepository = context.injector.get(TemplateRepository)
            latest = template_repository.get_latest_org_template(context.organization.id, "test-template")
            assert_that(latest, is_not(none()))
            assert latest is not None
            assert_that(latest.version, equal_to(1))


def test_create_agent_default_approval_mode_is_auto():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create an agent without specifying approval_mode"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("the response has approval_mode set to auto"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["approval_mode"], equal_to("auto"))


def test_create_openclaw_agent_with_approval_mode_off_returns_400():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create an OpenClaw agent with approval_mode off"):
            response = client.post(
                _BASE,
                json={**_VALID_CREATE, "approval_mode": "off"},
                headers=_auth(context),
            )

        with then("it returns 400 because OpenClaw does not support command approval"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("OpenClaw"))


def test_create_openclaw_agent_with_approval_mode_manual_returns_400_and_does_not_persist_agent():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create an OpenClaw agent with approval_mode manual"):
            response = client.post(
                _BASE,
                json={**_VALID_CREATE, "approval_mode": "manual"},
                headers=_auth(context),
            )

        with then("it returns 400 and no agent is persisted"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("OpenClaw"))
            agents = client.get(_BASE, headers=_auth(context)).json()["items"]
            assert_that(len(agents), equal_to(0))


def test_create_hermes_agent_with_approval_mode_manual():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a Hermes agent with approval_mode manual"):
            response = client.post(
                _BASE,
                json={**_VALID_CREATE_HERMES, "approval_mode": "manual"},
                headers=_auth(context),
            )

        with then("the response has approval_mode set to manual"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["approval_mode"], equal_to("manual"))


def test_create_hermes_agent_with_approval_mode_auto():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a Hermes agent with approval_mode auto"):
            response = client.post(
                _BASE,
                json={**_VALID_CREATE_HERMES, "approval_mode": "auto"},
                headers=_auth(context),
            )

        with then("the response has approval_mode set to auto"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["approval_mode"], equal_to("auto"))


def test_create_hermes_agent_with_approval_mode_off():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a Hermes agent with approval_mode off"):
            response = client.post(
                _BASE,
                json={**_VALID_CREATE_HERMES, "approval_mode": "off"},
                headers=_auth(context),
            )

        with then("the response has approval_mode set to off"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["approval_mode"], equal_to("off"))


def test_list_agents_returns_active_only():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(name="Active Agent"),
            there_is_an_agent(name="Deleted Agent", deleted=True),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I list agents"):
            response = client.get(_BASE, headers=_auth(context))

        with then("only the active agent is returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            items = response.json()["items"]
            assert_that(len(items), equal_to(1))
            assert_that(items[0]["name"], equal_to("Active Agent"))


def test_list_agents_status_filter():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(name="Stopped Agent", status=AgentStatus.STOPPED),
            there_is_an_agent(name="Running Agent", status=AgentStatus.RUNNING),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I filter by status=RUNNING"):
            response = client.get(f"{_BASE}?status=RUNNING", headers=_auth(context))

        with then("only the running agent is returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            items = response.json()["items"]
            assert_that(len(items), equal_to(1))
            assert_that(items[0]["name"], equal_to("Running Agent"))


def test_list_agents_no_auth_returns_401():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I list agents without a token"):
            response = client.get(_BASE)

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_get_agent_returns_agent():
    with given([*_GIVEN, there_is_an_agent(name="Fetchable Agent")]) as context:
        client: TestClient = context.client

        with when("I get the agent by id"):
            response = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context))

        with then("it returns the agent"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["name"], equal_to("Fetchable Agent"))


def test_get_deleted_agent_returns_404():
    with given([*_GIVEN, there_is_an_agent(deleted=True)]) as context:
        client: TestClient = context.client

        with when("I get a deleted agent"):
            response = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_get_agent_no_auth_returns_401():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I get an agent without a token"):
            response = client.get(f"{_BASE}/{context.agent.id}")

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_patch_agent_updates_name():
    with given([*_GIVEN, there_is_an_agent(name="Old Name")]) as context:
        client: TestClient = context.client

        with when("I patch the agent name"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"name": "New Name"},
                headers=_auth(context),
            )

        with then("it returns 200 with the updated name"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["name"], equal_to("New Name"))


def test_patch_agent_repins_template():
    # _GIVEN seeds the "test-template" lineage; the agent has its own generated
    # lineage, so re-pinning to "test-template" v1 is an observable change.
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I re-pin the agent to a different template version"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"template_key": "test-template", "template_version": 1},
                headers=_auth(context),
            )

        with then("it returns 200 pinned to the requested template"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["template_key"], equal_to("test-template"))
            assert_that(body["template_version"], equal_to(1))


def test_patch_agent_repin_unknown_version_returns_404():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I re-pin to a non-existent version"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"template_key": "test-template", "template_version": 99},
                headers=_auth(context),
            )

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_patch_agent_repin_requires_both_template_key_and_version():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I send only template_key without a version"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"template_key": "test-template"},
                headers=_auth(context),
            )

        with then("it returns 422"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_patch_agent_repin_rejects_template_slug_after_key_migration():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I re-pin using the removed template_slug field"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"template_slug": "test-template", "template_version": 1},
                headers=_auth(context),
            )

        with then("it returns 422"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_patch_running_agent_returns_409():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I patch a running agent"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"name": "Should Fail"},
                headers=_auth(context),
            )

        with then("it returns 409"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_patch_agent_no_auth_returns_401():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch an agent without a token"):
            response = client.patch(f"{_BASE}/{context.agent.id}", json={"name": "X"})

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_patch_hermes_agent_approval_mode_to_manual():
    with given([*_GIVEN, there_is_an_agent(agent_type=AgentType.HERMES)]) as context:
        client: TestClient = context.client
        agent_id = str(context.agent.id)

        with when("I update the Hermes agent's approval_mode to manual"):
            response = client.patch(
                f"{_BASE}/{agent_id}",
                json={"approval_mode": "manual"},
                headers=_auth(context),
            )

        with then("the response reflects the new approval_mode"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["approval_mode"], equal_to("manual"))


def test_patch_hermes_agent_approval_mode_to_off():
    with given([*_GIVEN, there_is_an_agent(agent_type=AgentType.HERMES)]) as context:
        client: TestClient = context.client
        agent_id = str(context.agent.id)

        with when("I update the Hermes agent's approval_mode to off"):
            response = client.patch(
                f"{_BASE}/{agent_id}",
                json={"approval_mode": "off"},
                headers=_auth(context),
            )

        with then("the response reflects the new approval_mode"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["approval_mode"], equal_to("off"))


def test_patch_openclaw_agent_approval_mode_manual_returns_400_and_leaves_agent_unchanged():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        agent_id = str(context.agent.id)
        original = client.get(f"{_BASE}/{agent_id}", headers=_auth(context)).json()

        with when("I update the OpenClaw agent's approval_mode to manual"):
            response = client.patch(
                f"{_BASE}/{agent_id}",
                json={"approval_mode": "manual"},
                headers=_auth(context),
            )

        with then("it returns 400 and the agent is unchanged"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("OpenClaw"))
            current = client.get(f"{_BASE}/{agent_id}", headers=_auth(context)).json()
            assert_that(current["approval_mode"], equal_to(original["approval_mode"]))


def test_patch_openclaw_agent_approval_mode_off_returns_400():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        agent_id = str(context.agent.id)

        with when("I update the OpenClaw agent's approval_mode to off"):
            response = client.patch(
                f"{_BASE}/{agent_id}",
                json={"approval_mode": "off"},
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("OpenClaw"))


def test_patch_agent_approval_mode_null_returns_422_and_leaves_agent_unchanged():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        agent_id = str(context.agent.id)

        with when("I update approval_mode to null"):
            response = client.patch(
                f"{_BASE}/{agent_id}",
                json={"approval_mode": None},
                headers=_auth(context),
            )

        with then("it rejects null rather than clearing the non-null setting"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))
            current = client.get(f"{_BASE}/{agent_id}", headers=_auth(context)).json()
            assert_that(current["approval_mode"], equal_to("auto"))


_JIRA_CONTENT = {
    "site_url": "https://acme.atlassian.net",
    "email": "a@b.com",
    "api_token": "jira-tok",
}


def _providers(response) -> list[str]:
    return [s["provider"] for s in response.json()["secrets"]]


def test_patch_agent_adds_secret():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch the agent with a jira secret"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )

        with then("it returns 200 and the agent exposes the jira secret"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_providers(response), equal_to(["jira"]))
            jira = response.json()["secrets"][0]
            assert_that(jira["secret_name"], equal_to("Jira credential"))


def test_patch_agent_rejects_retired_google_provider():
    """The per-service Google providers were removed outright — enum member, content
    model and rows (deleted by migration c9f1b30a7d42). A stale client naming one must be
    refused by request validation rather than reaching the database."""
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch the agent with a retired google sheets secret"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={
                    "secrets": [
                        {
                            "provider": "google_sheets",
                            "content": {"refresh_token": "rt-sheets"},
                        }
                    ]
                },
                headers=_auth(context),
            )

        with then("it is rejected as an unknown provider"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))
            assert_that("google_sheets" in response.text, equal_to(True))


def test_patch_agent_upserts_existing_secret():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        repository: AgentRepository = context.injector.get(AgentRepository)

        with when("I patch the same provider twice with different content"):
            client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={
                    "secrets": [
                        {
                            "provider": "jira",
                            "content": {**_JIRA_CONTENT, "api_token": "new-tok"},
                        }
                    ]
                },
                headers=_auth(context),
            )

        with then("there is exactly one jira row (upsert, not duplicate)"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            rows = repository.get_secrets_for_agent(context.agent.id)
            jira_rows = [r for r in rows if r.provider == SecretProvider.JIRA]
            assert_that(len(jira_rows), equal_to(1))


def test_patch_agent_removes_secret():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I add then remove a jira secret"):
            client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"removed_secret_providers": ["jira"]},
                headers=_auth(context),
            )

        with then("the jira secret is gone"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_providers(response), equal_to([]))


def test_patch_running_agent_with_secret_returns_409():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client

        with when("I patch a running agent with a secret"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )

        with then("it returns 409"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_patch_agent_secret_in_both_lists_returns_422():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch with a provider in both secrets and removed lists"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={
                    "secrets": [{"provider": "jira", "content": _JIRA_CONTENT}],
                    "removed_secret_providers": ["jira"],
                },
                headers=_auth(context),
            )

        with then("it returns 422"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_patch_agent_invalid_secret_content_returns_422():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch with jira content missing api_token"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": {"site_url": "x", "email": "y"}}]},
                headers=_auth(context),
            )

        with then("it returns 422"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


# --- optional/multi repos for GitHub and Bitbucket secrets (AF-162) ---

_GITHUB_CONTENT_NO_REPOS = {
    "token": "ghp_token",
    "owner": "my-org",
    "org": "my-org",
}

_BITBUCKET_CONTENT_NO_REPOS = {
    "workspace": "my-workspace",
    "email": "a@b.com",
    "api_token": "bb-tok",
}


def test_patch_agent_adds_github_secret_without_repos():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch the agent with a GitHub secret and no repos"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "github", "content": _GITHUB_CONTENT_NO_REPOS}]},
                headers=_auth(context),
            )

        with then("it returns 200 and the agent exposes the github secret"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_providers(response), equal_to(["github"]))


def test_patch_agent_adds_github_secret_with_multiple_repos():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch the agent with a GitHub secret listing multiple repos"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={
                    "secrets": [
                        {
                            "provider": "github",
                            "content": {
                                **_GITHUB_CONTENT_NO_REPOS,
                                "repos": ["repo-a", "repo-b"],
                            },
                        }
                    ]
                },
                headers=_auth(context),
            )

        with then("it returns 200 and the agent exposes the github secret"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_providers(response), equal_to(["github"]))


def test_patch_agent_adds_bitbucket_secret_without_repos():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch the agent with a Bitbucket secret and no repos"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={
                    "secrets": [
                        {
                            "provider": "bitbucket",
                            "content": _BITBUCKET_CONTENT_NO_REPOS,
                        }
                    ]
                },
                headers=_auth(context),
            )

        with then("it returns 200 and the agent exposes the bitbucket secret"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_providers(response), equal_to(["bitbucket"]))


def test_patch_agent_adds_bitbucket_secret_with_multiple_repos():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch the agent with a Bitbucket secret listing multiple repos"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={
                    "secrets": [
                        {
                            "provider": "bitbucket",
                            "content": {
                                **_BITBUCKET_CONTENT_NO_REPOS,
                                "repos": ["repo-a", "repo-b"],
                            },
                        }
                    ]
                },
                headers=_auth(context),
            )

        with then("it returns 200 and the agent exposes the bitbucket secret"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_providers(response), equal_to(["bitbucket"]))


def test_validate_integration_with_no_repos_returns_valid():
    """A credential with zero configured repos is a legitimate config — the validate
    endpoint must not report it as invalid."""
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        client.patch(
            f"{_BASE}/{context.agent.id}",
            json={"secrets": [{"provider": "github", "content": _GITHUB_CONTENT_NO_REPOS}]},
            headers=_auth(context),
        )

        user_resp = httpx.Response(
            200,
            json={"login": "alice"},
            request=httpx.Request("GET", "https://api.github.com/user"),
        )

        with (
            when("I validate the GitHub integration"),
            patch(
                "api.infrastructure.integration_validators.github.httpx.get",
                return_value=user_resp,
            ),
        ):
            response = client.post(
                f"{_BASE}/{context.agent.id}/integrations/github/validate",
                headers=_auth(context),
            )

        with then("it returns a valid status, not invalid, despite no repos configured"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["validation_status"], equal_to("valid"))


def test_start_agent_sets_status_running():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("it returns 200 with status RUNNING and k8s resources are created"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["status"], equal_to(AgentStatus.RUNNING.value))
            k8s.delete_config_map.assert_called_once()
            k8s.delete_secret.assert_called_once()
            k8s.create_config_map.assert_called_once()
            k8s.create_secret.assert_called_once()
            k8s.create_pvc.assert_called_once()
            k8s.create_service.assert_called_once()
            k8s.create_deployment.assert_called_once()
            service = k8s.create_service.call_args.args[1]
            assert_that(
                service.metadata.labels["org-name"],
                equal_to("test-organization"),
            )
            assert_that(
                service.metadata.labels["agent-name"],
                equal_to("test-agent"),
            )


def test_start_agent_emits_started_domain_event_and_delivery():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I start the agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("an Agent started Domain Event and pending email delivery are persisted"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            messages = _outbox_messages(context)
            started_events = [message for message in messages if message.event_name == AGENT_STARTED]
            assert_that(len(started_events), equal_to(1))
            assert_that(started_events[0].payload["previous_status"], equal_to(AgentStatus.STOPPED.value))
            assert_that(started_events[0].payload["new_status"], equal_to(AgentStatus.RUNNING.value))
            deliveries = context.injector.get(AgentRepository).outbox_repository.list_deliveries_for_event(
                started_events[0].event_id
            )
            assert_that(len(deliveries), equal_to(1))
            # Delivery is always persisted PENDING; the immediate enqueue attempt right
            # after is best-effort (falls back to background reconciliation on failure),
            # so whether it's already ENQUEUED here depends on Redis being reachable.
            assert_that(deliveries[0].status, is_in([EventDeliveryStatus.PENDING, EventDeliveryStatus.ENQUEUED]))


def test_start_agent_wires_telemetry_push_into_the_secret():
    with given(
        [
            set_env_variable({"INGEST_BASE_URL": _INGEST_BASE_URL}),
            *_GIVEN,
            there_is_an_agent(),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the secret carries the telemetry push wiring the plugins read"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            _, secret = k8s.create_secret.call_args.args
            assert_that(secret.string_data["AGENT_ID"], equal_to(str(context.agent.id)))
            assert_that(secret.string_data["INGEST_URL"], equal_to(_INGEST_BASE_URL))
            assert_that(secret.string_data["INGEST_API_KEY"], is_not(equal_to("")))


def test_start_already_running_returns_409():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I start an already running agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("it returns 409"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_start_agent_rejects_model_removed_from_allowlist():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(model="litellm/openrouter/openai/gpt-4o"),
        ]
    ) as context:
        client: TestClient = context.client
        org_repo: OrganizationRepository = context.injector.get(OrganizationRepository)
        org = org_repo.get(context.organization.id)
        assert org is not None
        # Allowlist changed after the agent was created: gpt-4o is no longer permitted.
        org.allowed_models = ["anthropic/*"]
        org_repo.save(org)

        with when("I start the agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("allowed model list"))


def test_start_agent_no_auth_returns_401():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I start an agent without a token"):
            response = client.post(f"{_BASE}/{context.agent.id}/start")

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_stop_agent_sets_status_stopped():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I stop the agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/stop", headers=_auth(context))

        with then("it returns 200 with status STOPPED and deployment is deleted"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["status"], equal_to(AgentStatus.STOPPED.value))
            k8s.delete_deployment.assert_called_once()


def test_stop_agent_emits_stopped_domain_event_and_delivery():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I stop the agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/stop", headers=_auth(context))

        with then("an Agent stopped Domain Event and pending email delivery are persisted"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            messages = _outbox_messages(context)
            stopped_events = [message for message in messages if message.event_name == AGENT_STOPPED]
            assert_that(len(stopped_events), equal_to(1))
            assert_that(stopped_events[0].payload["previous_status"], equal_to(AgentStatus.RUNNING.value))
            assert_that(stopped_events[0].payload["new_status"], equal_to(AgentStatus.STOPPED.value))
            deliveries = context.injector.get(AgentRepository).outbox_repository.list_deliveries_for_event(
                stopped_events[0].event_id
            )
            assert_that(len(deliveries), equal_to(1))
            # Delivery is always persisted PENDING; the immediate enqueue attempt right
            # after is best-effort (falls back to background reconciliation on failure),
            # so whether it's already ENQUEUED here depends on Redis being reachable.
            assert_that(deliveries[0].status, is_in([EventDeliveryStatus.PENDING, EventDeliveryStatus.ENQUEUED]))


def test_update_agent_emits_updated_domain_event_with_field_changes():
    with given([*_GIVEN, there_is_an_agent(name="Old Name")]) as context:
        client: TestClient = context.client

        with when("I rename the agent"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"name": "New Name"},
                headers=_auth(context),
            )

        with then("an agent.updated Domain Event carries the before/after name"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            messages = _outbox_messages(context)
            updated_events = [message for message in messages if message.event_name == AGENT_UPDATED]
            assert_that(len(updated_events), equal_to(1))
            field_changes = updated_events[0].payload["field_changes"]
            assert_that(field_changes["name"]["previous"], equal_to("Old Name"))
            assert_that(field_changes["name"]["new"], equal_to("New Name"))
            # Regression: actor_display must be the acting user's name, not the
            # ActorIdentity type string ("MEMBERSHIP"/"USER").
            assert_that(updated_events[0].payload["actor_display"], equal_to("Test User"))


def test_update_agent_with_no_tracked_field_change_emits_no_updated_event():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch the agent with only a secret, no tracked scalar field"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )

        with then("no agent.updated Domain Event is staged"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            messages = _outbox_messages(context)
            updated_events = [message for message in messages if message.event_name == AGENT_UPDATED]
            assert_that(len(updated_events), equal_to(0))


def test_delete_agent_emits_deleted_domain_event():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I delete the agent"):
            response = client.delete(f"{_BASE}/{context.agent.id}", headers=_auth(context))

        with then("an agent.deleted Domain Event is persisted"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            messages = _outbox_messages(context)
            deleted_events = [message for message in messages if message.event_name == AGENT_DELETED]
            assert_that(len(deleted_events), equal_to(1))
            assert_that(deleted_events[0].payload["agent_id"], equal_to(str(context.agent.id)))
            assert_that(deleted_events[0].payload["actor_display"], equal_to("Test User"))


def test_patch_agent_add_secret_emits_secret_added_domain_event():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I add a jira secret"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )

        with then("an agent.secret.added Domain Event is persisted without secret content"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            messages = _outbox_messages(context)
            added_events = [message for message in messages if message.event_name == AGENT_SECRET_ADDED]
            assert_that(len(added_events), equal_to(1))
            assert_that(added_events[0].payload["provider"], equal_to("jira"))
            assert_that(added_events[0].payload, is_not(has_key("content")))
            assert_that(added_events[0].payload["actor_display"], equal_to("Test User"))


def test_patch_agent_update_secret_emits_secret_updated_domain_event():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch the same provider twice with different content"):
            client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": {**_JIRA_CONTENT, "api_token": "new-tok"}}]},
                headers=_auth(context),
            )

        with then("an agent.secret.updated Domain Event is persisted"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            messages = _outbox_messages(context)
            updated_events = [message for message in messages if message.event_name == AGENT_SECRET_UPDATED]
            assert_that(len(updated_events), equal_to(1))
            assert_that(updated_events[0].payload["provider"], equal_to("jira"))


def test_patch_agent_remove_secret_emits_secret_removed_domain_event():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I add then remove a jira secret"):
            client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"removed_secret_providers": ["jira"]},
                headers=_auth(context),
            )

        with then("an agent.secret.removed Domain Event is persisted"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            messages = _outbox_messages(context)
            removed_events = [message for message in messages if message.event_name == AGENT_SECRET_REMOVED]
            assert_that(len(removed_events), equal_to(1))
            assert_that(removed_events[0].payload["provider"], equal_to("jira"))


def test_agent_updated_event_projects_to_durable_security_audit_record():
    with given([*_GIVEN, there_is_an_agent(name="Old Name")]) as context:
        client: TestClient = context.client

        with when("I rename the agent and the delivery is processed"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"name": "New Name"},
                headers=_auth(context),
            )
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            outbox_repository = context.injector.get(OutboxMessageRepository)
            messages = _outbox_messages(context)
            updated_event = next(m for m in messages if m.event_name == AGENT_UPDATED)
            delivery = outbox_repository.list_deliveries_for_event(updated_event.event_id)[0]
            outbox_repository.mark_delivery_enqueued(delivery.id)
            processed = context.injector.get(EventDeliveryProcessor).process(delivery.id)

        with then("a durable Security Audit Record is projected"):
            assert_that(processed, equal_to(True))
            audit_record = context.injector.get(SecurityAuditRepository).get_by_event_id(updated_event.event_id)
            assert_that(audit_record, is_not(none()))
            assert audit_record is not None
            assert_that(audit_record.action, equal_to(AGENT_UPDATED))
            assert_that(audit_record.subject_id, equal_to(str(context.agent.id)))


def test_stop_non_running_agent_returns_409():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        client: TestClient = context.client

        with when("I stop a non-running agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/stop", headers=_auth(context))

        with then("it returns 409"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_stop_agent_no_auth_returns_401():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client

        with when("I stop an agent without a token"):
            response = client.post(f"{_BASE}/{context.agent.id}/stop")

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_delete_agent_soft_deletes():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        agent_id = context.agent.id

        with when("I delete the agent"):
            response = client.delete(f"{_BASE}/{agent_id}", headers=_auth(context))

        with then("it returns 204 and the agent has deleted_at set"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))

            repository: AgentRepository = context.injector.get(AgentRepository)
            from sqlmodel import Session, col, select

            from api.domains.agents.models import Agent

            with Session(repository.delegate.engine) as session:
                agent = session.exec(select(Agent).where(col(Agent.id) == agent_id)).first()
            assert agent is not None
            assert_that(agent.deleted_at, is_not(none()))


def test_delete_agent_removes_all_k8s_resources():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.RUNNING),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I delete a running agent"):
            response = client.delete(f"{_BASE}/{context.agent.id}", headers=_auth(context))

        with then("it returns 204 and all k8s resources were deleted"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            k8s.delete_deployment.assert_called_once()
            k8s.delete_service.assert_called_once()
            k8s.delete_pvc.assert_called_once()
            k8s.delete_secret.assert_called_once()
            k8s.delete_config_map.assert_called_once()


def test_delete_stopped_agent_still_removes_deployment():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(status=AgentStatus.STOPPED),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I delete a stopped agent"):
            response = client.delete(f"{_BASE}/{context.agent.id}", headers=_auth(context))

        with then("it returns 204 and delete_deployment was still called"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            k8s.delete_deployment.assert_called_once()


def test_deleted_agent_not_in_list():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I delete the agent then list agents"):
            client.delete(f"{_BASE}/{context.agent.id}", headers=_auth(context))
            response = client.get(_BASE, headers=_auth(context))

        with then("the list is empty"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["items"], equal_to([]))


def test_delete_agent_no_auth_returns_401():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I delete an agent without a token"):
            response = client.delete(f"{_BASE}/{context.agent.id}")

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_create_agent_calls_litellm_generate_key():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        litellm: MagicMock = context.injector.get(LiteLLMClient)

        with when("I create an agent"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("LiteLLM generate_key was called once"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            agent_id = response.json()["id"]
            # the test uses _VALID_CREATE where name is "Test Agent"
            litellm.generate_key.assert_called_once_with(agent_id, _VALID_CREATE["name"], str(context.organization.id))
            litellm.delete_key.assert_not_called()
            litellm.block_key.assert_not_called()


def test_create_agent_litellm_failure_returns_503():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        litellm: MagicMock = context.injector.get(LiteLLMClient)
        litellm.generate_key.side_effect = LiteLLMError("down")

        with when("I create an agent but LiteLLM is down"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("it returns 503 and no agent was saved"):
            assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))
            repository: AgentRepository = context.injector.get(AgentRepository)
            from api.domains.agents.models import AgentFilter
            from api.domains.rbac.policy import AuthorizationScope
            from api.infrastructure.shared.models import Pagination

            _, total = repository.find_all_active(
                AuthorizationScope(organization_id=context.organization.id),
                AgentFilter(),
                Pagination(page=1, size=10),
            )
            assert_that(total, equal_to(0))


def test_create_agent_releases_litellm_key_when_persistence_fails():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        repository: AgentRepository = context.injector.get(AgentRepository)
        litellm: MagicMock = context.injector.get(LiteLLMClient)

        with patch.object(
            repository,
            "create_with_creator_access",
            side_effect=HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="persistence failed"),
        ):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("the unowned key is deleted exactly once"):
            assert_that(response.status_code, equal_to(status.HTTP_500_INTERNAL_SERVER_ERROR))
            litellm.delete_key.assert_called_once_with(FAKE_LITELLM_KEY)
            litellm.block_key.assert_not_called()


def test_create_agent_blocks_key_when_litellm_deletion_reports_failure(caplog):
    with given(_GIVEN) as context:
        client: TestClient = context.client
        repository: AgentRepository = context.injector.get(AgentRepository)
        litellm: MagicMock = context.injector.get(LiteLLMClient)
        litellm.delete_key.return_value = False

        with patch.object(
            repository,
            "create_with_creator_access",
            side_effect=HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="persistence failed"),
        ):
            with caplog.at_level("WARNING"):
                response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("blocking is attempted and the plaintext key is absent from logs"):
            assert_that(response.status_code, equal_to(status.HTTP_500_INTERNAL_SERVER_ERROR))
            litellm.delete_key.assert_called_once_with(FAKE_LITELLM_KEY)
            litellm.block_key.assert_called_once_with(FAKE_LITELLM_KEY)
            assert_that(caplog.text, is_not(contains_string(FAKE_LITELLM_KEY)))


def test_create_agent_blocks_key_when_litellm_deletion_raises(caplog):
    with given(_GIVEN) as context:
        client: TestClient = context.client
        repository: AgentRepository = context.injector.get(AgentRepository)
        litellm: MagicMock = context.injector.get(LiteLLMClient)
        litellm.delete_key.side_effect = RuntimeError("remote delete failed")

        with patch.object(
            repository,
            "create_with_creator_access",
            side_effect=HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="persistence failed"),
        ):
            with caplog.at_level("WARNING"):
                response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("blocking is attempted after a deletion exception"):
            assert_that(response.status_code, equal_to(status.HTTP_500_INTERNAL_SERVER_ERROR))
            litellm.delete_key.assert_called_once_with(FAKE_LITELLM_KEY)
            litellm.block_key.assert_called_once_with(FAKE_LITELLM_KEY)
            assert_that(caplog.text, is_not(contains_string(FAKE_LITELLM_KEY)))


def test_create_agent_rolls_back_initial_resources_before_releasing_key():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        outbox: OutboxMessageRepository = context.injector.get(OutboxMessageRepository)
        litellm: MagicMock = context.injector.get(LiteLLMClient)

        with (
            patch.dict(
                "api.domains.agents.service.PROVIDER_VALIDATORS",
                {SecretProvider.JIRA: lambda _content: IntegrationValidationResult(valid=True)},
            ),
            patch.object(
                outbox,
                "stage",
                side_effect=[
                    None,
                    HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="secret persistence failed",
                    ),
                ],
            ),
        ):
            response = client.post(
                _BASE,
                json={
                    **_VALID_CREATE,
                    "secrets": [
                        {
                            "provider": "jira",
                            "content": {
                                "site_url": "https://acme.atlassian.net",
                                "email": "a@b.com",
                                "api_token": "jira-token",
                            },
                        }
                    ],
                },
                headers=_auth(context),
            )

        with then("the failed transaction leaves no Agent before key compensation"):
            assert_that(response.status_code, equal_to(status.HTTP_500_INTERNAL_SERVER_ERROR))
            litellm.delete_key.assert_called_once_with(FAKE_LITELLM_KEY)
            litellm.block_key.assert_not_called()
            assert_that(client.get(_BASE, headers=_auth(context)).json()["items"], equal_to([]))


def test_start_agent_injects_per_agent_key():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the secret is created with the per-agent LiteLLM key"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            call_kwargs = k8s.create_secret.call_args
            secret = call_kwargs.args[1]
            assert_that(secret.string_data["LITELLM_API_KEY"], equal_to(FAKE_LITELLM_KEY))


def test_delete_agent_calls_litellm_block_key():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        litellm: MagicMock = context.injector.get(LiteLLMClient)

        with when("I delete the agent"):
            response = client.delete(f"{_BASE}/{context.agent.id}", headers=_auth(context))

        with then("LiteLLM block_key was called once"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            litellm.block_key.assert_called_once_with(FAKE_LITELLM_KEY)
            litellm.delete_key.assert_not_called()


def test_delete_agent_litellm_failure_still_returns_204():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        litellm: MagicMock = context.injector.get(LiteLLMClient)
        litellm.block_key.side_effect = Exception("timeout")

        with when("I delete the agent but LiteLLM key revocation fails"):
            response = client.delete(f"{_BASE}/{context.agent.id}", headers=_auth(context))

        with then("it still returns 204"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            litellm.delete_key.assert_not_called()


def test_create_agent_with_model():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        payload = {**_VALID_CREATE, "model": "litellm/gpt-5"}

        with when("I create an agent with a model"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 201 with the model set"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["model"], equal_to("litellm/gpt-5"))


def test_create_agent_without_model_defaults_to_empty():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create an agent without specifying model"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("it returns 201 with model as empty string"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["model"], equal_to(""))


def test_patch_agent_updates_model():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I patch the agent model"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"model": "litellm/gpt-5"},
                headers=_auth(context),
            )

        with then("it returns 200 with the updated model"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["model"], equal_to("litellm/gpt-5"))


def test_start_agent_configmap_has_overlay():
    with given([*_GIVEN, there_is_an_agent(model="litellm/gpt-5")]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the ConfigMap contains the overlay with the correct model"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            import json

            config_map = k8s.create_config_map.call_args.args[1]
            overlay = json.loads(config_map.data["openclaw-config-overlay.json"])
            assert_that(
                overlay["agents"]["defaults"]["model"]["primary"],
                equal_to("litellm/gpt-5"),
            )
            assert_that(
                overlay["models"]["providers"]["litellm"]["baseUrl"],
                equal_to("http://localhost:8090"),
            )


def test_start_agent_configmap_has_init_script():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the ConfigMap contains the init script"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(config_map.data, has_key("init-openclaw.js"))


def test_start_agent_init_script_scrubs_legacy_provider_configuration():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start a headless agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the init script replaces channels and bindings wholesale"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            init_js = config_map.data["init-openclaw.js"]
            assert_that(init_js, contains_string("['channels']"))
            assert_that(init_js, contains_string("['bindings']"))
            assert_that(init_js, is_not(contains_string("PREINSTALLED_MSTEAMS")))


def test_start_agent_deployment_runs_init_script():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the Deployment command runs start.sh"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            deployment = k8s.create_deployment.call_args.args[1]
            command = deployment.spec.template.spec.containers[0].command
            assert_that(command, equal_to(["sh", "/app/config/start.sh"]))


def test_start_agent_uses_default_model_when_empty():
    with given([*_GIVEN, there_is_an_agent(model="")]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start an agent with no model set"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the overlay uses the default model from config"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            import json

            config_map = k8s.create_config_map.call_args.args[1]
            overlay = json.loads(config_map.data["openclaw-config-overlay.json"])
            assert_that(
                overlay["agents"]["defaults"]["model"]["primary"],
                equal_to("litellm/gpt-5-mini"),
            )


def test_get_agent_template_returns_template():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I get the agent's template"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/template/1",
                headers=_auth(context),
            )

        with then("it returns 200 with the full template"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["version"], equal_to(1))
            assert_that(body["soul_md"], equal_to("# Soul\n\nTest soul."))
            assert_that(body["identity_md"], equal_to("# Identity\n\nTest identity."))
            assert_that(body["organization_id"], equal_to(str(context.organization.id)))
            assert_that(body, has_key("created_at"))
            assert_that(body, has_key("updated_at"))


def test_get_template_missing_version_returns_404():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I request a non-existent template version"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/template/99",
                headers=_auth(context),
            )

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_get_template_for_deleted_agent_returns_404():
    with given([*_GIVEN, there_is_an_agent(deleted=True)]) as context:
        client: TestClient = context.client

        with when("I get the template of a deleted agent"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/template/1",
                headers=_auth(context),
            )

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_get_agent_template_no_auth_returns_401():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I get a template without a token"):
            response = client.get(f"{_BASE}/{context.agent.id}/template/1")

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_start_agent_configmap_and_headless_gateway_overlay_are_correct():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        import json

        config_map = k8s.create_config_map.call_args.args[1]
        overlay = json.loads(config_map.data["openclaw-config-overlay.json"])

        with then("the runtime has no provider transport configuration"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(overlay["channels"], equal_to({}))
            assert_that(overlay["bindings"], equal_to([]))

        with then("the ConfigMap contains the runtime-neutral communications adapter"):
            assert_that("communications-runtime-adapter.py" in config_map.data, equal_to(True))

        with then("tools, memory, and the core/active-memory plugins are enabled"):
            assert_that(overlay["tools"]["profile"], equal_to("full"))
            assert_that(overlay["memory"]["backend"], equal_to("builtin"))
            assert_that(overlay["plugins"]["slots"]["memory"], equal_to("memory-core"))
            assert_that(overlay["plugins"]["entries"]["memory-core"]["enabled"], equal_to(True))
            assert_that(
                overlay["plugins"]["entries"]["active-memory"]["enabled"],
                equal_to(True),
            )

        with then("the ConfigMap contains all 8 template markdown files"):
            for key in (
                "SOUL.md",
                "IDENTITY.md",
                "USER.md",
                "TOOLS.md",
                "AGENTS.md",
                "BOOT.md",
                "BOOTSTRAP.md",
                "HEARTBEAT.md",
            ):
                assert_that(config_map.data, has_key(key))

        with then("soul_md and identity_md in the ConfigMap match the template"):
            assert_that(config_map.data["SOUL.md"], equal_to("# Soul\n\nTest soul."))
            assert_that(config_map.data["IDENTITY.md"], equal_to("# Identity\n\nTest identity."))


def test_start_agent_renders_template_placeholders():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(
                name="Maya Bot",
                soul_md="# Soul of {{ agent_display_name }} ({{agent_name}})",
                tools_md="# Tools for {{ unknown_placeholder }}",
            ),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        config_map = k8s.create_config_map.call_args.args[1]

        with then("known placeholders are rendered from the agent"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                config_map.data["SOUL.md"],
                equal_to("# Soul of Maya Bot (maya-bot)"),
            )

        with then("unknown placeholders pass through"):
            tools = config_map.data["TOOLS.md"]
            assert_that(tools, contains_string("{{ unknown_placeholder }}"))

        with then("the stored template keeps its raw placeholders"):
            template_repository: TemplateRepository = context.injector.get(TemplateRepository)
            stored = template_repository.get_pinned_template(context.agent)
            assert stored is not None
            assert_that(
                stored.soul_md,
                equal_to("# Soul of {{ agent_display_name }} ({{agent_name}})"),
            )


def test_get_agent_healthz_returns_ok_when_healthy():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        agent_id = context.agent.id

        with (
            when("the pod /healthz returns healthy"),
            patch.object(
                context.injector.get(KubernetesClient),
                "get_pod_readiness",
                return_value=("ready", None),
            ),
            patch.object(
                context.injector.get(KubernetesClient),
                "fetch_agent_healthz",
                return_value={"status": "ok"},
            ),
        ):
            response = client.get(f"{_BASE}/{agent_id}/healthz", headers=_auth(context))

        with then("the API returns 200 with status ok"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["status"], equal_to("ok"))


def test_get_agent_healthz_returns_503_when_pod_unreachable():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        agent_id = context.agent.id

        with (
            when("the pod is unreachable"),
            patch.object(
                context.injector.get(KubernetesClient),
                "get_pod_readiness",
                return_value=("ready", None),
            ),
            patch.object(
                context.injector.get(KubernetesClient),
                "fetch_agent_healthz",
                side_effect=RuntimeError("connection refused"),
            ),
        ):
            response = client.get(f"{_BASE}/{agent_id}/healthz", headers=_auth(context))

        with then("the API returns 503"):
            assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))


def test_get_agent_healthz_returns_initializing_when_pod_not_ready():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        agent_id = context.agent.id

        with (
            when("the pod is running but not yet ready"),
            patch.object(
                context.injector.get(KubernetesClient),
                "get_pod_readiness",
                return_value=("initializing", None),
            ),
        ):
            response = client.get(f"{_BASE}/{agent_id}/healthz", headers=_auth(context))

        with then("the API returns 200 with status initializing"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["status"], equal_to("initializing"))


def test_get_agent_healthz_returns_crashed_when_pod_has_crashed():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        agent_id = context.agent.id

        with (
            when("the pod is in CrashLoopBackOff"),
            patch.object(
                context.injector.get(KubernetesClient),
                "get_pod_readiness",
                return_value=("crashed", "CrashLoopBackOff"),
            ),
        ):
            response = client.get(f"{_BASE}/{agent_id}/healthz", headers=_auth(context))

        with then("the API returns 200 with status crashed"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["status"], equal_to("crashed"))


def test_get_agent_healthz_returns_409_when_agent_not_running():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        client: TestClient = context.client
        agent_id = context.agent.id

        with when("the agent is stopped"):
            response = client.get(f"{_BASE}/{agent_id}/healthz", headers=_auth(context))

        with then("the API returns 409"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_create_hermes_agent_returns_201_stopped_without_a_bundled_platform():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a headless Hermes agent"):
            response = client.post(_BASE, json=_VALID_CREATE_HERMES, headers=_auth(context))

        with then("it returns 201 with agent_type hermes and status stopped"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["agent_type"], equal_to("hermes"))
            assert_that(body, is_not(has_key("platform")))
            assert_that(body["status"], equal_to(AgentStatus.STOPPED.value))


def test_create_agent_defaults_to_openclaw_type():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a Slack agent without specifying agent_type"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("agent_type defaults to openclaw"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["agent_type"], equal_to("openclaw"))


def test_start_hermes_agent_uses_hermes_image_and_config():
    with given(
        [
            *_GIVEN_WITH_HERMES_IMAGE,
            there_is_an_agent(agent_type=AgentType.HERMES),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start a Hermes agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("it returns 200 with status RUNNING"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["status"], equal_to(AgentStatus.RUNNING.value))
        with then("the deployment uses the Hermes image"):
            deployment = k8s.create_deployment.call_args.args[1]
            assert_that(
                deployment.spec.template.spec.containers[0].image,
                equal_to("nousresearch/hermes-agent:v1.0"),
            )
        with then("all k8s resources were created"):
            k8s.create_config_map.assert_called_once()
            k8s.create_secret.assert_called_once()
            k8s.create_pvc.assert_called_once()
            k8s.create_service.assert_called_once()
            k8s.create_deployment.assert_called_once()


def test_start_hermes_agent_configmap_has_hermes_config():
    import yaml as _yaml

    with given([*_GIVEN_WITH_HERMES_IMAGE, there_is_an_agent(agent_type=AgentType.HERMES)]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start a Hermes agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the ConfigMap contains hermes-config.yaml with correct model"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(config_map.data, has_key("hermes-config.yaml"))
            cfg = _yaml.safe_load(config_map.data["hermes-config.yaml"])
            assert_that(cfg["model"]["base_url"], equal_to("http://localhost:8090"))
            assert_that(cfg["display"]["platforms"], equal_to({}))
            assert_that(cfg["plugins"]["enabled"], equal_to(["telemetry-push"]))
            assert_that(cfg, is_not(has_key("slack")))

        with then("the ConfigMap has the headless runtime adapter"):
            assert_that(config_map.data, has_key("start.sh"))
            assert_that(config_map.data, has_key("healthz-server.py"))
            assert_that(config_map.data, has_key("communications-runtime-adapter.py"))
            assert_that(
                any("allowlist" in key or "deny-dms" in key for key in config_map.data),
                equal_to(False),
            )

        with then("SOUL.md has the bootloader footer appended"):
            soul = config_map.data["SOUL.md"]
            assert_that(soul, contains_string("# Soul\n\nTest soul."))
            assert_that(soul, contains_string("/workspace/IDENTITY.md"))

        with then("BOOTSTRAP.md is absent from the ConfigMap"):
            assert_that(config_map.data, is_not(has_key("BOOTSTRAP.md")))


def test_start_hermes_agent_deployment_has_workspace_volume():
    with given([*_GIVEN_WITH_HERMES_IMAGE, there_is_an_agent(agent_type=AgentType.HERMES)]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start a Hermes agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the deployment mounts /opt/data and /workspace"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            deployment = k8s.create_deployment.call_args.args[1]
            mounts = {m.mount_path: m for m in deployment.spec.template.spec.containers[0].volume_mounts}
            assert_that("/opt/data" in mounts, equal_to(True))
            assert_that("/workspace" in mounts, equal_to(True))

        with then("the workspace persists on the agent PVC, not an emptyDir"):
            # AF-215: /workspace is a subPath of the per-agent PVC so files the
            # agent writes to its cwd survive restarts.
            assert_that(mounts["/workspace"].name, equal_to("data"))
            assert_that(mounts["/workspace"].sub_path, equal_to("workspace"))
            volumes = deployment.spec.template.spec.volumes
            empty_dirs = [v for v in volumes if v.empty_dir is not None]
            assert_that(len(empty_dirs), equal_to(0))


def test_existing_agent_rows_backfill_to_openclaw():
    with given([*_GIVEN, there_is_an_agent(name="Legacy Agent")]) as context:
        repository: AgentRepository = context.injector.get(AgentRepository)

        with when("I read an agent created without an explicit agent_type"):
            agent = repository.get_by_id(context.agent.id)

        with then("agent_type is openclaw (server_default applied)"):
            assert agent is not None
            assert_that(agent.agent_type, equal_to(AgentType.OPENCLAW))


# ---------------------------------------------------------------------------
# Slack token validation — unhappy paths
# ---------------------------------------------------------------------------


def test_create_agent_with_valid_skill_assigns_it():
    with given([*_GIVEN, there_is_a_skill(name="My Skill")]) as context:
        client: TestClient = context.client
        payload = {**_VALID_CREATE, "skill_ids": [str(context.skill.id)]}

        with when("I create an agent with a valid skill"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 201, the skill is persisted and present in the response"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            repository: AgentRepository = context.injector.get(AgentRepository)
            from uuid import UUID

            agent_skills = repository.get_skills_for_agent(UUID(body["id"]))
            assert_that(len(agent_skills), equal_to(1))
            assert_that(agent_skills[0].skill_id, equal_to(context.skill.id))
            assert_that(len(body["skills"]), equal_to(1))
            assert_that(body["skills"][0]["id"], equal_to(str(context.skill.id)))
            assert_that(body["skills"][0]["name"], equal_to("My Skill"))


def _publish_skill_version(client: TestClient, context, content: str) -> None:
    """Draft -> update -> publish a new skill version through the public API."""
    skill_base = f"/api/v1/organizations/{context.organization.id}/skills/{context.skill.id}"
    client.post(f"{skill_base}/draft", headers=_auth(context))
    client.patch(
        f"{skill_base}/draft",
        json={"files": [{"path": "SKILL.md", "content": content}]},
        headers=_auth(context),
    )
    client.post(f"{skill_base}/draft/publish", headers=_auth(context))


def test_create_agent_pins_skill_to_latest_by_default():
    with given([*_GIVEN, there_is_a_skill(name="My Skill")]) as context:
        client: TestClient = context.client
        payload = {**_VALID_CREATE, "skill_ids": [str(context.skill.id)]}

        with when("I create an agent with a skill and no explicit version"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("the skill is pinned to its latest version and the read exposes it"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["skills"][0]["version"], equal_to(1))
            repository: AgentRepository = context.injector.get(AgentRepository)
            from uuid import UUID

            agent_skills = repository.get_skills_for_agent(UUID(body["id"]))
            assert_that(agent_skills[0].pinned_version, equal_to(1))


def test_create_agent_pins_skill_to_explicit_version():
    with given([*_GIVEN, there_is_a_skill(name="My Skill")]) as context:
        client: TestClient = context.client
        _publish_skill_version(client, context, "# v2")

        with when("I create an agent pinning the skill to version 1"):
            payload = {
                **_VALID_CREATE,
                "skill_ids": [str(context.skill.id)],
                "skill_versions": [{"skill_id": str(context.skill.id), "version": 1}],
            }
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("the skill is pinned to version 1 even though v2 is latest"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["skills"][0]["version"], equal_to(1))


def test_create_agent_with_invalid_skill_version_returns_404_and_leaves_no_partial_state():
    with given([*_GIVEN, there_is_a_skill(name="My Skill")]) as context:
        client: TestClient = context.client
        litellm: MagicMock = context.injector.get(LiteLLMClient)
        payload = {
            **_VALID_CREATE,
            "skill_ids": [str(context.skill.id)],
            "skill_versions": [{"skill_id": str(context.skill.id), "version": 99}],
        }

        with when("I create an agent pinning a version that was never published"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 404 and no agent is persisted"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            litellm.generate_key.assert_not_called()
            agents = client.get(_BASE, headers=_auth(context)).json()["items"]
            assert_that(len(agents), equal_to(0))


def test_create_agent_with_skill_pin_for_unassigned_skill_returns_400():
    with given([*_GIVEN, there_is_a_skill(name="My Skill")]) as context:
        client: TestClient = context.client
        payload = {
            **_VALID_CREATE,
            "skill_ids": [],
            "skill_versions": [{"skill_id": str(context.skill.id), "version": 1}],
        }

        with when("I create an agent pinning a skill it doesn't assign"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_update_agent_rejects_a_skill_that_is_added_and_removed_together():
    with given([*_GIVEN, there_is_an_agent(), there_is_a_skill(name="Contradictory Skill")]) as context:
        response = context.client.patch(
            f"{_BASE}/{context.agent.id}",
            json={
                "skill_ids": [str(context.skill.id)],
                "removed_skill_ids": [str(context.skill.id)],
            },
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_update_agent_re_pins_existing_skill_to_newer_version():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(name="My Skill"),
            skill_is_assigned_to_agent(),
        ]
    ) as context:
        client: TestClient = context.client
        _publish_skill_version(client, context, "# v2")

        with when("I re-pin the skill to version 2"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"skill_versions": [{"skill_id": str(context.skill.id), "version": 2}]},
                headers=_auth(context),
            )

        with then("the agent's read reflects the new pin"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["skills"][0]["version"], equal_to(2))


def test_update_agent_with_invalid_skill_pin_leaves_config_intact():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(name="My Skill"),
            skill_is_assigned_to_agent(),
        ]
    ) as context:
        client: TestClient = context.client
        original_name = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()["name"]

        with when("I update the agent name and pin a nonexistent version"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={
                    "name": "Renamed Agent",
                    "skill_versions": [{"skill_id": str(context.skill.id), "version": 99}],
                },
                headers=_auth(context),
            )

        with then("it returns 404 and the name change was not applied"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            current_name = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()["name"]
            assert_that(current_name, equal_to(original_name))


def test_create_agent_with_skill_from_other_org_returns_404():
    with given([*_GIVEN, there_is_a_skill_for_another_org()]) as context:
        client: TestClient = context.client
        payload = {**_VALID_CREATE, "skill_ids": [str(context.other_org_skill.id)]}

        with when("I create an agent using a skill that belongs to another org"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_create_agent_skill_pin_from_other_org_does_not_reveal_version_existence():
    with given([*_GIVEN, there_is_a_skill_for_another_org()]) as context:
        client: TestClient = context.client
        payload = {
            **_VALID_CREATE,
            "skill_ids": [str(context.other_org_skill.id)],
            "skill_versions": [{"skill_id": str(context.other_org_skill.id), "version": 99}],
        }

        response = client.post(_BASE, json=payload, headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
        assert_that(response.json()["detail"], contains_string("Skill"))
        assert_that(response.json()["detail"], is_not(contains_string("Version")))


def test_create_agent_with_unknown_skill_id_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        from uuid import uuid4

        payload = {**_VALID_CREATE, "skill_ids": [str(uuid4())]}

        with when("I create an agent with a non-existent skill"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_create_agent_skill_missing_provider_returns_400():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(
                name="GitHub Skill",
                required_providers=[SecretProvider.GITHUB],
            ),
        ]
    ) as context:
        client: TestClient = context.client
        litellm: MagicMock = context.injector.get(LiteLLMClient)
        payload = {**_VALID_CREATE, "skill_ids": [str(context.skill.id)]}

        with when("I create an agent without providing the required GitHub secret"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 400 naming the skill and the missing provider"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("GitHub Skill"))
            assert_that(response.json()["detail"], contains_string("github"))
            litellm.generate_key.assert_not_called()


def test_create_agent_rejects_live_invalid_secret_before_persistence():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        litellm: MagicMock = context.injector.get(LiteLLMClient)
        invalid = IntegrationValidationResult(valid=False, error="Token is invalid or expired")
        seen_tokens: list[str] = []

        def reject_tampered_token(content) -> IntegrationValidationResult:
            seen_tokens.append(content.token)
            return invalid

        payload = {
            **_VALID_CREATE,
            "secrets": [
                {
                    "provider": "github",
                    "content": {
                        "token": "tampered-token",
                        "owner": "my-org",
                        "org": "my-org",
                    },
                }
            ],
        }

        with when("I create an agent with a syntactically valid but invalid credential"):
            with patch.dict(
                "api.domains.agents.service.PROVIDER_VALIDATORS",
                {SecretProvider.GITHUB: reject_tampered_token},
            ):
                response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("the final payload is live-validated and nothing is persisted"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], equal_to("Token is invalid or expired"))
            assert_that(seen_tokens, equal_to(["tampered-token"]))
            litellm.generate_key.assert_not_called()
            assert_that(client.get(_BASE, headers=_auth(context)).json()["items"], equal_to([]))


def test_create_agent_skill_with_covered_provider_assigns_skill():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(
                name="GitHub Skill",
                required_providers=[SecretProvider.GITHUB],
            ),
        ]
    ) as context:
        client: TestClient = context.client
        payload = {
            **_VALID_CREATE,
            "skill_ids": [str(context.skill.id)],
            "secrets": [
                {
                    "provider": "github",
                    "content": {
                        "token": "ghp_token",
                        "owner": "my-org",
                        "repo": "my-repo",
                        "org": "my-org",
                    },
                }
            ],
        }

        with when("I create an agent with the required GitHub secret"):
            with patch.dict(
                "api.domains.agents.service.PROVIDER_VALIDATORS",
                {SecretProvider.GITHUB: lambda _content: IntegrationValidationResult(valid=True)},
            ):
                response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 201 and the skill is assigned"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            repository: AgentRepository = context.injector.get(AgentRepository)
            from uuid import UUID

            agent_skills = repository.get_skills_for_agent(UUID(response.json()["id"]))
            assert_that(len(agent_skills), equal_to(1))


def test_create_agent_duplicate_skill_ids_assigns_skill_once():
    with given([*_GIVEN, there_is_a_skill(name="Dedup Skill")]) as context:
        client: TestClient = context.client
        skill_id = str(context.skill.id)
        payload = {**_VALID_CREATE, "skill_ids": [skill_id, skill_id]}

        with when("I create an agent with the same skill_id twice"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 201 and the skill is assigned only once"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            repository: AgentRepository = context.injector.get(AgentRepository)
            from uuid import UUID

            agent_skills = repository.get_skills_for_agent(UUID(response.json()["id"]))
            assert_that(len(agent_skills), equal_to(1))


# --- aai-cli Slack secret mirrors the gateway bot token ---


def test_patch_agent_adds_skill():
    with given([*_GIVEN, there_is_an_agent(), there_is_a_skill(name="New Skill")]) as context:
        client: TestClient = context.client

        with when("I add a skill via PATCH"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"skill_ids": [str(context.skill.id)]},
                headers=_auth(context),
            )

        with then("it returns 200 and the skill is assigned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            repository: AgentRepository = context.injector.get(AgentRepository)
            from uuid import UUID

            agent_skills = repository.get_skills_for_agent(UUID(body["id"]))
            assert_that(len(agent_skills), equal_to(1))
            assert_that(agent_skills[0].skill_id, equal_to(context.skill.id))
            assert_that(len(body["skills"]), equal_to(1))
            assert_that(body["skills"][0]["id"], equal_to(str(context.skill.id)))


def test_patch_agent_removes_skill():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(name="Removable Skill"),
            skill_is_assigned_to_agent(),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I remove the skill via PATCH"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"removed_skill_ids": [str(context.skill.id)]},
                headers=_auth(context),
            )

        with then("it returns 200 and the skill is no longer assigned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            repository: AgentRepository = context.injector.get(AgentRepository)
            from uuid import UUID

            agent_skills = repository.get_skills_for_agent(UUID(body["id"]))
            assert_that(len(agent_skills), equal_to(0))
            assert_that(len(body["skills"]), equal_to(0))


def test_patch_agent_add_skill_from_other_org_returns_404():
    with given([*_GIVEN, there_is_an_agent(), there_is_a_skill_for_another_org()]) as context:
        client: TestClient = context.client

        with when("I add a skill from another org via PATCH"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"skill_ids": [str(context.other_org_skill.id)]},
                headers=_auth(context),
            )

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_patch_agent_add_unknown_skill_returns_404():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        from uuid import uuid4

        with when("I add a non-existent skill via PATCH"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"skill_ids": [str(uuid4())]},
                headers=_auth(context),
            )

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_patch_agent_add_skill_missing_provider_returns_400():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(
                name="GitHub Skill",
                required_providers=[SecretProvider.GITHUB],
            ),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I add a skill that requires GitHub without providing the secret"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"skill_ids": [str(context.skill.id)]},
                headers=_auth(context),
            )

        with then("it returns 400 naming the skill and the missing provider"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("GitHub Skill"))
            assert_that(response.json()["detail"], contains_string("github"))


def test_start_agent_with_skill_includes_skills_json_in_configmap():
    import json as _json

    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(name="Mounted Skill"),
            skill_is_assigned_to_agent(),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start an agent that has an assigned skill"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the ConfigMap contains skills.json with the skill's files"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(config_map.data, has_key("skills.json"))
            entries = _json.loads(config_map.data["skills.json"])
            assert_that(len(entries), equal_to(1))
            # Files are stored relative to the skill root; root_dir is applied at mount
            # time, so the workspace path carries the skill's own directory.
            assert_that(entries[0]["path"], equal_to("mounted-skill/SKILL.md"))


def test_start_agent_without_skills_has_no_skills_json_in_configmap():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start an agent with no assigned skills"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the ConfigMap does not contain skills.json"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(config_map.data, is_not(has_key("skills.json")))


def test_start_agent_with_skill_pointer_injects_pointer_into_tools_md():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(name="Pointed Skill"),
            skill_is_assigned_to_agent(),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the ConfigMap TOOLS.md contains the derived skill pointer"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            # Custom skills store no pointer: it is derived from the skill's name and
            # entry path, so a rename can never leave a stale pointer behind.
            assert_that(
                config_map.data["TOOLS.md"],
                contains_string("For Pointed Skill: See ./skills/pointed-skill/SKILL.md"),
            )


def test_start_agent_mounts_pinned_skill_version():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(name="Pinned Skill"),
            skill_is_assigned_to_agent(),
        ]
    ) as context:
        client: TestClient = context.client
        # Agent is pinned to v1 (assigned before v2 existed); publish v2 so a
        # newer version exists that the pin must ignore.
        _publish_skill_version(client, context, "# v2 content")
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start the agent while a newer skill version exists"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the mounted skills.json carries the pinned v1 content, not v2"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(config_map.data["skills.json"], contains_string("# Pinned Skill"))
            assert_that(config_map.data["skills.json"], is_not(contains_string("# v2 content")))


# --- aai-cli skills auto-attach from configured providers ---

_JIRA_POINTER = "\nFor Jira, use the aai-cli tool. See ./skills/jira/SKILL.md\n"


def test_start_agent_auto_attaches_aai_cli_skill_for_configured_provider():
    import json as _json

    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(
                name="Jira",
                required_providers=[SecretProvider.JIRA],
                global_skill=True,
                tools_pointer=_JIRA_POINTER,
            ),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("a jira secret is configured but the skill is not explicitly assigned"):
            client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the aai-cli Jira skill is mounted and its pointer injected"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(config_map.data, has_key("skills.json"))
            entries = _json.loads(config_map.data["skills.json"])
            assert_that(len(entries), equal_to(1))
            # Built-ins use the same isolated <slug>/SKILL.md mount contract as
            # organization and Agent-owned Skills.
            assert_that(entries[0]["path"], equal_to("jira/SKILL.md"))
            assert_that(config_map.data["TOOLS.md"], contains_string(_JIRA_POINTER))


def test_start_agent_does_not_auto_attach_credential_free_skill():
    """A skill with no required providers (Excel works on local files) must stay opt-in.

    Auto-mount keys off provider coverage, and an empty requirement list is trivially
    satisfied — so without an explicit guard every agent would silently get this skill.
    """
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(
                name="Excel",
                required_providers=[],
                global_skill=True,
                tools_pointer="\nFor Excel (.xlsx) files, use the aai-cli tool.\n",
            ),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("a jira secret is configured and the excel skill is not assigned"):
            client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the excel skill is not mounted"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that("For Excel" in config_map.data.get("TOOLS.md", ""), equal_to(False))


def test_start_agent_does_not_auto_attach_skill_for_unconfigured_provider():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(
                name="GitHub",
                required_providers=[SecretProvider.GITHUB],
                global_skill=True,
                tools_pointer="\nFor GitHub, use the aai-cli tool.\n",
            ),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("a jira secret is configured but no github secret"):
            client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the GitHub skill is not mounted (its provider is not configured)"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(config_map.data, is_not(has_key("skills.json")))
            assert_that(
                config_map.data["TOOLS.md"],
                is_not(contains_string("For GitHub, use the aai-cli tool")),
            )


def test_start_agent_auto_attach_does_not_duplicate_explicitly_assigned_skill():
    import json as _json

    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(
                name="Jira",
                required_providers=[SecretProvider.JIRA],
                global_skill=True,
                tools_pointer=_JIRA_POINTER,
            ),
            skill_is_assigned_to_agent(),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("the jira skill is both explicitly assigned and provider-configured"):
            client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the skill is mounted exactly once and the pointer appears once"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            entries = _json.loads(config_map.data["skills.json"])
            assert_that(len(entries), equal_to(1))
            assert_that(config_map.data["TOOLS.md"].count(_JIRA_POINTER), equal_to(1))


def test_start_agent_injects_profile_mapping_into_agents_md_openclaw():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("a jira secret is configured and the OpenClaw agent starts"):
            client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("AGENTS.md carries the --profile mapping and no-fallback policy"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            agents_md = config_map.data["AGENTS.md"]
            assert_that(agents_md, contains_string("--profile jira-work"))
            assert_that(agents_md, contains_string("./skills/aai-<integration>/SKILL.md"))


def test_start_agent_injects_profile_mapping_into_agents_md_hermes():
    with given([*_GIVEN_WITH_HERMES_IMAGE, there_is_an_agent(agent_type=AgentType.HERMES)]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("a jira secret is configured and the Hermes agent starts"):
            client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "jira", "content": _JIRA_CONTENT}]},
                headers=_auth(context),
            )
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("AGENTS.md carries the --profile mapping and no-fallback policy"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            agents_md = config_map.data["AGENTS.md"]
            assert_that(agents_md, contains_string("--profile jira-work"))
            assert_that(agents_md, contains_string("./skills/aai-<integration>/SKILL.md"))


def test_start_agent_injects_chat_commands_policy_into_agents_md_openclaw():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("the OpenClaw agent starts"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("AGENTS.md tells the agent not to advertise chat commands"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            agents_md = config_map.data["AGENTS.md"]
            assert_that(agents_md, contains_string("## Chat Commands"))
            assert_that(agents_md, contains_string("/help"))


def test_start_agent_injects_chat_commands_policy_into_agents_md_hermes():
    with given([*_GIVEN_WITH_HERMES_IMAGE, there_is_an_agent(agent_type=AgentType.HERMES)]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("the Hermes agent starts"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("AGENTS.md tells the agent not to advertise chat commands"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            agents_md = config_map.data["AGENTS.md"]
            assert_that(agents_md, contains_string("## Chat Commands"))
            assert_that(agents_md, contains_string("/help"))


def test_start_agent_injects_role_scope_policy_into_agents_md_openclaw():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("the OpenClaw agent starts"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("AGENTS.md tells the agent to stay inside its defined role"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            agents_md = config_map.data["AGENTS.md"]
            assert_that(agents_md, contains_string("## Role Scope"))
            assert_that(agents_md, contains_string("out of scope"))


def test_start_agent_injects_role_scope_policy_into_agents_md_hermes():
    with given([*_GIVEN_WITH_HERMES_IMAGE, there_is_an_agent(agent_type=AgentType.HERMES)]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("the Hermes agent starts"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("AGENTS.md tells the agent to stay inside its defined role"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            agents_md = config_map.data["AGENTS.md"]
            assert_that(agents_md, contains_string("## Role Scope"))
            assert_that(agents_md, contains_string("out of scope"))


def test_start_agent_no_integrations_omits_integrations_block():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("the agent starts with no configured secrets"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("AGENTS.md has no integrations block appended"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(
                config_map.data["AGENTS.md"],
                is_not(contains_string("--profile")),
            )


# --- template required skills ---


def test_create_agent_with_required_skill_marks_it_required():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira"),
            there_is_a_template_skill(),
        ]
    ) as context:
        client: TestClient = context.client
        skill_id = str(context.skill.id)
        payload = {**_VALID_CREATE, "skill_ids": [skill_id]}

        with when("I create an agent including the required skill in skill_ids"):
            response = client.post(_BASE, json=payload, headers=_auth(context))

        with then("it returns 201 and the skill is marked required=true"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            skills = response.json()["skills"]
            assert_that(len(skills), equal_to(1))
            assert_that(skills[0]["id"], equal_to(skill_id))
            assert_that(skills[0]["required"], equal_to(True))


def test_create_agent_rejects_a_required_skill_pinned_to_a_different_version():
    with given([*_GIVEN, there_is_a_skill(name="Jira"), there_is_a_template_skill()]) as context:
        from api.domains.skills.repository import SkillRepository

        context.injector.get(SkillRepository).publish_version(context.skill.id, [("SKILL.md", "# Jira v2")])
        skill_id = str(context.skill.id)

        with when("I assign version 2 when the Template requires version 1"):
            response = context.client.post(
                _BASE,
                json={
                    **_VALID_CREATE,
                    "skill_ids": [skill_id],
                    "skill_versions": [{"skill_id": skill_id, "version": 2}],
                },
                headers=_auth(context),
            )

        with then("the Agent creation is rejected rather than treating the lineage as sufficient"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("must be pinned to version 1"))


def test_create_agent_missing_required_skill_returns_400():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira"),
            there_is_a_template_skill(),
        ]
    ) as context:
        client: TestClient = context.client
        litellm: MagicMock = context.injector.get(LiteLLMClient)

        with when("I create an agent without including the required skill"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            litellm.generate_key.assert_not_called()


def test_update_agent_cannot_remove_required_skill_returns_409():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira"),
            there_is_a_template_skill(),
        ]
    ) as context:
        client: TestClient = context.client
        skill_id = str(context.skill.id)

        with when("I create an agent with the required skill"):
            agent = client.post(
                _BASE,
                json={**_VALID_CREATE, "skill_ids": [skill_id]},
                headers=_auth(context),
            ).json()

        with when("I try to remove the required skill via PATCH"):
            response = client.patch(
                f"{_BASE}/{agent['id']}",
                json={"removed_skill_ids": [skill_id]},
                headers=_auth(context),
            )

        with then("it returns 409"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_update_agent_repin_missing_required_skill_returns_400():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira"),
            there_is_a_template(template_key="with-skill", name="With Skill"),
            there_is_a_template_skill(),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I create an agent using a template with no required skills"):
            agent = client.post(
                _BASE,
                json={**_VALID_CREATE, "template_key": "test-template"},
                headers=_auth(context),
            ).json()

        with when("I repin to a template that requires a skill I haven't provided"):
            response = client.patch(
                f"{_BASE}/{agent['id']}",
                json={"template_key": "with-skill", "template_version": 1},
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_update_agent_repin_with_required_skill_marks_it_required():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira"),
            there_is_a_template(template_key="with-skill", name="With Skill"),
            there_is_a_template_skill(),
        ]
    ) as context:
        client: TestClient = context.client
        skill_id = str(context.skill.id)

        with when("I create an agent using a template with no required skills"):
            agent = client.post(
                _BASE,
                json={**_VALID_CREATE, "template_key": "test-template"},
                headers=_auth(context),
            ).json()

        with when("I repin providing the required skill in skill_ids"):
            response = client.patch(
                f"{_BASE}/{agent['id']}",
                json={
                    "template_key": "with-skill",
                    "template_version": 1,
                    "skill_ids": [skill_id],
                },
                headers=_auth(context),
            )

        with then("it returns 200 and the skill is marked required=true"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            skills = response.json()["skills"]
            jira = next(s for s in skills if s["id"] == skill_id)
            assert_that(jira["required"], equal_to(True))


def test_list_agents_marks_required_skills():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira"),
            there_is_a_template_skill(),
        ]
    ) as context:
        client: TestClient = context.client
        skill_id = str(context.skill.id)

        with when("I create an agent with the required skill"):
            client.post(
                _BASE,
                json={**_VALID_CREATE, "skill_ids": [skill_id]},
                headers=_auth(context),
            )

        with when("I list agents"):
            response = client.get(_BASE, headers=_auth(context))

        with then("the skill appears with required=true in the list response"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            agents = response.json()["items"]
            assert_that(len(agents), equal_to(1))
            jira = next(s for s in agents[0]["skills"] if s["id"] == skill_id)
            assert_that(jira["required"], equal_to(True))


# --- template required skill groups ("at least one of") ---


def _group_skill_ids(context) -> dict[str, str]:
    return {s.name: str(s.id) for s in context.template_skill_group["skills"]}


def test_create_agent_with_no_group_member_returns_400():
    with given(
        [
            *_GIVEN,
            there_is_a_template_skill_group(("GitHub", "Bitbucket")),
        ]
    ) as context:
        client: TestClient = context.client
        litellm: MagicMock = context.injector.get(LiteLLMClient)

        with when("I create an agent without any group member in skill_ids"):
            response = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            litellm.generate_key.assert_not_called()


def test_create_agent_with_one_group_member_succeeds_and_marks_it_required():
    with given(
        [
            *_GIVEN,
            there_is_a_template_skill_group(("GitHub", "Bitbucket")),
        ]
    ) as context:
        client: TestClient = context.client
        github_id = _group_skill_ids(context)["GitHub"]

        with when("I create an agent including one group member"):
            response = client.post(
                _BASE,
                json={**_VALID_CREATE, "skill_ids": [github_id]},
                headers=_auth(context),
            )

        with then("it returns 201 and that skill is marked required=true"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            skills = response.json()["skills"]
            github = next(s for s in skills if s["id"] == github_id)
            assert_that(github["required"], equal_to(True))


def test_create_agent_with_both_group_members_marks_neither_required():
    with given(
        [
            *_GIVEN,
            there_is_a_template_skill_group(("GitHub", "Bitbucket")),
        ]
    ) as context:
        client: TestClient = context.client
        ids = _group_skill_ids(context)

        with when("I create an agent including both group members"):
            response = client.post(
                _BASE,
                json={**_VALID_CREATE, "skill_ids": [ids["GitHub"], ids["Bitbucket"]]},
                headers=_auth(context),
            )

        with then("it returns 201 and neither is marked required, since either is removable"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            skills = response.json()["skills"]
            assert_that(all(not s["required"] for s in skills), equal_to(True))


def test_update_agent_can_remove_one_group_member_while_other_remains():
    with given(
        [
            *_GIVEN,
            there_is_a_template_skill_group(("GitHub", "Bitbucket")),
        ]
    ) as context:
        client: TestClient = context.client
        ids = _group_skill_ids(context)

        with when("I create an agent with both group members"):
            agent = client.post(
                _BASE,
                json={**_VALID_CREATE, "skill_ids": [ids["GitHub"], ids["Bitbucket"]]},
                headers=_auth(context),
            ).json()

        with when("I remove one member via PATCH"):
            response = client.patch(
                f"{_BASE}/{agent['id']}",
                json={"removed_skill_ids": [ids["GitHub"]]},
                headers=_auth(context),
            )

        with then("it returns 200 and the survivor becomes required=true"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            bitbucket = next(s for s in response.json()["skills"] if s["id"] == ids["Bitbucket"])
            assert_that(bitbucket["required"], equal_to(True))


def test_update_agent_cannot_remove_last_group_member():
    with given(
        [
            *_GIVEN,
            there_is_a_template_skill_group(("GitHub", "Bitbucket")),
        ]
    ) as context:
        client: TestClient = context.client
        ids = _group_skill_ids(context)

        with when("I create an agent with a single group member"):
            agent = client.post(
                _BASE,
                json={**_VALID_CREATE, "skill_ids": [ids["GitHub"]]},
                headers=_auth(context),
            ).json()

        with when("I try to remove that sole group member via PATCH"):
            response = client.patch(
                f"{_BASE}/{agent['id']}",
                json={"removed_skill_ids": [ids["GitHub"]]},
                headers=_auth(context),
            )

        with then("it returns 409"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_update_agent_can_swap_group_members_in_one_call():
    with given(
        [
            *_GIVEN,
            there_is_a_template_skill_group(("GitHub", "Bitbucket")),
        ]
    ) as context:
        client: TestClient = context.client
        ids = _group_skill_ids(context)

        with when("I create an agent with the GitHub member"):
            agent = client.post(
                _BASE,
                json={**_VALID_CREATE, "skill_ids": [ids["GitHub"]]},
                headers=_auth(context),
            ).json()

        with when("I swap GitHub for Bitbucket in the same PATCH"):
            response = client.patch(
                f"{_BASE}/{agent['id']}",
                json={"skill_ids": [ids["Bitbucket"]], "removed_skill_ids": [ids["GitHub"]]},
                headers=_auth(context),
            )

        with then("it returns 200 and Bitbucket is now required=true"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            bitbucket = next(s for s in response.json()["skills"] if s["id"] == ids["Bitbucket"])
            assert_that(bitbucket["required"], equal_to(True))


def test_update_agent_repin_to_grouped_template_without_member_returns_400():
    with given(
        [
            *_GIVEN,
            there_is_a_template(template_key="with-group", name="With Group"),
            there_is_a_template_skill_group(("GitHub", "Bitbucket")),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I create an agent using a template with no required skills"):
            agent = client.post(
                _BASE,
                json={**_VALID_CREATE, "template_key": "test-template"},
                headers=_auth(context),
            ).json()

        with when("I repin to the grouped template without a member"):
            response = client.patch(
                f"{_BASE}/{agent['id']}",
                json={"template_key": "with-group", "template_version": 1},
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_update_agent_repin_to_grouped_template_with_member_succeeds_and_marks_required():
    with given(
        [
            *_GIVEN,
            there_is_a_template(template_key="with-group", name="With Group"),
            there_is_a_template_skill_group(("GitHub", "Bitbucket")),
        ]
    ) as context:
        client: TestClient = context.client
        ids = _group_skill_ids(context)

        with when("I create an agent using a template with no required skills"):
            agent = client.post(
                _BASE,
                json={**_VALID_CREATE, "template_key": "test-template"},
                headers=_auth(context),
            ).json()

        with when("I repin providing a group member in skill_ids"):
            response = client.patch(
                f"{_BASE}/{agent['id']}",
                json={
                    "template_key": "with-group",
                    "template_version": 1,
                    "skill_ids": [ids["Bitbucket"]],
                },
                headers=_auth(context),
            )

        with then("it returns 200 and the provided member is marked required=true"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            bitbucket = next(s for s in response.json()["skills"] if s["id"] == ids["Bitbucket"])
            assert_that(bitbucket["required"], equal_to(True))


def test_list_agents_marks_sole_group_member_required():
    with given(
        [
            *_GIVEN,
            there_is_a_template_skill_group(("GitHub", "Bitbucket")),
        ]
    ) as context:
        client: TestClient = context.client
        github_id = _group_skill_ids(context)["GitHub"]

        with when("I create an agent with a single group member"):
            client.post(
                _BASE,
                json={**_VALID_CREATE, "skill_ids": [github_id]},
                headers=_auth(context),
            )

        with when("I list agents"):
            response = client.get(_BASE, headers=_auth(context))

        with then("the sole group member appears with required=true in the list response"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            agents = response.json()["items"]
            github = next(s for s in agents[0]["skills"] if s["id"] == github_id)
            assert_that(github["required"], equal_to(True))


def test_update_agent_grandfathered_without_group_member_can_still_be_updated():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        repository: TemplateRepository = context.injector.get(TemplateRepository)

        with when("I create an agent on a template with no required skills yet"):
            agent = client.post(_BASE, json=_VALID_CREATE, headers=_auth(context)).json()

        with when("the template is later given a GitHub-or-Bitbucket group (e.g. via reseed)"):
            there_is_a_template_skill_group(("GitHub", "Bitbucket"))(context)
            # there_is_a_template_skill_group attaches to context.template, which
            # is the same "test-template" row the agent above is pinned to.
            assert repository.get_org_required_skill_map(context.template.id)

        with when("I make an unrelated update (rename) without touching skills"):
            response = client.patch(
                f"{_BASE}/{agent['id']}",
                json={"name": "Renamed Agent"},
                headers=_auth(context),
            )

        with then("it succeeds — the agent is grandfathered in without a group member"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["name"], equal_to("Renamed Agent"))


_GIVEN_WITH_FIRECRAWL = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "API_EXTERNAL_URL": "https://api.test.com",
            "SKIP_SLACK_TOKEN_VALIDATION": "true",
            "AGENT_FIRECRAWL_BASE_URL": "http://firecrawl:3002",
            "AGENT_FIRECRAWL_API_KEY": "fc-platform-key",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_a_template(),
]

_GIVEN_HERMES_WITH_FIRECRAWL = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "API_EXTERNAL_URL": "https://api.test.com",
            "HERMES_IMAGE": "nousresearch/hermes-agent:v1.0",
            "AGENT_FIRECRAWL_BASE_URL": "http://firecrawl:3002",
            "AGENT_FIRECRAWL_API_KEY": "fc-platform-key",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_a_template(),
]


def test_start_openclaw_agent_with_platform_firecrawl():
    with given([*_GIVEN_WITH_FIRECRAWL, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start an OpenClaw agent with platform firecrawl configured"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the overlay has firecrawl plugin and the secret has the key"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            overlay = json.loads(config_map.data["openclaw-config-overlay.json"])
            assert_that("firecrawl" in overlay["plugins"]["allow"], equal_to(True))
            assert_that(overlay["plugins"]["entries"], has_key("firecrawl"))
            assert_that(overlay["tools"]["web"]["fetch"]["provider"], equal_to("firecrawl"))
            secret = k8s.create_secret.call_args.args[1]
            assert_that(secret.string_data["FIRECRAWL_API_KEY"], equal_to("fc-platform-key"))


def test_start_hermes_agent_with_platform_firecrawl():
    import yaml as _yaml

    with given([*_GIVEN_HERMES_WITH_FIRECRAWL, there_is_an_agent(agent_type=AgentType.HERMES)]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start a Hermes agent with platform firecrawl configured"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("hermes config has firecrawl and secret has the env vars"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            cfg = _yaml.safe_load(config_map.data["hermes-config.yaml"])
            assert_that(cfg["web"], equal_to({"backend": "firecrawl"}))
            assert_that(cfg["browser"], equal_to({"cloud_provider": "firecrawl"}))
            secret = k8s.create_secret.call_args.args[1]
            assert_that(secret.string_data["FIRECRAWL_API_KEY"], equal_to("fc-platform-key"))
            assert_that(
                secret.string_data["FIRECRAWL_API_URL"],
                equal_to("http://firecrawl:3002"),
            )


def test_start_agent_per_agent_firecrawl_overrides_platform():
    with given([*_GIVEN_WITH_FIRECRAWL, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I add a per-agent firecrawl secret and start"):
            client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"secrets": [{"provider": "firecrawl", "content": {"api_key": "fc-my-key"}}]},
                headers=_auth(context),
            )
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the per-agent key is used instead of the platform key"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            secret = k8s.create_secret.call_args.args[1]
            assert_that(secret.string_data["FIRECRAWL_API_KEY"], equal_to("fc-my-key"))


def test_start_agent_per_agent_firecrawl_overrides_base_url():
    with given([*_GIVEN_WITH_FIRECRAWL, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I add a per-agent firecrawl secret with base_url and start"):
            client.patch(
                f"{_BASE}/{context.agent.id}",
                json={
                    "secrets": [
                        {
                            "provider": "firecrawl",
                            "content": {
                                "api_key": "fc-cloud-key",
                                "base_url": "https://api.firecrawl.dev",
                            },
                        }
                    ]
                },
                headers=_auth(context),
            )
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("both the key and base URL are overridden"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            secret = k8s.create_secret.call_args.args[1]
            assert_that(secret.string_data["FIRECRAWL_API_KEY"], equal_to("fc-cloud-key"))
            config_map = k8s.create_config_map.call_args.args[1]
            overlay = json.loads(config_map.data["openclaw-config-overlay.json"])
            fc_cfg = overlay["plugins"]["entries"]["firecrawl"]["config"]
            assert_that(
                fc_cfg["webSearch"]["baseUrl"],
                equal_to("https://api.firecrawl.dev"),
            )


_GIVEN_WITHOUT_FIRECRAWL = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "API_EXTERNAL_URL": "https://api.test.com",
            "SKIP_SLACK_TOKEN_VALIDATION": "true",
            "AGENT_FIRECRAWL_BASE_URL": "",
            "AGENT_FIRECRAWL_API_KEY": "",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_a_template(),
]


def test_start_openclaw_agent_without_firecrawl():
    with given([*_GIVEN_WITHOUT_FIRECRAWL, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start an agent without any firecrawl env vars"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the overlay has no firecrawl and the secret has no firecrawl key"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            overlay = json.loads(config_map.data["openclaw-config-overlay.json"])
            assert "firecrawl" not in overlay["plugins"]["allow"]
            assert_that(overlay["plugins"]["entries"], is_not(has_key("firecrawl")))
            secret = k8s.create_secret.call_args.args[1]
            assert_that(secret.string_data, is_not(has_key("FIRECRAWL_API_KEY")))


def test_start_agent_secret_has_litellm_proxy_target():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start the agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the secret contains LITELLM_PROXY_TARGET pointing to the real LiteLLM URL"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            secret = k8s.create_secret.call_args.args[1]
            assert_that(secret.string_data["LITELLM_PROXY_TARGET"], equal_to("http://litellm:4000"))

        with then("the secret routes LLM traffic through the local proxy"):
            assert_that(secret.string_data["LITELLM_BASE_URL"], equal_to("http://localhost:8090"))


def test_start_hermes_agent_secret_has_litellm_proxy_target():
    with given(
        [
            *_GIVEN_WITH_HERMES_IMAGE,
            there_is_an_agent(agent_type=AgentType.HERMES),
        ]
    ) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start the Hermes agent"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the secret contains LITELLM_PROXY_TARGET pointing to the real LiteLLM URL"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            secret = k8s.create_secret.call_args.args[1]
            assert_that(secret.string_data["LITELLM_PROXY_TARGET"], equal_to("http://litellm:4000"))

        with then("the secret routes LLM traffic through the local proxy"):
            assert_that(secret.string_data["OPENAI_BASE_URL"], equal_to("http://localhost:8090"))
            assert_that(secret.string_data["OPENROUTER_BASE_URL"], equal_to("http://localhost:8090"))


def test_agent_configuration_override_draft_publish_and_select_preserves_lineage():
    with given([*_GIVEN, there_is_an_agent(name="Configurable Agent")]) as context:
        client: TestClient = context.client
        configuration_url = f"{_BASE}/{context.agent.id}/configuration"
        template_repository: TemplateRepository = context.injector.get(TemplateRepository)
        pinned_template = cast(
            AgentTemplate | PlatformTemplate,
            template_repository.get_pinned_template(context.agent),
        )
        assert pinned_template is not None

        with when("I read the Agent configuration"):
            initial = client.get(configuration_url, headers=_auth(context))

        with then("the active shared snapshot and source lineage are returned"):
            assert_that(initial.status_code, equal_to(status.HTTP_200_OK))
            initial_body = initial.json()
            assert_that(initial_body["active"]["pin_type"], equal_to("shared"))
            assert_that(initial_body["active"]["source_type"], equal_to("organization"))
            assert_that(initial_body["active"]["source_template_key"], equal_to(pinned_template.template_key))
            assert_that(initial_body["draft"], none())

        with when("I start an Override Draft"):
            draft_response = client.post(f"{configuration_url}/draft", headers=_auth(context))

        with then("the draft is a complete copy of the pinned snapshot"):
            assert_that(draft_response.status_code, equal_to(status.HTTP_201_CREATED))
            draft = draft_response.json()
            assert_that(draft["state"], equal_to("draft"))
            assert_that(draft["source_template_key"], equal_to(pinned_template.template_key))
            assert_that(draft["source_template_version"], equal_to(pinned_template.version))
            assert_that(draft["soul_md"], equal_to(pinned_template.soul_md))
            assert_that(draft["user_md"], equal_to(pinned_template.user_md))

        with when("I save a changed artifact"):
            update_response = client.patch(
                f"{configuration_url}/draft",
                json={
                    "expected_updated_at": draft["updated_at"],
                    "soul_md": "# Agent-specific soul",
                },
                headers=_auth(context),
            )

        with then("the draft keeps the source lineage and changed content"):
            assert_that(update_response.status_code, equal_to(status.HTTP_200_OK))
            updated_draft = update_response.json()
            assert_that(updated_draft["soul_md"], equal_to("# Agent-specific soul"))
            assert_that(updated_draft["source_template_key"], equal_to(pinned_template.template_key))

        with when("I publish the draft"):
            publish_response = client.post(
                f"{configuration_url}/draft/publish",
                json={"expected_updated_at": updated_draft["updated_at"]},
                headers=_auth(context),
            )

        with then("it creates immutable Override Version 1 without changing the active pin"):
            assert_that(publish_response.status_code, equal_to(status.HTTP_201_CREATED))
            published = publish_response.json()
            assert_that(published["version"], equal_to(1))
            assert_that(published["state"], equal_to("published"))
            assert_that(published["soul_md"], equal_to("# Agent-specific soul"))
            still_shared = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            assert_that(still_shared["template_pin_type"], equal_to("shared"))
            assert_that(still_shared["override_version"], none())

        with when("I select the published Override Version"):
            select_response = client.post(
                f"{configuration_url}/select",
                json={
                    "selection_type": "override",
                    "override_version": 1,
                    "expected_agent_updated_at": still_shared["updated_at"],
                },
                headers=_auth(context),
            )

        with then("the Agent points at the Override while the shared source remains available"):
            assert_that(select_response.status_code, equal_to(status.HTTP_200_OK))
            selected = select_response.json()
            assert_that(selected["template_pin_type"], equal_to("override"))
            assert_that(selected["override_version"], equal_to(1))
            after_select = client.get(configuration_url, headers=_auth(context)).json()
            assert_that(after_select["active"]["pin_type"], equal_to("override"))
            assert_that(after_select["active"]["state"], equal_to("active"))
            assert_that(after_select["active"]["soul_md"], equal_to("# Agent-specific soul"))
            assert_that(len(after_select["shared_versions"]), equal_to(1))
            assert_that(after_select["draft"], none())

        with when("I start another draft from the active Override"):
            second_draft = client.post(f"{configuration_url}/draft", headers=_auth(context))

        with then("the new draft clones the active Override and retains its original source lineage"):
            assert_that(second_draft.status_code, equal_to(status.HTTP_201_CREATED))
            second_body = second_draft.json()
            assert_that(second_body["soul_md"], equal_to("# Agent-specific soul"))
            assert_that(second_body["source_template_key"], equal_to(pinned_template.template_key))
            assert_that(second_body["source_template_version"], equal_to(pinned_template.version))


def test_agent_configuration_override_lifecycle_emits_domain_events():
    with given([*_GIVEN, there_is_an_agent(name="Configurable Agent")]) as context:
        client: TestClient = context.client
        configuration_url = f"{_BASE}/{context.agent.id}/configuration"
        outbox = context.injector.get(AgentOverrideRepository).outbox_repository

        with when("I start an Override Draft"):
            draft = client.post(f"{configuration_url}/draft", headers=_auth(context)).json()

        with then("a Draft Saved Domain Event is persisted with created=True"):
            draft_events = [
                message
                for message in _outbox_messages(context)
                if message.event_name == AGENT_TEMPLATE_OVERRIDE_DRAFT_SAVED
            ]
            assert_that(len(draft_events), equal_to(1))
            assert_that(draft_events[0].payload["agent_id"], equal_to(str(context.agent.id)))
            assert_that(draft_events[0].payload["draft_id"], equal_to(draft["id"]))
            assert_that(draft_events[0].payload["created"], equal_to(True))
            assert_that(
                draft_events[0].payload["actor_display"], equal_to(context.user.full_name or context.user.email)
            )
            deliveries = outbox.list_deliveries_for_event(draft_events[0].event_id)
            assert_that(len(deliveries), equal_to(1))

        with when("I save a changed artifact"):
            updated_draft = client.patch(
                f"{configuration_url}/draft",
                json={"expected_updated_at": draft["updated_at"], "soul_md": "# Agent-specific soul"},
                headers=_auth(context),
            ).json()

        with then("a second Draft Saved Domain Event is persisted with created=False"):
            draft_events = sorted(
                (
                    message
                    for message in _outbox_messages(context)
                    if message.event_name == AGENT_TEMPLATE_OVERRIDE_DRAFT_SAVED
                ),
                key=lambda message: message.occurred_at,
            )
            assert_that(len(draft_events), equal_to(2))
            assert_that(draft_events[1].payload["created"], equal_to(False))

        with when("I publish the draft"):
            published = client.post(
                f"{configuration_url}/draft/publish",
                json={"expected_updated_at": updated_draft["updated_at"]},
                headers=_auth(context),
            ).json()

        with then("an Override Published Domain Event is persisted"):
            published_events = [
                message
                for message in _outbox_messages(context)
                if message.event_name == AGENT_TEMPLATE_OVERRIDE_PUBLISHED
            ]
            assert_that(len(published_events), equal_to(1))
            assert_that(published_events[0].payload["agent_id"], equal_to(str(context.agent.id)))
            assert_that(published_events[0].payload["override_version_id"], equal_to(published["id"]))
            assert_that(published_events[0].payload["version"], equal_to(1))

        with when("I select the published Override Version"):
            agent_before_select = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            client.post(
                f"{configuration_url}/select",
                json={
                    "selection_type": "override",
                    "override_version": 1,
                    "expected_agent_updated_at": agent_before_select["updated_at"],
                },
                headers=_auth(context),
            )

        with then("an Override Selected Domain Event is persisted"):
            selected_events = [
                message
                for message in _outbox_messages(context)
                if message.event_name == AGENT_TEMPLATE_OVERRIDE_SELECTED
            ]
            assert_that(len(selected_events), equal_to(1))
            assert_that(selected_events[0].payload["agent_id"], equal_to(str(context.agent.id)))
            assert_that(selected_events[0].payload["selection_type"], equal_to("override"))
            assert_that(selected_events[0].payload["selected_id"], equal_to(published["id"]))
            assert_that(selected_events[0].payload["selected_version"], equal_to(1))
            assert_that(selected_events[0].payload["template_key"], none())


def test_agent_configuration_draft_rejects_stale_update():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        configuration_url = f"{_BASE}/{context.agent.id}/configuration"
        draft = client.post(f"{configuration_url}/draft", headers=_auth(context)).json()
        first_update = client.patch(
            f"{configuration_url}/draft",
            json={"expected_updated_at": draft["updated_at"], "description": "first writer"},
            headers=_auth(context),
        )
        assert_that(first_update.status_code, equal_to(status.HTTP_200_OK))

        stale = client.patch(
            f"{configuration_url}/draft",
            json={"expected_updated_at": draft["updated_at"], "description": "stale writer"},
            headers=_auth(context),
        )

    assert_that(stale.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_agent_configuration_override_isolated_per_agent():
    with given([*_GIVEN, there_is_an_agent(name="First Agent")]) as context:
        client: TestClient = context.client
        first_agent = context.agent
        there_is_an_agent(name="Second Agent")(context)
        second_agent = context.agent
        first_url = f"{_BASE}/{first_agent.id}/configuration"

        draft = client.post(f"{first_url}/draft", headers=_auth(context)).json()
        published_response = client.post(
            f"{first_url}/draft/publish",
            json={"expected_updated_at": draft["updated_at"]},
            headers=_auth(context),
        )
        published = published_response.json()
        first_read = client.get(f"{_BASE}/{first_agent.id}", headers=_auth(context)).json()
        selected = client.post(
            f"{first_url}/select",
            json={
                "selection_type": "override",
                "override_version": published["version"],
                "expected_agent_updated_at": first_read["updated_at"],
            },
            headers=_auth(context),
        )

        first_configuration = client.get(first_url, headers=_auth(context)).json()
        second_configuration = client.get(
            f"{_BASE}/{second_agent.id}/configuration",
            headers=_auth(context),
        ).json()

        assert_that(selected.status_code, equal_to(status.HTTP_200_OK))
        assert_that(first_configuration["active"]["pin_type"], equal_to("override"))
        assert_that(second_configuration["active"]["pin_type"], equal_to("shared"))
        assert_that(second_configuration["draft"], none())


def test_agent_configuration_draft_and_publish_are_safe_while_running():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        configuration_url = f"{_BASE}/{context.agent.id}/configuration"
        draft_response = client.post(
            f"{configuration_url}/draft",
            headers=_auth(context),
        )
        assert_that(draft_response.status_code, equal_to(status.HTTP_201_CREATED))
        draft = draft_response.json()

        publish_response = client.post(
            f"{configuration_url}/draft/publish",
            json={"expected_updated_at": draft["updated_at"]},
            headers=_auth(context),
        )

        assert_that(publish_response.status_code, equal_to(status.HTTP_201_CREATED))
        selection_response = client.post(
            f"{configuration_url}/select",
            json={
                "selection_type": "override",
                "override_version": 1,
                "expected_agent_updated_at": context.agent.updated_at.isoformat(),
            },
            headers=_auth(context),
        )
        assert_that(selection_response.status_code, equal_to(status.HTTP_409_CONFLICT))
        agent = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
        assert_that(agent["template_pin_type"], equal_to("shared"))


def test_agent_override_platform_source_update_repins_without_changing_draft():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        delegate = context.injector.get(PostgresRepositoryDelegate)
        source_v1 = PlatformTemplate(
            template_key="direct-platform-source",
            template_name="Direct Platform Source",
            version=1,
            description="platform v1",
            soul_md="platform soul v1",
            identity_md="platform identity v1",
            user_md="platform user v1",
            tools_md="platform tools v1",
            agents_md="platform agents v1",
            boot_md="platform boot v1",
            bootstrap_md="platform bootstrap v1",
            heartbeat_md="platform heartbeat v1",
        )
        delegate.save(source_v1)
        _pin_override_to_source(context, source_v1, AgentTemplateOverrideSourceType.PLATFORM)
        source_v2 = PlatformTemplate(
            template_key=source_v1.template_key,
            template_name=source_v1.template_name,
            version=2,
            description="platform v2",
            soul_md="platform soul v2",
            identity_md=source_v1.identity_md,
            user_md=source_v1.user_md,
            tools_md=source_v1.tools_md,
            agents_md=source_v1.agents_md,
            boot_md=source_v1.boot_md,
            bootstrap_md=source_v1.bootstrap_md,
            heartbeat_md=source_v1.heartbeat_md,
        )
        delegate.save(source_v2)
        configuration_url = f"{_BASE}/{context.agent.id}/configuration"

        configuration = client.get(configuration_url, headers=_auth(context)).json()
        assert_that(configuration["source_update"]["source_type"], equal_to("platform"))
        assert_that(configuration["source_update"]["source_template_version"], equal_to(2))
        assert_that(configuration["source_update"]["soul_md"], equal_to("platform soul v2"))

        draft = client.post(f"{configuration_url}/draft", headers=_auth(context)).json()
        local_edit = client.patch(
            f"{configuration_url}/draft",
            json={"expected_updated_at": draft["updated_at"], "soul_md": "local change"},
            headers=_auth(context),
        ).json()
        agent_before_select = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
        selected = client.post(
            f"{configuration_url}/select",
            json={
                "selection_type": "platform",
                "template_key": source_v1.template_key,
                "template_version": 2,
                "expected_agent_updated_at": agent_before_select["updated_at"],
            },
            headers=_auth(context),
        )
        assert_that(selected.status_code, equal_to(status.HTTP_200_OK))
        assert_that(selected.json()["template_pin_type"], equal_to("shared"))
        assert_that(selected.json()["override_version"], none())

        after_select = client.get(configuration_url, headers=_auth(context)).json()
        assert_that(after_select["active"]["source_type"], equal_to("platform"))
        assert_that(after_select["active"]["source_template_version"], equal_to(2))
        assert_that(after_select["draft"]["source_template_version"], equal_to(1))
        assert_that(after_select["draft"]["soul_md"], equal_to("local change"))
        assert_that(after_select["draft"]["updated_at"], equal_to(local_edit["updated_at"]))


def test_agent_override_organization_source_update_is_labeled_and_can_be_selected():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        delegate = context.injector.get(PostgresRepositoryDelegate)
        template_repository = context.injector.get(TemplateRepository)
        source_v1 = cast(AgentTemplate, template_repository.get_pinned_template(context.agent))
        source_v2 = AgentTemplate(
            organization_id=source_v1.organization_id,
            template_key=source_v1.template_key,
            template_name=source_v1.template_name,
            template_source=source_v1.template_source,
            version=2,
            description="organization v2",
            soul_md="organization soul v2",
            identity_md=source_v1.identity_md,
            user_md=source_v1.user_md,
            tools_md=source_v1.tools_md,
            agents_md=source_v1.agents_md,
            boot_md=source_v1.boot_md,
            bootstrap_md=source_v1.bootstrap_md,
            heartbeat_md=source_v1.heartbeat_md,
        )
        delegate.save(source_v2)
        _pin_override_to_source(context, source_v1, AgentTemplateOverrideSourceType.ORGANIZATION)
        configuration_url = f"{_BASE}/{context.agent.id}/configuration"

        configuration = client.get(configuration_url, headers=_auth(context)).json()
        assert_that(configuration["source_update"]["source_type"], equal_to("organization"))
        assert_that(configuration["source_update"]["source_template_version"], equal_to(2))
        assert_that(configuration["source_update"]["soul_md"], equal_to("organization soul v2"))

        draft = client.post(f"{configuration_url}/draft", headers=_auth(context)).json()
        local_edit = client.patch(
            f"{configuration_url}/draft",
            json={"expected_updated_at": draft["updated_at"], "soul_md": "organization local change"},
            headers=_auth(context),
        ).json()
        agent_before_select = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
        selected = client.post(
            f"{configuration_url}/select",
            json={
                "selection_type": "organization",
                "template_key": source_v1.template_key,
                "template_version": 2,
                "expected_agent_updated_at": agent_before_select["updated_at"],
            },
            headers=_auth(context),
        )
        assert_that(selected.status_code, equal_to(status.HTTP_200_OK))
        assert_that(selected.json()["template_pin_type"], equal_to("shared"))
        assert_that(selected.json()["override_version"], none())

        after_select = client.get(configuration_url, headers=_auth(context)).json()
        assert_that(after_select["active"]["source_type"], equal_to("organization"))
        assert_that(after_select["active"]["source_template_version"], equal_to(2))
        assert_that(after_select["draft"]["source_template_version"], equal_to(1))
        assert_that(after_select["draft"]["soul_md"], equal_to("organization local change"))
        assert_that(after_select["draft"]["updated_at"], equal_to(local_edit["updated_at"]))


def test_agent_override_source_update_has_no_candidate_when_source_is_unavailable():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        delegate = context.injector.get(PostgresRepositoryDelegate)
        source = PlatformTemplate(
            template_key="unavailable-platform-source",
            template_name="Unavailable Platform Source",
            version=1,
            description="platform v1",
            soul_md="platform soul v1",
            identity_md="platform identity v1",
            user_md="platform user v1",
            tools_md="platform tools v1",
            agents_md="platform agents v1",
            boot_md="platform boot v1",
            bootstrap_md="platform bootstrap v1",
            heartbeat_md="platform heartbeat v1",
        )
        delegate.save(source)
        delegate.save(source.model_copy(update={"id": uuid7(), "version": 2, "soul_md": "platform soul v2"}))
        _pin_override_to_source(context, source, AgentTemplateOverrideSourceType.PLATFORM)
        delegate.delete_one(PlatformTemplate, source.id)

        configuration = context.client.get(
            f"{_BASE}/{context.agent.id}/configuration",
            headers=_auth(context),
        )
        assert_that(configuration.status_code, equal_to(status.HTTP_200_OK))
        assert_that(configuration.json()["source_update"], none())
        active_agent = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context))
        assert_that(active_agent.status_code, equal_to(status.HTTP_200_OK))
        assert_that(active_agent.json()["override_version"], equal_to(1))


def test_agent_configuration_select_rolls_back_to_prior_version_and_preserves_independent_draft():
    with given([*_GIVEN, there_is_an_agent(name="Rollback Agent")]) as context:
        client: TestClient = context.client
        configuration_url = f"{_BASE}/{context.agent.id}/configuration"

        with when("I publish and select Override Version 1"):
            draft_v1 = client.post(f"{configuration_url}/draft", headers=_auth(context)).json()
            client.patch(
                f"{configuration_url}/draft",
                json={"expected_updated_at": draft_v1["updated_at"], "soul_md": "# Soul v1"},
                headers=_auth(context),
            )
            draft_v1 = client.get(configuration_url, headers=_auth(context)).json()["draft"]
            publish_v1 = client.post(
                f"{configuration_url}/draft/publish",
                json={"expected_updated_at": draft_v1["updated_at"]},
                headers=_auth(context),
            ).json()
            agent_after_v1 = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            select_v1 = client.post(
                f"{configuration_url}/select",
                json={
                    "selection_type": "override",
                    "override_version": publish_v1["version"],
                    "expected_agent_updated_at": agent_after_v1["updated_at"],
                },
                headers=_auth(context),
            )
            assert_that(select_v1.status_code, equal_to(status.HTTP_200_OK))

        with when("I publish and select Override Version 2"):
            draft_v2 = client.post(f"{configuration_url}/draft", headers=_auth(context)).json()
            client.patch(
                f"{configuration_url}/draft",
                json={"expected_updated_at": draft_v2["updated_at"], "soul_md": "# Soul v2"},
                headers=_auth(context),
            )
            draft_v2 = client.get(configuration_url, headers=_auth(context)).json()["draft"]
            publish_v2 = client.post(
                f"{configuration_url}/draft/publish",
                json={"expected_updated_at": draft_v2["updated_at"]},
                headers=_auth(context),
            ).json()
            agent_after_v2 = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            select_v2 = client.post(
                f"{configuration_url}/select",
                json={
                    "selection_type": "override",
                    "override_version": publish_v2["version"],
                    "expected_agent_updated_at": agent_after_v2["updated_at"],
                },
                headers=_auth(context),
            )
            assert_that(select_v2.status_code, equal_to(status.HTTP_200_OK))

        with when("I start an independent draft and then roll back to Override Version 1"):
            rollback_draft = client.post(f"{configuration_url}/draft", headers=_auth(context)).json()
            client.patch(
                f"{configuration_url}/draft",
                json={"expected_updated_at": rollback_draft["updated_at"], "soul_md": "# Independent draft"},
                headers=_auth(context),
            )
            agent_after_draft = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            rollback = client.post(
                f"{configuration_url}/select",
                json={
                    "selection_type": "override",
                    "override_version": publish_v1["version"],
                    "expected_agent_updated_at": agent_after_draft["updated_at"],
                },
                headers=_auth(context),
            )

        with then("the Agent points back at Override Version 1 and the independent draft is preserved"):
            assert_that(rollback.status_code, equal_to(status.HTTP_200_OK))
            rolled_back = rollback.json()
            assert_that(rolled_back["template_pin_type"], equal_to("override"))
            assert_that(rolled_back["override_version"], equal_to(publish_v1["version"]))
            after_rollback = client.get(configuration_url, headers=_auth(context)).json()
            assert_that(after_rollback["active"]["soul_md"], equal_to("# Soul v1"))
            assert_that(after_rollback["draft"], is_not(none()))
            assert_that(after_rollback["draft"]["soul_md"], equal_to("# Independent draft"))


def test_agent_configuration_select_rejects_stale_agent_update():
    with given([*_GIVEN, there_is_an_agent(name="Stale Select Agent")]) as context:
        client: TestClient = context.client
        configuration_url = f"{_BASE}/{context.agent.id}/configuration"

        draft = client.post(f"{configuration_url}/draft", headers=_auth(context)).json()
        publish = client.post(
            f"{configuration_url}/draft/publish",
            json={"expected_updated_at": draft["updated_at"]},
            headers=_auth(context),
        ).json()
        stale_agent = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()

        with when("I select the Override Version once, then retry with the same stale timestamp"):
            first_select = client.post(
                f"{configuration_url}/select",
                json={
                    "selection_type": "override",
                    "override_version": publish["version"],
                    "expected_agent_updated_at": stale_agent["updated_at"],
                },
                headers=_auth(context),
            )
            assert_that(first_select.status_code, equal_to(status.HTTP_200_OK))

            second_draft = client.post(f"{configuration_url}/draft", headers=_auth(context)).json()
            client.patch(
                f"{configuration_url}/draft",
                json={"expected_updated_at": second_draft["updated_at"], "soul_md": "# Second"},
                headers=_auth(context),
            )
            second_draft = client.get(configuration_url, headers=_auth(context)).json()["draft"]
            second_publish = client.post(
                f"{configuration_url}/draft/publish",
                json={"expected_updated_at": second_draft["updated_at"]},
                headers=_auth(context),
            ).json()

            stale_select = client.post(
                f"{configuration_url}/select",
                json={
                    "selection_type": "override",
                    "override_version": second_publish["version"],
                    "expected_agent_updated_at": stale_agent["updated_at"],
                },
                headers=_auth(context),
            )

        with then("the stale selection is rejected with 409"):
            assert_that(stale_select.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_agent_configuration_publish_rejects_unassigned_required_skill():
    with given(
        [*_GIVEN, there_is_an_agent(name="Missing Required Skill Agent"), there_is_a_skill(name="Jira")]
    ) as context:
        client: TestClient = context.client
        configuration_url = f"{_BASE}/{context.agent.id}/configuration"
        skill_id = str(context.skill.id)

        with when("I mark a Skill required on the draft while it is still assigned to the Agent"):
            assign = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"skill_ids": [skill_id]},
                headers=_auth(context),
            )
            assert_that(assign.status_code, equal_to(status.HTTP_200_OK))

            draft = client.post(f"{configuration_url}/draft", headers=_auth(context)).json()
            marked = client.patch(
                f"{configuration_url}/draft",
                json={"expected_updated_at": draft["updated_at"], "required_skill_ids": [skill_id]},
                headers=_auth(context),
            )
            assert_that(marked.status_code, equal_to(status.HTTP_200_OK))
            marked_body = marked.json()

        with when("the required Skill is removed from the Agent before publishing"):
            unassign = client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"removed_skill_ids": [skill_id]},
                headers=_auth(context),
            )
            assert_that(unassign.status_code, equal_to(status.HTTP_200_OK))

        with then("publishing without the required Skill assigned is rejected with 400"):
            publish = client.post(
                f"{configuration_url}/draft/publish",
                json={"expected_updated_at": marked_body["updated_at"]},
                headers=_auth(context),
            )
            assert_that(publish.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_agent_configuration_override_history_retained_after_soft_delete():
    with given([*_GIVEN, there_is_an_agent(name="Retention Agent")]) as context:
        client: TestClient = context.client
        configuration_url = f"{_BASE}/{context.agent.id}/configuration"
        agent_id = context.agent.id

        draft = client.post(f"{configuration_url}/draft", headers=_auth(context)).json()
        published = client.post(
            f"{configuration_url}/draft/publish",
            json={"expected_updated_at": draft["updated_at"]},
            headers=_auth(context),
        ).json()

        with when("I soft-delete the Agent"):
            delete_response = client.delete(f"{_BASE}/{agent_id}", headers=_auth(context))
            assert_that(delete_response.status_code, equal_to(status.HTTP_204_NO_CONTENT))

        with then("the Override Version remains retained"):
            override_repository: AgentOverrideRepository = context.injector.get(AgentOverrideRepository)
            retained = override_repository.get_version(agent_id, context.organization.id, published["version"])
            assert retained is not None
            assert_that(retained.soul_md, equal_to(published["soul_md"]))


# ---------------------------------------------------------------------------
# Google Workspace (gog) integration
# ---------------------------------------------------------------------------

_GWS_CONTENT = {
    "email": "user@example.com",
    "services": ["gmail", "calendar"],
    "scopes": [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.settings.basic",
        "https://www.googleapis.com/auth/gmail.settings.sharing",
        "https://www.googleapis.com/auth/calendar",
    ],
    "refresh_token": "gws-refresh-token",
    "client_id": "client-id.apps.googleusercontent.com",
    "client_secret": "GOCSPX-secret",
}


def _configure_gws(client: TestClient, context, content: dict | None = None):
    return client.patch(
        f"{_BASE}/{context.agent.id}",
        json={"secrets": [{"provider": "google_workspace", "content": content or _GWS_CONTENT}]},
        headers=_auth(context),
    )


def test_patch_agent_accepts_google_workspace_secret():
    """Covers the enum member, the content schema, and the DB check constraint."""
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I configure a Google Workspace credential"):
            response = _configure_gws(client, context)

        with then("it is stored and listed without exposing its contents"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            providers = [s["provider"] for s in response.json()["secrets"]]
            assert_that(providers, has_item("google_workspace"))
            assert_that(response.text, is_not(contains_string("gws-refresh-token")))


def test_patch_agent_rejects_unsupported_google_workspace_service():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I ask for a service gog's v1 allowlist does not cover"):
            response = _configure_gws(client, context, {**_GWS_CONTENT, "services": ["gmail", "youtube"]})

        with then("it is rejected"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))


def test_patch_agent_rejects_google_workspace_scopes_missing_selected_service():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("the recorded consent scopes do not cover the selected services"):
            response = _configure_gws(
                client,
                context,
                {
                    **_GWS_CONTENT,
                    "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
                },
            )

        with then("it is rejected"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))


def test_start_agent_materializes_gog_env_and_setup_script():
    import json as _json

    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start an agent with a Google Workspace credential"):
            _configure_gws(client, context)
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the pod secret carries everything gog needs to rebuild its state"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            secret = k8s.create_secret.call_args.args[1]
            assert_that(secret.string_data["GOG_HOME"], equal_to("/home/node/.config/gogcli"))
            assert_that(secret.string_data["GOG_KEYRING_BACKEND"], equal_to("file"))
            assert_that(len(secret.string_data["GOG_KEYRING_PASSWORD"]), greater_than(0))
            assert_that(secret.string_data["GOG_ACCOUNT_EMAIL"], equal_to("user@example.com"))
            token = _json.loads(secret.string_data["GOG_TOKEN_JSON"])
            assert_that(token["refresh_token"], equal_to("gws-refresh-token"))
            assert_that(token["services"], equal_to(["gmail", "calendar"]))
            client_json = _json.loads(secret.string_data["GOG_CLIENT_JSON"])
            assert_that(client_json["web"]["client_id"], equal_to("client-id.apps.googleusercontent.com"))

        with then("the setup script is mounted and the agent is told how to use gog"):
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(config_map.data, has_key("gog-setup.sh"))
            assert_that(config_map.data["gog-setup.sh"], contains_string("gog auth tokens import -"))
            assert_that(config_map.data["AGENTS.md"], contains_string("Google Workspace (gog)"))
            assert_that(config_map.data["AGENTS.md"], contains_string("user@example.com"))


def test_start_agent_gog_state_is_not_on_the_hermes_pvc():
    """Hermes' PVC is /opt/data (where aai-cli lives); gog's state is deliberately
    ephemeral, since it is rebuilt from the credential on every boot."""
    with given([*_GIVEN_WITH_HERMES_IMAGE, there_is_an_agent(agent_type=AgentType.HERMES)]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start a Hermes agent with a Google Workspace credential"):
            _configure_gws(client, context)
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("GOG_HOME is under the container home, not the PVC"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            secret = k8s.create_secret.call_args.args[1]
            assert_that(secret.string_data["GOG_HOME"], equal_to("/home/hermes/.config/gogcli"))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(config_map.data, has_key("gog-setup.sh"))


def test_start_agent_without_google_workspace_has_no_gog_artifacts():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("I start an agent with no Google Workspace credential"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("no gog script or env is injected"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(config_map.data, is_not(has_key("gog-setup.sh")))
            secret = k8s.create_secret.call_args.args[1]
            assert_that(secret.string_data, is_not(has_key("GOG_TOKEN_JSON")))
            assert_that(config_map.data["AGENTS.md"], is_not(contains_string("Google Workspace (gog)")))


def test_start_agent_with_only_google_workspace_omits_aai_cli_policy():
    """gog takes no --profile, so the aai-cli block must not claim to cover it."""
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s: MagicMock = context.injector.get(KubernetesClient)

        with when("Google Workspace is the agent's only integration"):
            _configure_gws(client, context)
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the aai-cli integrations block and config.toml are absent"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            config_map = k8s.create_config_map.call_args.args[1]
            assert_that(config_map.data["AGENTS.md"], is_not(contains_string("Integrations (aai-cli)")))
            assert_that(config_map.data, is_not(has_key("aai-cli-config.toml")))


def test_start_agent_rejects_google_workspace_without_a_client():
    """The credential must name the OAuth client its refresh token was issued under;
    with no server-owned client configured either, starting has to fail loudly.

    The empty client config is explicit: a developer's root .env may define real Google
    client credentials, which would otherwise be backfilled and let this pass.
    """
    with given([*_GIVEN_WITHOUT_GOOGLE_CLIENT, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("the stored credential has no client id/secret"):
            content = {k: v for k, v in _GWS_CONTENT.items() if k not in ("client_id", "client_secret")}
            _configure_gws(client, context, content)
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the start is rejected with a reconnect hint"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("Google Workspace credential"))
