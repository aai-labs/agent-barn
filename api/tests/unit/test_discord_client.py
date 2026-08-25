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
