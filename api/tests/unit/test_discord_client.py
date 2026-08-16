from unittest.mock import MagicMock, patch

from hamcrest import assert_that, equal_to, none

from api.infrastructure.discord.client import DiscordClient


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
