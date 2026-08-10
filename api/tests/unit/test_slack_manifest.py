from api.infrastructure.slack.manifest import build_slack_app_manifest


def test_build_manifest_contains_expanded_scopes():
    manifest = build_slack_app_manifest("TestBot", "A test bot")
    scopes = manifest["oauth_config"]["scopes"]["bot"]

    for scope in [
        "files:write",
        "canvases:read",
        "pins:write",
        "reactions:read",
        "search:read.users",
        "bookmarks:read",
    ]:
        assert scope in scopes


def test_build_manifest_contains_expanded_events():
    manifest = build_slack_app_manifest("TestBot", "A test bot")
    events = manifest["settings"]["event_subscriptions"]["bot_events"]

    for event in [
        "channel_rename",
        "pin_added",
        "reaction_added",
        "member_joined_channel",
    ]:
        assert event in events


def test_build_manifest_socket_mode_enabled():
    manifest = build_slack_app_manifest("TestBot", "A test bot")

    assert manifest["settings"]["socket_mode_enabled"] is True
