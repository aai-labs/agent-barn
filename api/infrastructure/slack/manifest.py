"""Least-privilege Slack app manifest for Agent Barn Communication Connections."""

BOT_SCOPES: list[str] = [
    "channels:history",
    "channels:read",
    "chat:write",
    "groups:history",
    "groups:read",
    "im:history",
    "im:read",
    "mpim:history",
    "mpim:read",
    "reactions:write",
    "users:read",
]

BOT_EVENTS: list[str] = [
    "message.channels",
    "message.groups",
    "message.im",
    "message.mpim",
]


def build_slack_app_manifest(
    name: str = "Agent Barn",
    description: str = "Connect an Agent Barn agent to Slack.",
    background_color: str = "#4A154B",
) -> dict:
    """Build an importable manifest for the Slack behavior we ship today.

    Socket Mode's app-level token is intentionally absent: Slack requires an
    operator to create it after import, with ``connections:write``.
    """
    return {
        "display_information": {
            "name": name,
            "description": description,
            "background_color": background_color,
        },
        "features": {
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
            "org_deploy_enabled": False,
            "socket_mode_enabled": True,
            "token_rotation_enabled": False,
        },
    }
