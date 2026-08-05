BOT_SCOPES: list[str] = [
    "app_mentions:read",
    "bookmarks:read",
    "canvases:read",
    "canvases:write",
    "channels:history",
    "channels:join",
    "channels:read",
    "chat:write",
    "chat:write.customize",
    "chat:write.public",
    "emoji:read",
    "files:read",
    "files:write",
    "groups:history",
    "groups:read",
    "im:history",
    "im:read",
    "im:write",
    "mpim:history",
    "mpim:read",
    "mpim:write",
    "pins:read",
    "pins:write",
    "reactions:read",
    "reactions:write",
    "search:read.users",
    "users:read",
    "users:read.email",
]

BOT_EVENTS: list[str] = [
    "app_mention",
    "channel_rename",
    "member_joined_channel",
    "member_left_channel",
    "message.channels",
    "message.groups",
    "message.im",
    "message.mpim",
    "pin_added",
    "pin_removed",
    "reaction_added",
    "reaction_removed",
]


def build_slack_app_manifest(
    name: str,
    description: str,
    background_color: str = "#4A154B",
) -> dict:
    return {
        "display_information": {
            "name": name,
            "description": description,
            "background_color": background_color,
        },
        "features": {
            "app_home": {
                "home_tab_enabled": False,
                "messages_tab_enabled": True,
                "messages_tab_read_only_enabled": False,
            },
            "bot_user": {
                "display_name": name,
                "always_online": True,
            },
        },
        "oauth_config": {
            "scopes": {"bot": list(BOT_SCOPES)},
            "pkce_enabled": False,
        },
        "settings": {
            "event_subscriptions": {"bot_events": list(BOT_EVENTS)},
            "interactivity": {"is_enabled": True},
            "org_deploy_enabled": False,
            "socket_mode_enabled": True,
            "token_rotation_enabled": False,
            "is_mcp_enabled": False,
        },
    }
