from unittest.mock import patch

import pytest
from hamcrest import assert_that, contains_string, empty, equal_to
from sqlalchemy.exc import IntegrityError

from api.domains.communications.models import CommunicationConnection
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.helpers.agent_messages import (
    STEPS,
    messaging_ready,
    origin_request,
    rows,
    scheduled_request,
    submit,
)
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, there_is_an_agent, there_is_an_agent_in_another_org


def _conversation(channel):
    return {"id": channel, "name": "updates", "is_im": False}


@pytest.fixture(autouse=True)
def slack_lookup():
    with patch("api.domains.communications.plugins.slack.SlackClient.get_conversation", side_effect=_conversation):
        with patch("api.domains.communications.plugins.slack.SlackPlatformPlugin.processing_feedback"):
            yield


@pytest.mark.parametrize("destination", ["default", "origin", "explicit"])
def test_retired_message_endpoint_returns_terminal_response_without_queueing(destination):
    with given([*STEPS, messaging_ready]) as context:
        if destination == "default":
            payload = scheduled_request()
        elif destination == "origin":
            payload = origin_request(context)
        else:
            payload = {
                "text": "Requested update",
                "idempotency_key": "retired-interactive",
                "destination": {"kind": "explicit", "target": {"recipient": "C456"}},
                "context": {"kind": "interactive", "execution_token": "historical-execution"},
            }
        with when("an old bridge client submits a message"):
            response = submit(context, payload)
        with then("it receives a terminal retirement response and creates no history or work"):
            assert_that(response.status_code, equal_to(410))
            assert_that(response.json()["detail"], contains_string("retired"))
            for records in rows(context):
                assert_that(records, empty())


def test_runtime_identity_requires_matching_credential():
    with given([*STEPS, messaging_ready]) as context:
        context.runtime_headers["Authorization"] = "Bearer wrong-key"
        assert_that(submit(context, scheduled_request()).status_code, equal_to(401))


def test_database_enforces_one_default_including_disabled_connections():
    with given([*STEPS, messaging_ready]) as context:
        other = CommunicationConnection(
            organization_id=context.connection.organization_id,
            agent_id=context.connection.agent_id,
            # Another platform, so only the one-default rule can reject it.
            platform_key="discord",
            display_name="Another",
            enabled=False,
            settings=dict(context.connection.settings),
            credentials_encrypted=context.connection.credentials_encrypted,
            driver_key_encrypted=context.connection.driver_key_encrypted,
        )
        with pytest.raises(IntegrityError):
            context.injector.get(PostgresRepositoryDelegate).save(other)


def test_setting_a_conflicting_default_returns_conflict_through_connection_editor_api():
    with given([*STEPS, messaging_ready]) as context:
        response = context.client.post(
            f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections",
            headers={"Authorization": f"Bearer {context.access_token}"},
            json={
                "platform_key": "slack",
                "display_name": "Second default",
                "enabled": False,
                "settings": {"channel_ids": ["C456"], "default_delivery_target": {"recipient": "C456"}},
                "credentials": {"bot_token": "another-bot", "app_token": "another-app"},
            },
        )
        assert_that(response.status_code, equal_to(409), response.text)


@pytest.mark.parametrize("body", ["", "{invalid", "null", "{}"])
def test_retired_message_endpoint_ignores_obsolete_body_contract(body):
    with given([*STEPS, messaging_ready]) as context:
        with when("a retired client submits an absent or unusable body"):
            response = context.communications_client.post(
                f"/communications/v1/agents/{context.agent.id}/messages",
                headers={**context.runtime_headers, "Content-Type": "application/json"},
                content=body,
            )
        with then("the authenticated request receives terminal retirement without writes"):
            assert_that(response.status_code, equal_to(410))
            for records in rows(context):
                assert_that(records, empty())


@pytest.mark.parametrize("cross_organization", [False, True])
def test_retired_message_endpoint_rejects_another_agents_credential(cross_organization):
    with given([*STEPS, messaging_ready]) as context:
        (there_is_an_agent_in_another_org() if cross_organization else there_is_an_agent())(context)
        context.agent.communication_key_encrypted = encrypt_token("other-runtime", TEST_ENCRYPTION_KEY)
        context.injector.get(PostgresRepositoryDelegate).save(context.agent)
        with when("a runtime submits to a different Agent using its own credential"):
            response = submit(context, scheduled_request())
        with then("the runtime identity is rejected before returning retirement information"):
            assert_that(response.status_code, equal_to(401))
            for records in rows(context):
                assert_that(records, empty())


def test_retired_message_endpoint_keeps_protocol_negotiation():
    with given([*STEPS, messaging_ready]) as context:
        context.runtime_headers["X-AgentBarn-Communications-Version"] = "unknown"
        with when("a client submits with an unsupported protocol version"):
            response = submit(context, scheduled_request())
        with then("the existing protocol upgrade response is preserved"):
            assert_that(response.status_code, equal_to(426))
