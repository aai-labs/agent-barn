"""Scope Slack authorization to the Connection's channel or DM policy.

Hermes' native user allowlist covers both channels and DMs. Its dispatch hooks
run too late to protect attachment fetches, so enforce the Connection policy
at the authorization seam shared by adapter intake and the gateway runner.
"""

from functools import wraps


# The pinned-image hermes_slack_access_driver.py contract guards these private
# Hermes APIs; run it whenever updating the Hermes image.
def register(ctx):
    from gateway.authz_mixin import GatewayAuthorizationMixin, _auth_env  # ty: ignore[unresolved-import]
    from plugins.platforms.slack.adapter import SlackAdapter  # ty: ignore[unresolved-import]

    original = GatewayAuthorizationMixin._is_user_authorized
    private_channels = set()

    async def supported_location(adapter, channel_id, team_id=""):
        # Legacy private channels and group DMs both have G-prefixed IDs.
        # Resolve provider metadata before admission; never infer the kind from G.
        if not channel_id.startswith("G"):
            return channel_id.startswith(("C", "D"))
        if channel_id in private_channels:
            return True
        try:
            result = await adapter._get_client(channel_id, team_id=team_id).conversations_info(channel=channel_id)
            channel = result.get("channel", {})
            if (
                result.get("ok")
                and channel.get("is_mpim") is False
                and (channel.get("is_group") or channel.get("is_channel"))
            ):
                private_channels.add(channel_id)
                return True
        except Exception:
            pass
        return False

    @wraps(original)
    def authorize(self, source, **kwargs):
        if getattr(source.platform, "value", source.platform) != "slack":
            return original(self, source, **kwargs)
        if not source.user_id:
            return False
        if source.chat_type == "dm":
            if not source.chat_id.startswith("D"):
                return False
            policy = _auth_env("AGENTBARN_SLACK_DM_POLICY", "off")
            allowed = _auth_env("AGENTBARN_SLACK_DM_ALLOWED_USERS")
            identity = source.user_id
        elif source.chat_type in {"group", "channel", "forum", "thread"}:
            if not (source.chat_id.startswith("C") or source.chat_id in private_channels):
                return False
            policy = _auth_env("AGENTBARN_SLACK_GROUP_POLICY", "allowlist")
            allowed = _auth_env("SLACK_ALLOWED_CHANNELS")
            identity = source.chat_id
        else:
            return False
        if policy == "open":
            return True
        return policy == "allowlist" and identity in {item.strip() for item in allowed.split(",") if item.strip()}

    GatewayAuthorizationMixin._is_user_authorized = authorize

    intake = SlackAdapter._handle_slack_message

    @wraps(intake)
    async def receive(adapter, event, payload=None):
        if event.get("channel_type") == "mpim":
            return
        if not await supported_location(adapter, event.get("channel", ""), adapter._event_team_id(event, payload)):
            return
        return await intake(adapter, event, payload)

    SlackAdapter._handle_slack_message = receive
    actions = {}

    def guard_action(handler):
        @wraps(handler)
        async def handle(adapter, ack, body, action):
            await ack()
            channel_id = (body.get("channel") or {}).get("id", "")
            if not await supported_location(adapter, channel_id, adapter._event_team_id({}, body)):
                return

            async def acknowledged():
                pass

            return await handler(adapter, acknowledged, body, action)

        return handle

    for name in ("_handle_approval_action", "_handle_slash_confirm_action", "_handle_clarify_action"):
        handler = getattr(SlackAdapter, name)
        guarded = guard_action(handler)
        actions[name] = (handler, guarded)
        setattr(SlackAdapter, name, guarded)

    def restore():
        if GatewayAuthorizationMixin._is_user_authorized is authorize:
            GatewayAuthorizationMixin._is_user_authorized = original
        if SlackAdapter._handle_slack_message is receive:
            SlackAdapter._handle_slack_message = intake
        for name, (handler, guarded) in actions.items():
            if getattr(SlackAdapter, name) is guarded:
                setattr(SlackAdapter, name, handler)

    ctx.on_unload(restore)
