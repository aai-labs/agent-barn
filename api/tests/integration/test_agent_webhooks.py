import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import status
from hamcrest import assert_that, equal_to, has_length, is_, none
from sqlmodel import Session, select

from api.domains.agent_webhooks.models import WebhookInvocation, WebhookInvocationStatus
from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.communications.models import CommunicationConnection
from api.domains.communications.repository import CommunicationConnectionRepository
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "API_EXTERNAL_URL": "https://api.agentbarn.test",
            "COMMUNICATIONS_NATIVE_PLATFORMS": "slack,discord,telegram,teams",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_an_agent(status=AgentStatus.RUNNING),
]


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _default_channel_settings(platform: str) -> dict:
    if platform == "slack":
        return {"default_delivery_target": {"channel_id": "C123"}}
    return {"home_channel_id": "home-1"}


def _ensure_native_connection(context, platform: str = "slack", settings: dict | None = None) -> None:
    repository = context.injector.get(CommunicationConnectionRepository)
    if repository.get_active_by_platform_key(context.agent.id, platform) is not None:
        return
    context.injector.get(PostgresRepositoryDelegate).save(
        CommunicationConnection(
            organization_id=context.organization.id,
            agent_id=context.agent.id,
            platform_key=platform,
            display_name=f"Native {platform.title()}",
            settings=_default_channel_settings(platform) if settings is None else settings,
            credentials_encrypted="unused",
            driver_key_encrypted="unused",
        )
    )


def _create_webhook(context, name: str = "Jira automation", platform: str = "slack") -> dict:
    _ensure_native_connection(context, platform)
    response = context.client.post(
        f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/webhooks",
        json={"display_name": name, "delivery_platform": platform},
        headers=_auth(context),
    )
    assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
    return response.json()


def _fire(context, webhook_id: str, secret: str, body: dict, *, timestamp: int | None = None) -> httpx.Response:
    raw = json.dumps(body, separators=(",", ":")).encode()
    signed_at = str(int(time.time()) if timestamp is None else timestamp)
    signature = "sha256=" + hmac.new(secret.encode(), signed_at.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return context.client.post(
        f"/agent-hooks/v1/{webhook_id}",
        content=raw,
        headers={
            "X-AgentBarn-Webhook-Version": "1",
            "X-AgentBarn-Timestamp": signed_at,
            "X-AgentBarn-Signature": signature,
            "Content-Type": "application/json",
        },
    )


def _set_trigger_key(context, value: str = "trigger-key") -> None:
    repository = context.injector.get(AgentRepository)
    context.agent.communication_key_encrypted = encrypt_token(value, TEST_ENCRYPTION_KEY)
    repository.save(context.agent)


def _invocation(context, invocation_id: str) -> WebhookInvocation:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        invocation = session.get(WebhookInvocation, UUID(invocation_id))
        assert invocation is not None
        session.expunge(invocation)
        return invocation


def test_create_reveals_the_secret_once_and_selects_a_native_delivery_platform() -> None:
    with given(_GIVEN) as context:
        created = _create_webhook(context)

        assert_that(created["delivery_platform"], equal_to("slack"))
        assert_that(created["webhook_url"], equal_to(f"https://api.agentbarn.test/agent-hooks/v1/{created['id']}"))
        assert_that(len(created["signing_secret"]) >= 32, is_(True))

        response = context.client.get(
            f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/webhooks/{created['id']}",
            headers=_auth(context),
        )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["signing_secret"], none())


def test_create_rejects_a_platform_without_an_enabled_native_connection() -> None:
    with given(_GIVEN) as context:
        response = context.client.post(
            f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/webhooks",
            json={"display_name": "Jira", "delivery_platform": "slack"},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_a_connection_without_a_default_channel_is_not_eligible() -> None:
    with given(_GIVEN) as context:
        _ensure_native_connection(context, "discord", settings={})

        platforms = context.client.get(
            f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/webhooks/delivery-platforms",
            headers=_auth(context),
        )
        created = context.client.post(
            f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/webhooks",
            json={"display_name": "Jira", "delivery_platform": "discord"},
            headers=_auth(context),
        )

        assert_that(platforms.status_code, equal_to(status.HTTP_200_OK))
        assert_that(platforms.json(), has_length(0))
        assert_that(created.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(created.json()["detail"], equal_to("The discord connection has no default channel configured"))


def test_ingress_fails_visibly_when_the_default_channel_was_removed() -> None:
    with given(_GIVEN) as context:
        webhook = _create_webhook(context, platform="telegram")
        repository = context.injector.get(CommunicationConnectionRepository)
        connection = repository.get_active_by_platform_key(context.agent.id, "telegram")
        connection.settings = {}
        context.injector.get(PostgresRepositoryDelegate).save(connection)

        response = _fire(context, webhook["id"], webhook["signing_secret"], {"prompt": "Summarize"})

        assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
        invocation = _invocation(context, response.json()["invocation_id"])
        assert_that(invocation.status, equal_to(WebhookInvocationStatus.DISPATCH_FAILED))
        assert_that(invocation.last_error_code, equal_to("DELIVERY_CHANNEL_UNAVAILABLE"))


def test_ingress_rejects_a_prompt_over_5000_characters() -> None:
    with given(_GIVEN) as context:
        webhook = _create_webhook(context)

        response = _fire(context, webhook["id"], webhook["signing_secret"], {"prompt": "x" * 5_001})

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            assert_that(list(session.exec(select(WebhookInvocation)).all()), has_length(0))


def test_signed_ingress_persists_one_idempotent_invocation_without_output() -> None:
    with given(_GIVEN) as context:
        webhook = _create_webhook(context)
        payload = {"event_id": "PROJ-42", "prompt": "Summarize PROJ-42"}

        first = _fire(context, webhook["id"], webhook["signing_secret"], payload)
        duplicate = _fire(context, webhook["id"], webhook["signing_secret"], payload)

        assert_that(first.status_code, equal_to(status.HTTP_202_ACCEPTED))
        assert_that(duplicate.json()["invocation_id"], equal_to(first.json()["invocation_id"]))
        assert_that(duplicate.json()["duplicate"], is_(True))
        invocation = _invocation(context, first.json()["invocation_id"])
        assert_that(invocation.status, equal_to(WebhookInvocationStatus.DISPATCH_FAILED))
        assert_that(invocation.last_error_code, equal_to("AGENT_NOT_RUNNING"))
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            assert_that(list(session.exec(select(WebhookInvocation)).all()), has_length(1))


def test_ingress_without_event_id_creates_a_new_invocation_per_request() -> None:
    with given(_GIVEN) as context:
        webhook = _create_webhook(context)
        payload = {"prompt": "Summarize the backlog"}

        first = _fire(context, webhook["id"], webhook["signing_secret"], payload)
        second = _fire(context, webhook["id"], webhook["signing_secret"], payload)

        assert_that(first.status_code, equal_to(status.HTTP_202_ACCEPTED))
        assert_that(second.status_code, equal_to(status.HTTP_202_ACCEPTED))
        assert_that(second.json()["duplicate"], is_(False))
        assert_that(second.json()["invocation_id"] != first.json()["invocation_id"], is_(True))
        assert_that(_invocation(context, first.json()["invocation_id"]).external_event_id, none())


def test_ingress_requires_a_prompt() -> None:
    with given(_GIVEN) as context:
        webhook = _create_webhook(context)

        response = _fire(context, webhook["id"], webhook["signing_secret"], {"event_id": "evt-1"})

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_ingress_rejects_a_bad_signature_without_persisting_an_invocation() -> None:
    with given(_GIVEN) as context:
        webhook = _create_webhook(context)
        response = context.client.post(
            f"/agent-hooks/v1/{webhook['id']}",
            json={"event_id": "evt-1", "prompt": "Do something"},
            headers={"X-AgentBarn-Webhook-Version": "1"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            assert_that(list(session.exec(select(WebhookInvocation)).all()), has_length(0))


def test_ingress_rejects_a_correctly_signed_request_replayed_outside_the_window() -> None:
    with given(_GIVEN) as context:
        webhook = _create_webhook(context)
        response = _fire(
            context,
            webhook["id"],
            webhook["signing_secret"],
            {"prompt": "Do something"},
            timestamp=int(time.time()) - 301,
        )

        assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            assert_that(list(session.exec(select(WebhookInvocation)).all()), has_length(0))


def test_active_webhook_names_are_unique_per_agent() -> None:
    with given(_GIVEN) as context:
        _create_webhook(context)
        response = context.client.post(
            f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/webhooks",
            json={"display_name": "jira AUTOMATION", "delivery_platform": "slack"},
            headers=_auth(context),
        )
        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_webhook_is_concealed_through_another_agent_path() -> None:
    with given(_GIVEN) as context:
        webhook = _create_webhook(context)
        response = context.client.get(
            f"/api/v1/organizations/{context.organization.id}/agents/{uuid4()}/webhooks/{webhook['id']}",
            headers=_auth(context),
        )
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_ingress_submits_a_native_job_and_stops_tracking_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    with given(_GIVEN) as context:
        webhook = _create_webhook(context)
        _set_trigger_key(context)
        calls: list[dict] = []

        def accept_trigger(method, url, **kwargs):
            calls.append({"method": method, "url": url, **kwargs})
            return httpx.Response(202, json={"native_job_id": "native-job-42"})

        monkeypatch.setattr("api.domains.agent_webhooks.dispatch.httpx.request", accept_trigger)
        response = _fire(
            context,
            webhook["id"],
            webhook["signing_secret"],
            {"event_id": "evt-native", "prompt": "Prepare release notes"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
        invocation = _invocation(context, response.json()["invocation_id"])
        assert_that(invocation.status, equal_to(WebhookInvocationStatus.SUBMITTED))
        assert_that(invocation.native_job_id, equal_to("native-job-42"))
        assert_that(invocation.dispatch_attempt_count, equal_to(1))
        submitted = json.loads(calls[0]["content"])
        assert_that(submitted["delivery_platform"], equal_to("slack"))
        assert_that(submitted["prompt"], equal_to("Prepare release notes"))


def test_failed_dispatch_can_be_retried_as_a_new_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    with given(_GIVEN) as context:
        webhook = _create_webhook(context)
        _set_trigger_key(context)
        monkeypatch.setattr(
            "api.domains.agent_webhooks.dispatch.httpx.request",
            lambda *args, **kwargs: httpx.Response(503),
        )
        failed = _fire(
            context,
            webhook["id"],
            webhook["signing_secret"],
            {"event_id": "evt-retry", "prompt": "Try this"},
        )
        failed_invocation = _invocation(context, failed.json()["invocation_id"])
        assert_that(failed_invocation.dispatch_attempt_count, equal_to(3))
        assert_that(failed_invocation.status, equal_to(WebhookInvocationStatus.DISPATCH_FAILED))

        monkeypatch.setattr(
            "api.domains.agent_webhooks.dispatch.httpx.request",
            lambda *args, **kwargs: httpx.Response(202, json={"native_job_id": "retry-job"}),
        )
        retried = context.client.post(
            f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/webhooks/"
            f"{webhook['id']}/invocations/{failed.json()['invocation_id']}/retry",
            headers=_auth(context),
        )

        assert_that(retried.status_code, equal_to(status.HTTP_200_OK))
        assert_that(retried.json()["dispatch_generation"], equal_to(2))
        assert_that(retried.json()["status"], equal_to("SUBMITTED"))
        assert_that(retried.json()["native_job_id"], equal_to("retry-job"))


def _retry(context, webhook_id: str, invocation_id: str) -> httpx.Response:
    return context.client.post(
        f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/webhooks/"
        f"{webhook_id}/invocations/{invocation_id}/retry",
        headers=_auth(context),
    )


def _set_invocation(context, invocation_id: str, **values) -> None:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        invocation = session.get(WebhookInvocation, UUID(invocation_id))
        assert invocation is not None
        for key, value in values.items():
            setattr(invocation, key, value)
        session.add(invocation)
        session.commit()


def test_an_abandoned_received_dispatch_can_be_retried_once_it_stalls(monkeypatch: pytest.MonkeyPatch) -> None:
    with given(_GIVEN) as context:
        webhook = _create_webhook(context)
        _set_trigger_key(context)
        monkeypatch.setattr(
            "api.domains.agent_webhooks.dispatch.httpx.request",
            lambda *args, **kwargs: httpx.Response(202, json={"native_job_id": "recovered-job"}),
        )
        fired = _fire(context, webhook["id"], webhook["signing_secret"], {"prompt": "Recover me"})
        invocation_id = fired.json()["invocation_id"]
        # As if the API process died between storing the invocation and recording the dispatch.
        _set_invocation(context, invocation_id, status=WebhookInvocationStatus.RECEIVED, native_job_id=None)

        assert_that(_retry(context, webhook["id"], invocation_id).status_code, equal_to(status.HTTP_409_CONFLICT))

        _set_invocation(context, invocation_id, updated_at=datetime.now(UTC) - timedelta(minutes=5))
        retried = _retry(context, webhook["id"], invocation_id)

        assert_that(retried.status_code, equal_to(status.HTTP_200_OK))
        assert_that(retried.json()["status"], equal_to("SUBMITTED"))
        assert_that(retried.json()["dispatch_generation"], equal_to(2))


def test_a_disabled_webhook_does_not_retry_its_invocations(monkeypatch: pytest.MonkeyPatch) -> None:
    with given(_GIVEN) as context:
        webhook = _create_webhook(context)
        _set_trigger_key(context)
        monkeypatch.setattr(
            "api.domains.agent_webhooks.dispatch.httpx.request",
            lambda *args, **kwargs: httpx.Response(400),
        )
        failed = _fire(context, webhook["id"], webhook["signing_secret"], {"prompt": "Not now"})
        disabled = context.client.patch(
            f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/webhooks/{webhook['id']}",
            json={"revision": webhook["revision"], "enabled": False},
            headers=_auth(context),
        )
        assert_that(disabled.status_code, equal_to(status.HTTP_200_OK))

        response = _retry(context, webhook["id"], failed.json()["invocation_id"])

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(
            _invocation(context, failed.json()["invocation_id"]).status,
            equal_to(WebhookInvocationStatus.DISPATCH_FAILED),
        )
