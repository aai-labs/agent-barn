from unittest.mock import MagicMock, patch
from uuid import uuid4

from hamcrest import assert_that, contains_string, equal_to, is_, none, not_

from api.domains.communications.models import (
    ConversationLocation,
    OutboundCommunicationEnvelope,
    PlatformCapability,
    ProcessingFeedbackStage,
)
from api.domains.communications.plugins.base import (
    ProcessingFeedbackContext,
    failure_feedback_idempotency_key,
    provider_idempotency_key,
)
from api.domains.communications.plugins.discord import DiscordCredentials, DiscordPlatformPlugin, DiscordSettings


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
def test_terminal_failure_notice_does_not_reuse_the_reply_idempotency_key(mock_client) -> None:
    context = _context(ProcessingFeedbackStage.FAILED)
    source_delivery_id = context.source_delivery_id
    assert source_delivery_id is not None
    plugin = _plugin()
    credentials = DiscordCredentials(bot_token="bot-value")

    plugin.send(
        DiscordSettings(),
        credentials,
        OutboundCommunicationEnvelope(
            source_delivery_id=source_delivery_id,
            location=context.location,
            text="the answer",
            reply_to_provider_message_id=context.provider_message_id,
        ),
        idempotency_key=str(source_delivery_id),
    )
    plugin.processing_feedback(DiscordSettings(), credentials, context)

    sends = mock_client.return_value.send_message.call_args_list
    reply_key = sends[0].kwargs["idempotency_key"]
    failure_notice_key = sends[1].kwargs["idempotency_key"]
    assert_that(reply_key, equal_to(provider_idempotency_key(str(source_delivery_id))))
    assert_that(failure_notice_key, equal_to(failure_feedback_idempotency_key(context)))
    assert_that(failure_notice_key, not_(equal_to(reply_key)))


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


@patch("api.domains.communications.plugins.slack.SlackClient")
def test_slack_terminal_failure_posts_the_reason_in_thread(mock_client) -> None:
    from api.domains.communications.plugins.slack import SlackCredentials, SlackPlatformPlugin, SlackSettings

    plugin = SlackPlatformPlugin(MagicMock(skip_slack_token_validation=True))
    context = ProcessingFeedbackContext(
        connection_id=uuid4(),
        stage=ProcessingFeedbackStage.FAILED,
        location=ConversationLocation(id="C1", type="CHANNEL", thread_id="1789545886.673029"),
        provider_message_id="1789545886.673029",
        source_delivery_id=uuid4(),
        error_summary="The provider reports exhausted credits or billing (HTTP 402)",
    )

    plugin.processing_feedback(
        SlackSettings(),
        SlackCredentials(bot_token="xoxb-value", app_token="xapp-value"),
        context,
    )

    send = mock_client.return_value.send_message
    assert_that(send.call_args.args[0], equal_to("C1"))
    assert_that(send.call_args.args[1], contains_string("exhausted credits or billing (HTTP 402)"))
    assert_that(send.call_args.kwargs["thread_id"], equal_to("1789545886.673029"))


@patch("api.domains.communications.plugins.slack.SlackClient")
def test_slack_success_posts_no_notice(mock_client) -> None:
    from api.domains.communications.plugins.slack import SlackCredentials, SlackPlatformPlugin, SlackSettings

    plugin = SlackPlatformPlugin(MagicMock(skip_slack_token_validation=True))

    plugin.processing_feedback(
        SlackSettings(),
        SlackCredentials(bot_token="xoxb-value", app_token="xapp-value"),
        ProcessingFeedbackContext(
            connection_id=uuid4(),
            stage=ProcessingFeedbackStage.SUCCEEDED,
            location=ConversationLocation(id="C1", type="CHANNEL", thread_id="1.1"),
            provider_message_id="1.1",
        ),
    )

    assert_that(mock_client.return_value.send_message.call_count, equal_to(0))
