from unittest.mock import MagicMock, patch

import httpx
from hamcrest import assert_that, calling, equal_to, raises

from api.infrastructure.discord.client import DiscordClient
from api.infrastructure.shared.cache import clear_cache


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
    """Two bots querying guild directories must not share cached
    names — a shared key would leak one Connection's directory into another.
    """
    clear_cache()
    try:
        response_one = MagicMock(status_code=200)
        response_one.json.return_value = [{"id": "guild-1", "name": "Bot One server"}]
        response_two = MagicMock(status_code=200)
        response_two.json.return_value = [{"id": "guild-2", "name": "Bot Two server"}]
        mock_request.side_effect = [response_one, response_two]

        first = DiscordClient("token-one").list_guilds()
        second = DiscordClient("token-two").list_guilds()

        assert_that(first, equal_to([{"id": "guild-1", "name": "Bot One server"}]))
        assert_that(second, equal_to([{"id": "guild-2", "name": "Bot Two server"}]))
    finally:
        clear_cache()
