from unittest.mock import patch
from uuid import uuid4

import pytest
from hamcrest import assert_that, contains_string, empty, equal_to
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from api.domains.communications.models import (
    AgentMessageCreate,
    CommunicationConnection,
)
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


@pytest.mark.parametrize(
    "context_kind,destination_kind,allowed",
    [
        # A scheduled run may reach its configured default or the conversation that
        # created it. It may never name a destination itself -- that is the whole
        # authorization boundary for work with no user in the loop.
        ("scheduled", "default", True),
        ("scheduled", "origin", True),
        ("scheduled", "explicit", False),
        # An interactive run has a live execution to authorize an explicit send, but
        # no job origin to inherit.
        ("interactive", "default", False),
        ("interactive", "explicit", True),
        ("interactive", "origin", False),
    ],
)
def test_only_the_allowed_destination_kinds_are_accepted_per_context(context_kind, destination_kind, allowed):
    destinations = {
        "default": {"kind": "default"},
        "explicit": {"kind": "explicit", "target": {"recipient": "C456"}},
        "origin": {
            "kind": "origin",
            "connection_id": str(uuid4()),
            "channel_id": "C456",
            "thread_id": None,
        },
    }
    contexts = {
        "scheduled": {"kind": "scheduled", "run_id": "hermes:run"},
        "interactive": {"kind": "interactive", "execution_token": "token"},
    }
    payload = {
        "text": "Scheduled result",
        "idempotency_key": "matrix",
        "destination": destinations[destination_kind],
        "context": contexts[context_kind],
    }
    if allowed:
        AgentMessageCreate.model_validate(payload)
    else:
        with pytest.raises(ValidationError):
            AgentMessageCreate.model_validate(payload)


def test_a_connection_id_is_not_part_of_the_explicit_contract():
    """Connection identity changes when an operator recreates a Connection, so it
    must never be something a prompt carries or a model can name."""
    with pytest.raises(ValidationError):
        AgentMessageCreate.model_validate(
            {
                "text": "hello",
                "idempotency_key": "k",
                "destination": {
                    "kind": "explicit",
                    "connection_id": str(uuid4()),
                    "target": {"recipient": "C456"},
                },
                "context": {"kind": "interactive", "execution_token": "token"},
            }
        )
