"""Scope Slack authorization to the Connection's channel or DM policy.

Hermes' native user allowlist covers both channels and DMs. Its dispatch hooks
run too late to protect attachment fetches, so enforce the Connection policy
at the authorization seam shared by adapter intake and the gateway runner.
"""

from functools import wraps


def register(ctx):
    from gateway.authz_mixin import GatewayAuthorizationMixin, _auth_env  # ty: ignore[unresolved-import]

    original = GatewayAuthorizationMixin._is_user_authorized

    @wraps(original)
    def authorize(self, source, **kwargs):
        if getattr(source.platform, "value", source.platform) != "slack":
            return original(self, source, **kwargs)
        if not source.user_id:
            return False
        if source.chat_type == "dm":
            policy = _auth_env("AGENTBARN_SLACK_DM_POLICY", "off")
            allowed = _auth_env("AGENTBARN_SLACK_DM_ALLOWED_USERS")
            identity = source.user_id
        elif source.chat_type in {"group", "channel", "forum"}:
            policy = _auth_env("AGENTBARN_SLACK_GROUP_POLICY", "allowlist")
            allowed = _auth_env("SLACK_ALLOWED_CHANNELS")
            identity = source.chat_id
        else:
            return False
        if policy == "open":
            return True
        return policy == "allowlist" and identity in {item.strip() for item in allowed.split(",") if item.strip()}

    GatewayAuthorizationMixin._is_user_authorized = authorize

    def restore():
        if GatewayAuthorizationMixin._is_user_authorized is authorize:
            GatewayAuthorizationMixin._is_user_authorized = original

    ctx.on_unload(restore)
