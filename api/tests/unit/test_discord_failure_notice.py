from unittest.mock import MagicMock, patch
from uuid import uuid4

from hamcrest import assert_that, contains_string, equal_to, is_, none, not_

from api.domains.communications.models import (
    ConversationLocation,
    PlatformCapability,
    ProcessingFeedbackStage,
)
from api.domains.communications.plugins.base import ProcessingFeedbackContext
from api.domains.communications.plugins.discord import (
    DiscordCredentials,
    DiscordPlatformPlugin,
    DiscordSettings,
)


def _plugin() -> DiscordPlatformPlugin:
    return DiscordPlatformPlugin(MagicMock(skip_discord_token_validation=True))


def _context(stage: ProcessingFeedbackStage, **overrides) -> ProcessingFeedbackContext:
    return ProcessingFeedbackContext(
        connection_id=uuid4(),
        stage=stage,
        location=ConversationLocation(id="channel-1", type="CHANNEL"),
        provider_message_id="message-1",
        source_delivery_id=uuid4(),
        **overrides,
    )


def test_discord_declares_processing_feedback_so_the_hook_is_not_skipped() -> None:
    assert_that(PlatformCapability.PROCESSING_FEEDBACK in _plugin().capabilities, is_(True))


@patch("api.domains.communications.plugins.discord.DiscordClient")
def test_terminal_failure_replies_in_the_originating_thread_with_the_reason(mock_client) -> None:
    context = _context(
        ProcessingFeedbackStage.FAILED,
        error_summary="The provider reports exhausted credits or billing (HTTP 402)",
    )

    _plugin().processing_feedback(DiscordSettings(), DiscordCredentials(bot_token="bot-value"), context)

    send = mock_client.return_value.send_message
    assert_that(send.call_args.args[0], equal_to("channel-1"))
    assert_that(send.call_args.args[1], contains_string("exhausted credits or billing (HTTP 402)"))
    assert_that(send.call_args.kwargs["reply_to_id"], equal_to("message-1"))
    # Deduplicated on the Delivery, so a re-run cannot double-post.
    assert_that(send.call_args.kwargs["idempotency_key"], not_(none()))


@patch("api.domains.communications.plugins.discord.DiscordClient")
def test_non_terminal_stages_stay_silent(mock_client) -> None:
    for stage in (ProcessingFeedbackStage.ACCEPTED, ProcessingFeedbackStage.CLAIMED, ProcessingFeedbackStage.SUCCEEDED):
        _plugin().processing_feedback(DiscordSettings(), DiscordCredentials(bot_token="bot-value"), _context(stage))

    assert_that(mock_client.return_value.send_message.call_count, equal_to(0))


@patch("api.domains.communications.plugins.discord.DiscordClient")
def test_a_send_failure_never_escapes_the_feedback_hook(mock_client) -> None:
    mock_client.return_value.send_message.side_effect = RuntimeError("discord is down")

    _plugin().processing_feedback(
        DiscordSettings(),
        DiscordCredentials(bot_token="bot-value"),
        _context(ProcessingFeedbackStage.FAILED, error_summary="boom"),
    )


@patch("api.domains.communications.plugins.discord.DiscordClient")
def test_connection_alert_goes_to_the_home_channel(mock_client) -> None:
    settings = DiscordSettings(home_channel_id="alerts-1")

    _plugin().alert(settings, DiscordCredentials(bot_token="bot-value"), "ingress is down")

    mock_client.return_value.send_message.assert_called_once_with("alerts-1", "ingress is down")


@patch("api.domains.communications.plugins.discord.DiscordClient")
def test_connection_alert_is_skipped_without_a_home_channel(mock_client) -> None:
    _plugin().alert(DiscordSettings(), DiscordCredentials(bot_token="bot-value"), "ingress is down")

    assert_that(mock_client.return_value.send_message.call_count, equal_to(0))
