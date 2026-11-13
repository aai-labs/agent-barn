import hashlib
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, cast

import pytest

from api.tests.unit.test_agent_llm_error_proxy import BUDGET_BODY, _proxy, _upstream

SCRIPTS = Path(__file__).resolve().parents[2] / "domains/agents/scripts"
PLUGINS = SCRIPTS / "openclaw/plugins"
HEALTHZ = SCRIPTS / "openclaw/healthz-server.js"
ADAPTER = SCRIPTS / "communications-runtime-adapter.py"
DRIVER = Path(__file__).resolve().parents[1] / "fixtures/openclaw_telemetry_driver.mjs"
PARENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
BOT_A = "0000000a-0000-4000-8000-00000000000a"
BOT_B = "0000000b-0000-4000-8000-00000000000b"
UNKNOWN = "0000000c-0000-4000-8000-00000000000c"
FAKE_HEALTH = """
console.log(JSON.stringify({ok: true, channels: {
  telegram: {accountId: "default", running: true, connected: true, accounts: {
    default: {running: true, connected: true},
    "BOT_A_ID": {running: true, connected: false},
  }},
  discord: {accountId: "BOT_B_ID", running: true, connected: true, accounts: {
    "BOT_B_ID": {running: true, connected: true},
  }},
}}));
"""


class _Collector(HTTPServer):
    posts: list[dict]


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        server = cast(_Collector, self.server)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        server.posts.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _secrets(root: Path) -> Path:
    for bot_id in (BOT_A, BOT_B):
        (root / bot_id).mkdir(parents=True)
        (root / bot_id / "AGENT_ID").write_text(bot_id)
        (root / bot_id / "INGEST_API_KEY").write_text(f"ingest-{bot_id}")
    return root


def _collect(tmp_path: Path, command: list[str], expected_paths: set[str], extra_env=None) -> list[dict]:
    node = shutil.which("node")
    assert node is not None, "node is required to exercise the OpenClaw plugins"
    server = _Collector(("127.0.0.1", _free_port()), _Handler)
    server.posts = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {
        **os.environ,
        "AGENT_ID": PARENT,
        "INGEST_URL": f"http://127.0.0.1:{server.server_port}",
        "INGEST_API_KEY": "ingest-parent",
        "AGENTBARN_NATIVE_CHANNELS": "telegram,discord",
        "BOT_SECRET_ROOT": str(_secrets(tmp_path / "bots")),
        **(extra_env or {}),
    }
    proc = subprocess.Popen([node, *command], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not expected_paths <= {post["path"] for post in server.posts}:
            time.sleep(0.1)
        time.sleep(2.5)
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        server.shutdown()
        server.server_close()
    return server.posts


def _steps(tmp_path: Path, steps: list[dict]) -> str:
    path = tmp_path / "steps.json"
    path.write_text(json.dumps(steps))
    return str(path)


def _tool_call(ctx: dict, name: str) -> dict:
    return {"hook": "before_tool_call", "event": {"toolName": name, "toolCallId": name, "params": {}}, "ctx": ctx}


def _by_agent(posts: list[dict], suffix: str) -> dict[str, list[dict]]:
    found: dict[str, list[dict]] = {}
    for post in posts:
        agent = post["path"].split("/")[2]
        assert post["path"] == f"/agents/{agent}/{suffix}"
        found.setdefault(agent, []).append(post)
    return found


def test_telemetry_files_each_agents_tool_calls_under_that_agent(tmp_path):
    steps = _steps(
        tmp_path,
        [
            _tool_call({"agentId": "main", "sessionKey": "agent:main:x"}, "parent-call"),
            _tool_call({"agentId": BOT_A, "sessionKey": f"agent:{BOT_A}:x"}, "a-call"),
            _tool_call({"sessionKey": f"agent:{BOT_B}:x"}, "b-call"),
            _tool_call({"agentId": UNKNOWN}, "unknown-call"),
        ],
    )

    posts = _collect(
        tmp_path,
        [str(DRIVER), str(PLUGINS / "telemetry-push/index.js"), steps],
        {f"/agents/{agent}/events" for agent in (PARENT, BOT_A, BOT_B)},
    )

    found = _by_agent(posts, "events")
    assert set(found) == {PARENT, BOT_A, BOT_B}
    for agent, call in ((PARENT, "parent-call"), (BOT_A, "a-call"), (BOT_B, "b-call")):
        assert {post["auth"] for post in found[agent]} == {
            "Bearer ingest-parent" if agent == PARENT else f"Bearer ingest-{agent}"
        }
        calls = [tool["external_id"] for post in found[agent] for tool in post["body"]["tool_calls"]]
        assert calls == [call]


def test_telemetry_files_a_bots_message_by_its_account_and_marks_its_main_session_a_dm(tmp_path):
    steps = _steps(
        tmp_path,
        [
            {
                "hook": "message_received",
                "event": {"content": "hi", "messageId": "m1"},
                "ctx": {"accountId": BOT_A, "conversationId": "c1"},
            },
            {
                "hook": "message_received",
                "event": {"content": "hello", "messageId": "m2"},
                "ctx": {"sessionKey": f"agent:{BOT_B}:main", "conversationId": "c2"},
            },
        ],
    )

    posts = _collect(
        tmp_path,
        [str(DRIVER), str(PLUGINS / "telemetry-push/index.js"), steps],
        {f"/agents/{BOT_A}/events", f"/agents/{BOT_B}/events"},
    )

    found = _by_agent(posts, "events")
    assert set(found) == {BOT_A, BOT_B}
    message = found[BOT_B][0]["body"]["messages"][0]
    assert (message["msg_id"], message["conversation_type"]) == ("m2", "DM")


def test_the_observer_reports_each_agents_native_messages_as_that_agent(tmp_path):
    def received(ctx, message_id):
        return {
            "hook": "message_received",
            "event": {"content": "hi", "messageId": message_id, "senderId": "u"},
            "ctx": {"channelId": "telegram", "chatId": "c1", **ctx},
        }

    steps = _steps(
        tmp_path,
        [
            received({"sessionKey": "agent:main:telegram:direct:1", "accountId": "default"}, "p1"),
            received({"sessionKey": f"agent:{BOT_A}:telegram:direct:1", "accountId": BOT_A}, "a1"),
            received({"sessionKey": f"agent:{UNKNOWN}:telegram:direct:1"}, "u1"),
        ],
    )

    posts = _collect(
        tmp_path,
        [str(DRIVER), str(PLUGINS / "agentbarn-observer/index.js"), steps],
        {f"/agents/{PARENT}/communication-events", f"/agents/{BOT_A}/communication-events"},
    )

    found = _by_agent(posts, "communication-events")
    assert set(found) == {PARENT, BOT_A}
    assert {post["auth"] for post in found[BOT_A]} == {f"Bearer ingest-{BOT_A}"}
    ids = {
        agent: [m["provider_message_id"] for p in group for m in p["body"]["messages"]]
        for agent, group in found.items()
    }
    assert ids == {PARENT: ["p1"], BOT_A: ["a1"]}


def _healthz(tmp_path: Path, active: list | None):
    fake = tmp_path / "fake-health.js"
    fake.write_text(FAKE_HEALTH.replace("BOT_A_ID", BOT_A).replace("BOT_B_ID", BOT_B))
    active_file = tmp_path / "active-bots.json"
    if active is not None:
        active_file.write_text(json.dumps(active))
    port = _free_port()
    node = shutil.which("node")
    assert node is not None
    env = {
        "HEALTHZ_PORT": str(port),
        "HEALTHZ_HEALTH_COMMAND": json.dumps([node, str(fake)]),
        "BOT_ACTIVE_FILE": str(active_file),
    }
    return port, env


def test_health_reports_each_accounts_connection_under_its_own_agent(tmp_path):
    _, env = _healthz(tmp_path, [{"id": BOT_A, "slot": 1}, {"id": BOT_B, "slot": 2}])

    posts = _collect(
        tmp_path,
        [str(HEALTHZ)],
        {f"/agents/{agent}/communication-events" for agent in (PARENT, BOT_A, BOT_B)},
        env,
    )

    found = _by_agent(posts, "communication-events")
    stages = {
        agent: [(event["platform"], event["stage"]) for post in group for event in post["body"]["events"]]
        for agent, group in found.items()
    }
    assert stages == {
        PARENT: [("telegram", "connection_connected")],
        BOT_A: [("telegram", "connection_connecting")],
        BOT_B: [("discord", "connection_connected")],
    }
    assert {post["auth"] for post in found[BOT_B]} == {f"Bearer ingest-{BOT_B}"}


@pytest.mark.parametrize(("active", "expected"), [([{"id": BOT_A, "slot": 1}], [BOT_A]), (None, None)])
def test_health_lists_the_bots_the_pod_serves(tmp_path, active, expected):
    port, env = _healthz(tmp_path, active)
    node = shutil.which("node")
    assert node is not None
    proc = subprocess.Popen(
        [node, str(HEALTHZ)],
        env={**os.environ, **env},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        body = None
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as response:
                    body = json.loads(response.read())
                    break
            except OSError:
                time.sleep(0.2)
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    assert body is not None
    assert body.get("served_bots") == expected


def _marker_for(base: Path, key: str) -> Path:
    return Path(f"{base}.{hashlib.sha256(key.encode()).hexdigest()[:16]}")


def _spend(proxy: str, key: str) -> None:
    request = urllib.request.Request(
        f"{proxy}/chat/completions",
        data=b"{}",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        urllib.request.urlopen(request, timeout=10).read()
    except OSError:
        pass


def test_a_pod_with_bots_records_a_spent_limit_for_the_key_that_hit_it(tmp_path):
    marker = tmp_path / "marker.json"
    extra = {"AGENTBARN_LLM_ERROR_MARKER": str(marker), "RUNTIME_SESSION_PREFIX": "agent:main:"}
    with _upstream(400, BUDGET_BODY) as target, _proxy("openclaw", target, extra) as proxy:
        _spend(proxy, "sk-bot-a")

    assert _marker_for(marker, "sk-bot-a").exists()
    assert not _marker_for(marker, "sk-bot-b").exists()
    assert not marker.exists()


def test_a_pod_without_bots_keeps_one_marker(tmp_path):
    marker = tmp_path / "marker.json"
    with (
        _upstream(400, BUDGET_BODY) as target,
        _proxy("openclaw", target, {"AGENTBARN_LLM_ERROR_MARKER": str(marker)}) as proxy,
    ):
        _spend(proxy, "sk-parent")

    assert marker.exists()


def _adapter(monkeypatch, **env):
    base = {
        "COMMUNICATIONS_URL": "http://communications",
        "COMMUNICATIONS_API_KEY": "key",
        "AGENT_ID": "agent",
        "RUNTIME_API_URL": "http://runtime",
        "RUNTIME_API_KEY": "key",
        "RUNTIME_MODEL": "model",
        "RUNTIME_KIND": "openclaw",
        "AGENTBARN_LLM_ERROR_MARKER": "/tmp/marker.json",
    }
    for name in ("RUNTIME_SESSION_PREFIX", "GATEWAY_MULTIPLEX_PROFILES"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {**base, **env}.items():
        monkeypatch.setenv(name, value)
    spec = importlib.util.spec_from_file_location("openclaw_identity_adapter", ADAPTER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_bots_adapter_reads_the_marker_for_its_own_key(monkeypatch):
    adapter = _adapter(monkeypatch, RUNTIME_SESSION_PREFIX=f"agent:{BOT_A}:", LITELLM_API_KEY="sk-bot-a")

    assert adapter._LLM_ERROR_MARKER == f"/tmp/marker.json.{hashlib.sha256(b'sk-bot-a').hexdigest()[:16]}"


def test_an_adapter_in_a_pod_without_bots_reads_the_one_marker(monkeypatch):
    adapter = _adapter(monkeypatch, LITELLM_API_KEY="sk-parent")

    assert adapter._LLM_ERROR_MARKER == "/tmp/marker.json"
