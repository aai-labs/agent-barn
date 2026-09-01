import json
from unittest.mock import MagicMock, patch

from hamcrest import assert_that, equal_to, none

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


@patch("api.infrastructure.discord.client.cached", side_effect=lambda _key, fetch, ttl: fetch())
@patch("api.infrastructure.discord.client.resilient_request")
def test_discord_client_returns_none_when_resource_is_not_visible(mock_request, _mock_cached):
    mock_request.return_value = MagicMock(status_code=403)
    client = DiscordClient("discord-token")

    assert_that(client.get_channel_display_name("channel-1"), none())


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

    message_id = DiscordClient("bot-value").send_message(
        "channel-1",
        "reply",
        idempotency_key="provider-key",
    )

    assert_that(message_id, equal_to("message-1"))
    payload = json.loads(mock_request.call_args.kwargs["content"])
    assert_that(payload["nonce"], equal_to("provider-key"))
    assert_that(payload["enforce_nonce"], equal_to(True))
