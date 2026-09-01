from api.infrastructure.slack.manifest import BOT_EVENTS, BOT_SCOPES, build_slack_app_manifest


def test_build_manifest_contains_only_connection_scopes():
    manifest = build_slack_app_manifest("TestBot", "A test bot")

    assert manifest["oauth_config"]["scopes"]["bot"] == BOT_SCOPES
    assert "chat:write" in BOT_SCOPES
    assert "reactions:write" in BOT_SCOPES
    assert "files:write" not in BOT_SCOPES
    assert "app_mentions:read" not in BOT_SCOPES


def test_build_manifest_contains_only_consumed_message_events():
    manifest = build_slack_app_manifest("TestBot", "A test bot")

    assert manifest["settings"]["event_subscriptions"]["bot_events"] == BOT_EVENTS
    assert BOT_EVENTS == ["message.channels", "message.groups", "message.im", "message.mpim"]


def test_build_manifest_enables_socket_mode_without_an_app_token():
    manifest = build_slack_app_manifest("TestBot", "A test bot")

    assert manifest["settings"]["socket_mode_enabled"] is True
    assert "connections:write" not in str(manifest)
