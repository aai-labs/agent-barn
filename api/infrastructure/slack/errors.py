class SlackFetchError(Exception):
    """A Slack request failed (transport error, non-ok response, or exhausted retries).

    Raised by the paginating fetchers so partial/empty results are never cached as
    if they were the complete directory, and so callers can surface a clear error
    instead of an empty list that looks like a genuinely empty workspace.
    """


# Human-facing messages for the Slack error codes token validation can return,
# keyed by the `error` field of a non-ok auth.test / apps.connections.open response.
BOT_TOKEN_ERRORS: dict[str, str] = {
    "invalid_auth": "Slack bot token is invalid. Check the token in your Slack app settings.",
    "token_revoked": "Slack bot token has been revoked. Generate a new one in your Slack app settings.",
    "account_inactive": "The Slack account linked to this bot token is inactive.",
    "not_authed": "No Slack bot token was provided.",
    "org_login_required": "This workspace requires enterprise authentication.",
    "ekm_access_denied": "Access denied by your organisation's key management settings.",
}

APP_TOKEN_ERRORS: dict[str, str] = {
    "invalid_auth": "Slack app token is invalid. Check the token in your Slack app settings.",
    "token_revoked": "Slack app token has been revoked. Generate a new one in your Slack app settings.",
    "missing_scope": "Slack app token is missing the 'connections:write' scope. Add it in your Slack app configuration.",
    "not_authed": "No Slack app token was provided.",
    "org_login_required": "This workspace requires enterprise authentication.",
}
