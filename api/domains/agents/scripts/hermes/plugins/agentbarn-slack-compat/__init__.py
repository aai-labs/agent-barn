"""Run the native Slack adapter against a Slack-compatible server such as Slawk.

Hermes' Slack adapter and the Slack SDK call ``https://slack.com/api/<method>``
and have no setting to change that. This plugin sends every such call that
carries this Connection's bot or app token to ``AGENTBARN_SLACK_COMPAT_API_URL``
instead. Socket Mode follows, because ``apps.connections.open`` returns the
server's own ``wss://`` URL. Calls with any other token are left alone, so a
real Slack app in the same process keeps talking to Slack.

File downloads attach the bot token, so the adapter only downloads from Slack's
CDN hosts. The server's host is allowed too, and downloads from it always use
this Connection's bot token, never another workspace's.
"""

import os
from functools import wraps
from urllib.parse import urlparse

_SLACK_API = "https://slack.com/api/"


def _bearer(headers):
    if not headers:
        return ""
    items = headers.items() if hasattr(headers, "items") else headers
    for key, value in items:
        if str(key).lower() == "authorization":
            return str(value).removeprefix("Bearer ").strip()
    return ""


# The pinned-image hermes_slack_compat_driver.py contract guards these private
# Hermes and aiohttp APIs; run it whenever updating the Hermes image.
def register(ctx):
    import aiohttp
    from plugins.platforms.slack.adapter import SlackAdapter  # ty: ignore[unresolved-import]

    api_url = os.environ.get("AGENTBARN_SLACK_COMPAT_API_URL", "").strip()
    bot_token = os.environ.get("AGENTBARN_SLACK_COMPAT_BOT_TOKEN", "").strip()
    app_token = os.environ.get("AGENTBARN_SLACK_COMPAT_APP_TOKEN", "").strip()
    if not (api_url and bot_token and app_token):
        raise RuntimeError("agentbarn-slack-compat needs AGENTBARN_SLACK_COMPAT_API_URL, _BOT_TOKEN and _APP_TOKEN")
    if not api_url.endswith("/"):
        api_url += "/"
    parsed = urlparse(api_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RuntimeError("AGENTBARN_SLACK_COMPAT_API_URL must be an https URL")
    host = parsed.hostname.lower()
    tokens = {bot_token, app_token}

    request = aiohttp.ClientSession._request

    @wraps(request)
    def route(session, method, str_or_url, *args, **kwargs):
        url = str(str_or_url)
        if url.startswith(_SLACK_API) and _bearer(kwargs.get("headers")) in tokens:
            str_or_url = api_url + url[len(_SLACK_API) :]
        return request(session, method, str_or_url, *args, **kwargs)

    aiohttp.ClientSession._request = route  # ty: ignore[invalid-assignment]

    cdn_hosts = SlackAdapter._SLACK_CDN_EXACT_HOSTS
    SlackAdapter._SLACK_CDN_EXACT_HOSTS = cdn_hosts | {host}

    download_token = SlackAdapter._resolve_download_token

    @wraps(download_token)
    def resolve_download_token(adapter, url, team_id=""):
        if (urlparse(url).hostname or "").lower().rstrip(".") == host:
            return bot_token
        return download_token(adapter, url, team_id)

    SlackAdapter._resolve_download_token = resolve_download_token

    def restore():
        if aiohttp.ClientSession._request is route:
            aiohttp.ClientSession._request = request
        SlackAdapter._SLACK_CDN_EXACT_HOSTS = cdn_hosts
        if SlackAdapter._resolve_download_token is resolve_download_token:
            SlackAdapter._resolve_download_token = download_token

    ctx.on_unload(restore)
