from unittest.mock import MagicMock, patch
from uuid import uuid4

from hamcrest import assert_that, contains_string, equal_to

from api.domains.communications.models import (
    ConversationLocation,
    ProcessingFeedbackStage,
)
from api.domains.communications.plugins.base import (
    ProcessingFeedbackContext,
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
