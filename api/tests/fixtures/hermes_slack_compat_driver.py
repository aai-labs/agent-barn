"""Prove agentbarn-slack-compat routes Slack calls in the pinned Hermes image.

Runs inside the image with the plugin mounted at /plugin. Every outbound
aiohttp request is captured instead of sent, so the driver needs no network.
Hermes' own Slack SDK, adapter helpers and standalone sender issue the calls,
so an upgrade that moves them off aiohttp or renames a patched API fails here.
"""

import asyncio
import importlib.util
import os
import sys
import tempfile
from typing import NoReturn
from unittest.mock import MagicMock

os.environ["HERMES_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, "/opt/hermes")

API = "https://chat.example.test/slack/api/"
BOT = "xoxb-compat"
APP = "xapp-compat"
SLACK_BOT = "xoxb-real-slack"
os.environ.update(
    AGENTBARN_SLACK_COMPAT_API_URL=API.rstrip("/"),
    AGENTBARN_SLACK_COMPAT_BOT_TOKEN=BOT,
    AGENTBARN_SLACK_COMPAT_APP_TOKEN=APP,
)

import aiohttp
import plugins.platforms.slack.adapter as slack  # ty: ignore[unresolved-import]
from slack_sdk.web.async_client import AsyncWebClient  # ty: ignore[unresolved-import]


def fail(message) -> NoReturn:
    raise SystemExit("slack compat contract broken: " + message)


class Captured(Exception):
    pass


sent = []


def capture(session, method, str_or_url, *args, **kwargs):
    sent.append(str(str_or_url))
    raise Captured


aiohttp.ClientSession._request = capture

spec = importlib.util.spec_from_file_location("agentbarn_slack_compat", "/plugin/__init__.py")
if spec is None or spec.loader is None:
    fail("could not load the plugin")
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)
ctx = MagicMock()
plugin.register(ctx)


async def last_url(call):
    sent.clear()
    try:
        await call
    except Captured:
        pass
    if not sent:
        fail("no request was made")
    return sent[-1]


async def main():
    cases = [
        ("bot token Web API", AsyncWebClient(token=BOT).auth_test(), API + "auth.test"),
        (
            "Socket Mode handshake",
            AsyncWebClient(token=BOT).apps_connections_open(app_token=APP),
            API + "apps.connections.open",
        ),
        ("other Slack app", AsyncWebClient(token=SLACK_BOT).auth_test(), "https://slack.com/api/auth.test"),
        (
            "standalone DM lookup",
            slack._resolve_slack_user_dm(BOT, "U1"),
            API + "conversations.open",
        ),
        (
            "standalone text send",
            slack._standalone_send(MagicMock(token=BOT), "C1", "hello"),
            API + "chat.postMessage",
        ),
    ]
    for label, call, expected in cases:
        url = await last_url(call)
        if url != expected:
            fail(f"{label} went to {url}, expected {expected}")


asyncio.run(main())

adapter = slack.SlackAdapter
if not adapter._is_slack_cdn_url("https://chat.example.test/files/F1/download"):
    fail("the server's file URLs are refused")
if adapter._is_slack_cdn_url("https://evil.example.test/files/F1/download"):
    fail("an unrelated host became a trusted file host")
if not adapter._is_slack_cdn_url("https://files.slack.com/files-pri/T1-F1/x"):
    fail("Slack's own CDN is no longer trusted")

instance = adapter.__new__(adapter)
instance._team_clients = {"T1": MagicMock(token=SLACK_BOT)}
instance.config = MagicMock(token=SLACK_BOT)
if instance._resolve_download_token("https://chat.example.test/files/F1/download", "T1") != BOT:
    fail("a download from the server would carry another workspace's token")
if instance._resolve_download_token("https://files.slack.com/files-pri/T1-F1/x", "T1") != SLACK_BOT:
    fail("Slack downloads lost their workspace token")

restore = ctx.on_unload.call_args.args[0]
restore()
if aiohttp.ClientSession._request is not capture or "chat.example.test" in adapter._SLACK_CDN_EXACT_HOSTS:
    fail("unloading the plugin did not restore Hermes")

print("hermes slack compat contract ok")
