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

from hamcrest import assert_that, contains_string, empty, equal_to, has_key, has_length, is_

from api.domains.ingest.models import IngestBatchRequest
from api.tests.core.givenpy import given, then, when

_PLUGIN_DIR = (
    Path(__file__).parent.parent.parent / "domains" / "agents" / "scripts" / "openclaw" / "plugins" / "telemetry-push"
)
_DRIVER = Path(__file__).parent.parent / "fixtures" / "openclaw_telemetry_driver.mjs"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _CollectorServer(HTTPServer):
    """Collects the batches the plugin posts, so tests assert on the wire format."""

    payloads: list[dict]


class _IngestCollector(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        server = cast(_CollectorServer, self.server)
        server.payloads.append(json.loads(self.rfile.read(length)))
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass


def _run_driver(steps, timeout=20):
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is required to exercise the OpenClaw plugin")

    server = _CollectorServer(("127.0.0.1", _free_port()), _IngestCollector)
    server.payloads = []
    threading.Thread(target=server.serve_forever, daemon=True).start()

    fd, steps_path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(steps, f)

    env = {
        **os.environ,
        "AGENT_ID": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "INGEST_URL": f"http://127.0.0.1:{server.server_port}",
        "INGEST_API_KEY": "test-key-123",
    }
    proc = subprocess.Popen(
        [node, str(_DRIVER), str(_PLUGIN_DIR / "index.js"), steps_path],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + timeout
        while not server.payloads and time.monotonic() < deadline:
            if proc.poll() is not None and proc.returncode != 0:
                stderr = proc.stderr.read() if proc.stderr else ""
                raise AssertionError(f"driver exited {proc.returncode}: {stderr}")
            time.sleep(0.05)
        time.sleep(0.3)  # let any straggling flush arrive
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        server.shutdown()
        server.server_close()
        os.unlink(steps_path)

    merged = {"messages": [], "tool_calls": [], "tool_results": []}
    for payload in server.payloads:
        for key, collected in merged.items():
            collected.extend(payload.get(key) or [])
    return merged


def _inbound(conversation_id):
    return {
        "hook": "message_received",
        "event": {"content": f"from {conversation_id}", "senderId": "U1"},
        "ctx": {"conversationId": conversation_id, "sessionKey": f"sess-{conversation_id}"},
    }


def _agent_end(session_key, reply, channel_id=None):
    return {
        "hook": "agent_end",
        "event": {"messages": [{"role": "assistant", "content": reply}]},
        "ctx": {"sessionKey": session_key, "trigger": "user", "channelId": channel_id or ""},
    }


_SESSION_END = {"hook": "session_end", "event": {}, "ctx": {}}


def _outbound(payload):
    return [m for m in payload["messages"] if m["direction"] == "OUTBOUND"]


def test_plugin_index_js_exists():
    with given():
        with when("I check for the plugin entry point"):
            exists = (_PLUGIN_DIR / "index.js").exists()

        with then("the file exists"):
            assert_that(exists, equal_to(True))


def test_plugin_package_json_is_valid():
    with given():
        raw = (_PLUGIN_DIR / "package.json").read_text()

        with when("I parse package.json"):
            pkg = json.loads(raw)

        with then("it has the expected fields"):
            assert_that(pkg["name"], equal_to("telemetry-push"))
            assert_that(pkg["type"], equal_to("module"))


def test_plugin_openclaw_plugin_json_is_valid():
    with given():
        raw = (_PLUGIN_DIR / "openclaw.plugin.json").read_text()

        with when("I parse openclaw.plugin.json"):
            meta = json.loads(raw)

        with then("it has the expected id and activation"):
            assert_that(meta["id"], equal_to("telemetry-push"))
            assert_that(meta["activation"]["onStartup"], equal_to(True))


def test_index_js_reads_env_vars():
    with given():
        source = (_PLUGIN_DIR / "index.js").read_text()

        with when("I inspect the plugin source"):
            pass

        with then("it reads AGENT_ID, INGEST_URL, and INGEST_API_KEY"):
            assert_that(source, contains_string("AGENT_ID"))
            assert_that(source, contains_string("INGEST_URL"))
            assert_that(source, contains_string("INGEST_API_KEY"))


def test_index_js_registers_hooks():
    with given():
        source = (_PLUGIN_DIR / "index.js").read_text()

        with when("I inspect the plugin source"):
            pass

        with then("it registers message and tool call hooks"):
            assert_that(source, contains_string("message_received"))
            assert_that(source, contains_string("agent_end"))
            assert_that(source, contains_string("before_tool_call"))
            assert_that(source, contains_string("after_tool_call"))
            assert_that(source, contains_string("session_end"))


def test_overlay_includes_telemetry_push_in_plugins():
    with given():
        from api.domains.agents.builders import build_openclaw_config_overlay

        with when("I build a Slack overlay"):
            overlay = build_openclaw_config_overlay("litellm/qwen3", "http://x:4000")

        with then("telemetry-push is in the plugins allow list and entries"):
            assert_that("telemetry-push" in overlay["plugins"]["allow"], equal_to(True))
            assert_that(overlay["plugins"]["entries"], has_key("telemetry-push"))
            assert_that(
                overlay["plugins"]["entries"]["telemetry-push"]["enabled"],
                equal_to(True),
            )


def test_teams_overlay_includes_telemetry_push_in_plugins():
    with given():
        from api.domains.agents.builders import build_openclaw_config_overlay_teams

        with when("I build a Teams overlay"):
            overlay = build_openclaw_config_overlay_teams("litellm/qwen3", "http://x:4000")

        with then("telemetry-push is in the plugins allow list and entries"):
            assert_that("telemetry-push" in overlay["plugins"]["allow"], equal_to(True))
            assert_that(overlay["plugins"]["entries"], has_key("telemetry-push"))


def test_config_map_includes_telemetry_push_files():
    with given():
        from api.domains.agents.builders import build_config_map

        with when("I build an OpenClaw config map"):
            cm = build_config_map(
                agent_id=__import__("uuid").UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
                org_id=__import__("uuid").UUID("11111111-2222-3333-4444-555555555555"),
                namespace="agent-farm",
                soul_md="# Soul",
                identity_md="# Identity",
                user_md="# User",
                tools_md="# Tools",
                agents_md="# Agents",
                boot_md="# Boot",
                bootstrap_md="# Bootstrap",
                heartbeat_md="# Heartbeat",
                openclaw_config_overlay={"plugins": {}},
            )

        with then("the config map has telemetry-push plugin files"):
            assert_that(cm.data, has_key("telemetry-push-index.js"))
            assert_that(cm.data, has_key("telemetry-push-package.json"))
            assert_that(cm.data, has_key("telemetry-push-plugin.json"))


def test_start_sh_installs_telemetry_push():
    with given():
        from api.domains.agents.builders import START_SH

        with when("I inspect the OpenClaw start.sh"):
            pass

        with then("it copies and installs the telemetry-push plugin"):
            assert_that(START_SH, contains_string("telemetry-push"))


# --- chat attribution ---


def test_outbound_goes_to_its_own_chat_when_another_chat_messaged_meanwhile():
    with given():
        # agent_end deliberately carries chat B's channelId: the reply must be
        # attributed from the correlated inbound record, not from that field.
        steps = [
            _inbound("c_aaa"),
            _inbound("c_bbb"),
            _agent_end("sess-c_aaa", "reply for A", channel_id="c_bbb"),
            _SESSION_END,
        ]

        with when("chat A's turn ends after chat B's message arrived"):
            payload = _run_driver(steps)

        with then("the reply is attributed to chat A"):
            outbound = _outbound(payload)
            assert_that(outbound, has_length(1))
            assert_that(outbound[0]["channel_id"], equal_to("C_AAA"))
            assert_that(outbound[0]["session_key"], equal_to("sess-c_aaa"))
            assert_that(outbound[0]["content"], equal_to("reply for A"))


def test_each_concurrent_chat_gets_its_own_reply():
    with given():
        steps = [
            _inbound("c_aaa"),
            _inbound("c_bbb"),
            _agent_end("sess-c_bbb", "reply for B"),
            _agent_end("sess-c_aaa", "reply for A"),
            _SESSION_END,
        ]

        with when("both turns end out of arrival order"):
            payload = _run_driver(steps)

        with then("each reply carries its own chat"):
            by_channel = {m["channel_id"]: m["content"] for m in _outbound(payload)}
            assert_that(by_channel, equal_to({"C_BBB": "reply for B", "C_AAA": "reply for A"}))


def test_outbound_is_dropped_when_session_is_unknown():
    with given():
        steps = [
            _inbound("c_aaa"),
            _agent_end("sess-unknown", "reply with no inbound"),
            _SESSION_END,
        ]

        with when("a turn ends for a session that never sent a message"):
            payload = _run_driver(steps)

        with then("nothing is recorded rather than guessing a chat"):
            assert_that(_outbound(payload), is_(empty()))


def test_inbound_and_outbound_agree_on_channel_id():
    with given():
        steps = [_inbound("c_aaa"), _agent_end("sess-c_aaa", "reply for A"), _SESSION_END]

        with when("a single chat completes a turn"):
            payload = _run_driver(steps)

        with then("both directions group under the same channel"):
            channels = {m["channel_id"] for m in payload["messages"]}
            assert_that(channels, equal_to({"C_AAA"}))


# --- tool calls ---


def test_tool_call_and_result_share_an_external_id():
    with given():
        steps = [
            {
                "hook": "before_tool_call",
                "event": {"toolName": "bash", "params": {"cmd": "ls"}, "runId": "run-1"},
                "ctx": {},
            },
            {
                "hook": "after_tool_call",
                "event": {"toolName": "bash", "params": {"cmd": "ls"}, "runId": "run-1", "result": "ok"},
                "ctx": {},
            },
            _SESSION_END,
        ]

        with when("a tool call completes without the runtime supplying a call id"):
            payload = _run_driver(steps)

        with then("the result is bound to the id minted for its own call"):
            assert_that(payload["tool_calls"], has_length(1))
            assert_that(payload["tool_results"], has_length(1))
            assert_that(
                payload["tool_results"][0]["external_id"],
                equal_to(payload["tool_calls"][0]["external_id"]),
            )


def test_concurrent_calls_to_the_same_tool_keep_distinct_results():
    with given():
        steps = [
            {
                "hook": "before_tool_call",
                "event": {"toolName": "bash", "params": {"cmd": "ls"}, "toolCallId": "call-1"},
                "ctx": {},
            },
            {
                "hook": "before_tool_call",
                "event": {"toolName": "bash", "params": {"cmd": "pwd"}, "toolCallId": "call-2"},
                "ctx": {},
            },
            {
                "hook": "after_tool_call",
                "event": {"toolName": "bash", "params": {"cmd": "pwd"}, "toolCallId": "call-2", "result": "/root"},
                "ctx": {},
            },
            {
                "hook": "after_tool_call",
                "event": {"toolName": "bash", "params": {"cmd": "ls"}, "toolCallId": "call-1", "result": "file1"},
                "ctx": {},
            },
            _SESSION_END,
        ]

        with when("two calls to the same tool overlap"):
            payload = _run_driver(steps)

        with then("each result is bound to the external id of its own call"):
            calls = {c["arguments"]["cmd"]: c["external_id"] for c in payload["tool_calls"]}
            results = {r["external_id"]: r["result"] for r in payload["tool_results"]}
            assert_that(results[calls["ls"]], equal_to("file1"))
            assert_that(results[calls["pwd"]], equal_to("/root"))


# --- ingest contract ---


def test_posted_payload_satisfies_the_ingest_contract():
    with given():
        steps = [
            _inbound("c_aaa"),
            _agent_end("sess-c_aaa", "reply for A"),
            {
                "hook": "before_tool_call",
                "event": {"toolName": "bash", "params": {"cmd": "ls"}, "toolCallId": "call-1"},
                "ctx": {},
            },
            {
                "hook": "after_tool_call",
                "event": {"toolName": "bash", "params": {"cmd": "ls"}, "toolCallId": "call-1", "result": "ok"},
                "ctx": {},
            },
            _SESSION_END,
        ]

        with when("the plugin posts its batch"):
            payload = _run_driver(steps)

        with then("Ingest accepts it without coercion errors"):
            batch = IngestBatchRequest.model_validate(payload)
            assert_that(batch.messages, has_length(2))
            assert_that(batch.tool_calls, has_length(1))
            assert_that(batch.tool_results, has_length(1))
