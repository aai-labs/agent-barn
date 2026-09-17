import json
from unittest.mock import MagicMock, patch

import httpx
from hamcrest import assert_that, calling, equal_to, none, raises

from api.domains.communications.plugins.base import provider_idempotency_key
from api.infrastructure.discord.client import DiscordClient
from api.infrastructure.shared.cache import clear_cache


@patch("api.infrastructure.discord.client.cached", side_effect=lambda _key, fetch, ttl: fetch())
@patch("api.infrastructure.discord.client.resilient_request")
def test_discord_client_resolves_user_and_channel_names(mock_request, _mock_cached):
    user_response = MagicMock(status_code=200)
    user_response.json.return_value = {"id": "user-1", "global_name": "Alice", "username": "alice"}
    channel_response = MagicMock(status_code=200)
    channel_response.json.return_value = {"id": "channel-1", "name": "ops-alerts"}
    mock_request.side_effect = [user_response, channel_response]
    client = DiscordClient("discord-token")

    assert_that(client.get_user_display_name("user-1"), equal_to("Alice"))
    assert_that(client.get_channel_display_name("channel-1"), equal_to("ops-alerts"))


@patch("api.infrastructure.discord.client.resilient_request")
def test_discord_client_identifies_its_rest_requests_to_discord(mock_request):
    response = MagicMock(status_code=200)
    response.json.return_value = {"id": "bot-1", "username": "agentbarn"}
    mock_request.return_value = response

    DiscordClient("discord-token").get_current_bot()

    assert_that(
        mock_request.call_args.kwargs["headers"],
        equal_to({"Authorization": "Bot discord-token", "User-Agent": "AgentBarn/1.0"}),
    )


@patch("api.infrastructure.discord.client.cached", side_effect=lambda _key, fetch, ttl: fetch())
@patch("api.infrastructure.discord.client.resilient_request")
def test_discord_client_returns_none_when_resource_is_not_visible(mock_request, _mock_cached):
    mock_request.return_value = MagicMock(status_code=403)
    client = DiscordClient("discord-token")

    assert_that(client.get_channel_display_name("channel-1"), none())


@patch("api.infrastructure.discord.client.cached", side_effect=lambda _key, fetch, ttl: fetch())
@patch("api.infrastructure.discord.client.resilient_request")
def test_discord_client_raises_instead_of_hiding_a_forbidden_member_list(mock_request, _mock_cached):
    """A 403 (e.g. Server Members Intent disabled) must propagate, not collapse to [].

    Directory results are cached for 10 minutes: silently returning [] here would
    look identical to a guild with no members and get cached as if it were correct,
    leaving the "Allowed users" picker empty with no way to tell why.
    """
    response = MagicMock(status_code=403)
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Forbidden", request=MagicMock(), response=MagicMock(status_code=403)
    )
    mock_request.return_value = response
    client = DiscordClient("discord-token")

    assert_that(calling(client.list_guild_members).with_args("guild-1"), raises(httpx.HTTPStatusError))


@patch("api.infrastructure.discord.client.cached", side_effect=lambda _key, fetch, ttl: fetch())
@patch("api.infrastructure.discord.client.resilient_request")
def test_discord_client_lists_a_guild_directory(mock_request, _mock_cached):
    def response(body):
        value = MagicMock(status_code=200)
        value.json.return_value = body
        return value

    mock_request.side_effect = [
        response([{"id": "guild-1", "name": "Community"}]),
        response([{"id": "channel-1", "name": "general", "type": 0}, {"id": "voice-1", "name": "Voice", "type": 2}]),
        response([{"user": {"id": "user-1", "username": "aria"}, "nick": "Aria"}]),
        response([{"id": "guild-1", "name": "@everyone"}, {"id": "role-1", "name": "Maintainer"}]),
    ]
    client = DiscordClient("discord-token")

    assert_that(client.list_guilds(), equal_to([{"id": "guild-1", "name": "Community"}]))
    assert_that(client.list_guild_channels("guild-1"), equal_to([{"id": "channel-1", "name": "general"}]))
    assert_that(client.list_guild_members("guild-1"), equal_to([{"id": "user-1", "name": "Aria"}]))
    assert_that(client.list_guild_roles("guild-1"), equal_to([{"id": "role-1", "name": "Maintainer"}]))


@patch("api.infrastructure.discord.client.resilient_request")
def test_discord_client_cache_does_not_cross_contaminate_different_tokens(mock_request):
    """Two bots resolving the same Discord user ID must not share a cached
    name — a shared key would leak one Connection's directory into another.
    """
    clear_cache()
    try:
        response_one = MagicMock(status_code=200)
        response_one.json.return_value = {"id": "user-1", "global_name": "Bot One's Alice"}
        response_two = MagicMock(status_code=200)
        response_two.json.return_value = {"id": "user-1", "global_name": "Bot Two's Alice"}
        mock_request.side_effect = [response_one, response_two]

        first = DiscordClient("token-one").get_user_display_name("user-1")
        second = DiscordClient("token-two").get_user_display_name("user-1")

        assert_that(first, equal_to("Bot One's Alice"))
        assert_that(second, equal_to("Bot Two's Alice"))
    finally:
        clear_cache()


@patch("api.infrastructure.discord.client.resilient_request")
def test_discord_client_carries_the_provider_idempotency_key(mock_request):
    response = MagicMock(status_code=200)
    response.json.return_value = {"id": "message-1"}
    mock_request.return_value = response

    provider_key = provider_idempotency_key("delivery-1")

    message_id = DiscordClient("bot-value").send_message(
        "channel-1",
        "reply",
        idempotency_key=provider_key,
    )

    assert_that(message_id, equal_to("message-1"))
    payload = json.loads(mock_request.call_args.kwargs["content"])
    # Discord caps the nonce at 25 characters and answers 400/50035 above that.
    assert_that(payload["nonce"], equal_to(provider_key[:25]))
    assert_that(len(payload["nonce"]), equal_to(25))
    assert_that(payload["enforce_nonce"], equal_to(True))


@patch("api.infrastructure.discord.client.resilient_request")
def test_discord_client_sends_components_only_when_a_message_has_them(mock_request):
    response = MagicMock(status_code=200)
    response.json.return_value = {"id": "message-1"}
    mock_request.return_value = response
    buttons = [{"type": 1, "components": [{"type": 2, "style": 2, "label": "Allow once", "custom_id": "value-1"}]}]

    DiscordClient("bot-value").send_message("channel-1", "reply")
    plain = json.loads(mock_request.call_args.kwargs["content"])

    DiscordClient("bot-value").send_message("channel-1", "approval", components=buttons)
    with_buttons = json.loads(mock_request.call_args.kwargs["content"])

    assert_that("components" in plain, equal_to(False))
    assert_that(with_buttons["components"], equal_to(buttons))


@patch("api.infrastructure.discord.client.resilient_request")
def test_discord_client_sends_a_short_reply_as_one_unchanged_request(mock_request):
    response = MagicMock(status_code=200)
    response.json.return_value = {"id": "message-1"}
    mock_request.return_value = response

    provider_key = provider_idempotency_key("delivery-1")

    message_id = DiscordClient("bot-value").send_message(
        "channel-1",
        "reply",
        reply_to_id="origin-1",
        idempotency_key=provider_key,
    )

    assert_that(message_id, equal_to("message-1"))
    assert_that(mock_request.call_count, equal_to(1))
    payload = json.loads(mock_request.call_args.kwargs["content"])
    assert_that(payload["content"], equal_to("reply"))
    assert_that(payload["nonce"], equal_to(provider_key[:25]))
    assert_that(payload["enforce_nonce"], equal_to(True))
    assert_that(payload["message_reference"]["message_id"], equal_to("origin-1"))
