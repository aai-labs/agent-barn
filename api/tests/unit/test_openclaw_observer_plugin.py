import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, cast

from hamcrest import assert_that, equal_to

from api.domains.ingest.models import IngestCommunicationEventBatch

_PLUGIN = Path(__file__).parents[2] / "domains" / "agents" / "scripts" / "openclaw" / "plugins" / "agentbarn-observer"
_DRIVER = Path(__file__).parents[1] / "fixtures" / "openclaw_telemetry_driver.mjs"


class _Collector(HTTPServer):
    payloads: list[dict]


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        server = cast(_Collector, self.server)
        server.payloads.append(json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)))))
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass


def _run(steps: list[dict], native_channels: str = "slack,discord") -> list[dict]:
    node = shutil.which("node")
    assert node is not None, "node is required to exercise the OpenClaw plugin"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = _Collector(("127.0.0.1", port), _Handler)
    server.payloads = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    fd, steps_path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(steps, f)
    env = {
        **os.environ,
        "AGENT_ID": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "INGEST_URL": f"http://127.0.0.1:{port}",
        "INGEST_API_KEY": "test-key",
        "AGENTBARN_NATIVE_CHANNELS": native_channels,
    }
    proc = subprocess.Popen([node, str(_DRIVER), str(_PLUGIN / "index.js"), steps_path], env=env, text=True)
    try:
        deadline = time.monotonic() + 20
        while not server.payloads and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        server.shutdown()
        server.server_close()
        os.unlink(steps_path)
    return server.payloads


def test_native_channel_turn_reports_content_free_journal_stages() -> None:
    session = {"sessionKey": "agent:main:slack:channel:c1"}
    payloads = _run(
        [
            {
                "hook": "message_received",
                "event": {"content": "secret text", "senderId": "U1", "messageId": "1700.1"},
                "ctx": {"channelId": "slack", "chatId": "c1", **session},
            },
            # Gateway-owned platforms are not the observer's to report.
            {
                "hook": "message_received",
                "event": {"content": "other", "messageId": "9"},
                "ctx": {"channelId": "telegram", "chatId": "9", "sessionKey": "agent:main:telegram:1"},
            },
            {"hook": "before_agent_run", "event": {"prompt": "secret text"}, "ctx": session},
            {"hook": "agent_end", "event": {"success": True, "messages": []}, "ctx": session},
            {
                "hook": "message_sent",
                "event": {"to": "channel:c1", "content": "reply", "messageId": "reply-1", "success": True},
                "ctx": {"channelId": "slack", "chatId": "c1", **session},
            },
            {
                "hook": "message_sent",
                "event": {
                    "to": "channel:c1",
                    "content": "reply",
                    "messageId": "reply-2",
                    "success": False,
                    "error": "provider text",
                },
                "ctx": {"channelId": "slack", "chatId": "c1", **session},
            },
            # A cron run has no inbound message to correlate with.
            {"hook": "agent_end", "event": {"success": True, "messages": []}, "ctx": {"sessionKey": "cron:job"}},
        ]
    )

    events = [event for payload in payloads for event in payload["events"]]
    messages = [message for payload in payloads for message in payload["messages"]]
    batch = IngestCommunicationEventBatch.model_validate({"events": events, "messages": messages})
    assert_that(
        [(e.stage, e.platform, e.correlation_id, e.error_code) for e in batch.events],
        equal_to(
            [
                ("provider_observed", "slack", "slack:1700.1", None),
                ("agent_claimed", "slack", "slack:1700.1", None),
                ("model_completed", "slack", "slack:1700.1", None),
                ("provider_delivered", "slack", "slack:1700.1", None),
                ("provider_delivery_attempted", "slack", "slack:1700.1", "send_failed"),
            ]
        ),
    )
    assert_that(any(text in json.dumps(events) for text in ("secret", "reply", "provider text", "U1")), equal_to(False))
    assert_that(
        [(message.direction, message.content, message.channel_id) for message in batch.messages],
        equal_to(
            [
                ("INBOUND", "secret text", "c1"),
                ("OUTBOUND", "reply", "c1"),
                ("OUTBOUND", "reply", "c1"),
            ]
        ),
    )


def test_openclaw_msteams_events_use_the_product_teams_platform_key() -> None:
    session = {"sessionKey": "agent:main:msteams:conversation:c1"}
    payloads = _run(
        [
            {
                "hook": "message_received",
                "event": {"content": "hello", "messageId": "activity-1", "conversationId": "c1"},
                "ctx": {"channelId": "msteams", "conversationId": "c1", **session},
            },
            {
                "hook": "message_sent",
                "event": {"content": "reply", "messageId": "activity-2", "success": True},
                "ctx": {"channelId": "msteams", "conversationId": "c1", **session},
            },
        ],
        native_channels="msteams",
    )

    events = [event for payload in payloads for event in payload["events"]]
    messages = [message for payload in payloads for message in payload["messages"]]
    assert {event["platform"] for event in events} == {"teams"}
    assert {message["platform"] for message in messages} == {"teams"}
    assert events[0]["correlation_id"] == "teams:activity-1"
