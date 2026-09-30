import importlib.util
import io
import json
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest
from hamcrest import assert_that, contains_string, equal_to, has_length

ROOT = Path(__file__).parents[2] / "domains/agents/scripts/messaging"


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTBARN_MESSAGE_SPOOL", str(tmp_path / "messages.sqlite3"))
    monkeypatch.setenv("AGENTBARN_EXECUTIONS_DIR", str(tmp_path / "executions"))
    spec = importlib.util.spec_from_file_location("agentbarn_message_test", ROOT / "agentbarn_message.py")
    if spec is None or spec.loader is None:
        raise AssertionError("Could not load the agent message client")
    loader = spec.loader
    client = importlib.util.module_from_spec(spec)
    loader.exec_module(client)
    return client


def test_completion_survives_process_restart_and_lost_acknowledgement(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from agentbarn_message import capture_completion; capture_completion('hermes:one','result')",
        ],
        cwd=ROOT,
        check=True,
    )
    submissions = []

    def lost_ack(method, path, payload):
        submissions.append(payload)
        raise TimeoutError

    monkeypatch.setattr(client, "request", lost_ack)
    client.drain_once()
    with client._spool() as db:
        assert_that(db.execute("SELECT receipt FROM completions").fetchone()[0], equal_to(None))
        db.execute("UPDATE completions SET available_at=0")
    receipt = {"delivery_id": "durable-one", "status": "PENDING"}
    monkeypatch.setattr(client, "request", lambda method, path, payload: submissions.append(payload) or receipt)
    client.drain_once()
    client.drain_once()
    assert_that(submissions, has_length(2))
    assert_that(submissions[0], equal_to(submissions[1]))
    with client._spool() as db:
        assert_that(json.loads(db.execute("SELECT receipt FROM completions").fetchone()[0]), equal_to(receipt))


def _refusal(code, detail="Agent has no configured default delivery target"):
    body = io.BytesIO(json.dumps({"detail": detail}).encode())
    return urllib.error.HTTPError("http://communications/messages", code, "refused", {}, body)  # ty: ignore[invalid-argument-type]


@pytest.mark.parametrize(
    "code,retried", [(400, False), (403, False), (409, False), (408, True), (429, True), (503, True)]
)
def test_only_a_failure_that_could_succeed_later_is_retried(monkeypatch, tmp_path, code, retried):
    """A permanent refusal retried forever never shrinks the spool and can land hours late."""
    client = _client(monkeypatch, tmp_path)
    client.capture_completion("one", "Scheduled result")
    submissions = []

    def refuse(method, path, payload):
        submissions.append(payload)
        raise _refusal(code)

    monkeypatch.setattr(client, "request", refuse)
    client.drain_once()
    with client._spool() as db:
        db.execute("UPDATE completions SET available_at=0")
    client.drain_once()
    assert_that(submissions, has_length(2 if retried else 1))


def test_retries_stop_at_the_attempt_ceiling(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.capture_completion("one", "Scheduled result")
    with client._spool() as db:
        db.execute("UPDATE completions SET attempts=?", (client.MAX_ATTEMPTS - 1,))
    monkeypatch.setattr(client, "request", lambda method, path, payload: (_ for _ in ()).throw(TimeoutError()))
    client.drain_once()
    with client._spool() as db:
        assert_that(db.execute("SELECT settled_at IS NOT NULL FROM completions").fetchone()[0], equal_to(1))


def test_settled_rows_are_pruned_only_after_the_retention_window(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    for run_id in ("old", "recent", "pending"):
        client.capture_completion(run_id, f"Scheduled result {run_id}")
    now = client.time.time()
    with client._spool() as db:
        db.execute("UPDATE completions SET settled_at=? WHERE run_id='old'", (now - client.RETENTION_SECONDS - 1,))
        db.execute("UPDATE completions SET settled_at=? WHERE run_id='recent'", (now,))
        db.execute("UPDATE completions SET available_at=? WHERE run_id='pending'", (now + 3600,))
    client.drain_once()
    with client._spool() as db:
        remaining = [row[0] for row in db.execute("SELECT run_id FROM completions ORDER BY run_id")]
    assert_that(remaining, equal_to(["pending", "recent"]))


def test_existing_spool_is_upgraded_with_terminal_state(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    path = tmp_path / "messages.sqlite3"
    with client.sqlite3.connect(path) as db:
        db.execute(
            """CREATE TABLE completions (
                run_id TEXT PRIMARY KEY, request TEXT NOT NULL, receipt TEXT,
                attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL DEFAULT 0, error TEXT
            )"""
        )

    with client._spool() as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(completions)")]

    assert_that("settled_at" in columns, equal_to(True))


@pytest.mark.parametrize(
    "error,expected",
    [
        (_refusal(403, "Outbound recipient is not allowed by this Connection"), "Do not retry"),
        (TimeoutError(), "retry the same tool invocation"),
    ],
)
def test_cli_tells_the_model_to_retry_only_what_could_succeed(monkeypatch, tmp_path, capsys, error, expected):
    client = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["agentbarn-message", "send", "--to", "C123", "--text", "hi"])
    monkeypatch.setattr(client, "send_explicit", lambda *args: (_ for _ in ()).throw(error))
    with pytest.raises(SystemExit):
        client.main()
    assert_that(capsys.readouterr().err, contains_string(expected))


@pytest.mark.parametrize(
    "command,matched",
    [
        ("agentbarn-message send --to C123 --text hi", True),
        ("cd /workspace && /tmp/agentbarn-bin/agentbarn-message send --to C123 --text hi", True),
        ("ls -la /opt/data/agentbarn-messages.sqlite3", False),
        ("cat agentbarn-message.log", False),
    ],
)
def test_hermes_hook_matches_the_command_not_a_path_that_contains_it(monkeypatch, tmp_path, command, matched):
    monkeypatch.syspath_prepend(str(ROOT))
    spec = importlib.util.spec_from_file_location("hermes_messaging_test", ROOT / "hermes-messaging.py")
    if spec is None or spec.loader is None:
        raise AssertionError("Could not load the Hermes messaging hook")
    loader = spec.loader
    hook = importlib.util.module_from_spec(spec)
    loader.exec_module(hook)
    # No inbound binding exists, so a matched command is blocked and anything else passes through untouched.
    result = hook.before_tool("terminal", {"command": command}, session_id="cron", tool_call_id="call")
    assert_that(result is not None, equal_to(matched))


def test_either_silence_marker_suppresses_submission_but_prose_does_not(monkeypatch, tmp_path):
    """Templates say HEARTBEAT_OK, the delivery policy says [SILENT]; both must stay quiet.

    Surrounding whitespace is ignored because a trailing newline is the normal shape of
    a model's final response, and posting a bare "[SILENT]" to Slack is the worse failure.
    """
    client = _client(monkeypatch, tmp_path)
    quiet = [
        "[SILENT]",
        "HEARTBEAT_OK",
        " [SILENT] ",
        "HEARTBEAT_OK\n",
        "   ",
        # The runtime's own tokens: BOOT.md and the seeds hand these to agents, and
        # models drop the brackets often enough that Hermes matches them natively.
        "SILENT",
        "no_reply",
        "NO REPLY",
        "Here is the summary.\n\n[silent]",
    ]
    delivered = ["Report [SILENT]", "HEARTBEAT_OK: 3 blockers", "Nothing to flag today.", "no reply was received"]
    for key, text in enumerate(quiet + delivered):
        client.capture_completion(str(key), text)
    with client._spool() as db:
        assert_that(db.execute("SELECT COUNT(*) FROM completions").fetchone()[0], equal_to(len(delivered)))


def test_changed_completion_cannot_replace_persisted_run(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.capture_completion("one", "first")
    with pytest.raises(ValueError):
        client.capture_completion("one", "second")


def test_runtime_binding_is_session_scoped_and_removed_at_completion(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.bind_execution("inbound", {"execution_token": "server-token", "delivery_id": "delivery"})
    assert_that(client.execution_environment("inbound", "call")["AGENTBARN_INVOCATION_ID"], equal_to("delivery:call"))
    with pytest.raises(FileNotFoundError):
        client.execution_environment("cron", "call")
    client.unbind_execution("inbound")
    with pytest.raises(FileNotFoundError):
        client.execution_environment("inbound", "call")


@pytest.mark.parametrize(
    "origin,expected",
    [
        (None, {"kind": "default"}),
        ({}, {"kind": "default"}),
        (
            {"platform": "api_server", "chat_id": "connection:0191-uuid:C123:root"},
            {"kind": "origin", "connection_id": "0191-uuid", "channel_id": "C123", "thread_id": None},
        ),
        (
            {"platform": "api_server", "chat_id": "connection:0191-uuid:C123:1788328904.404579"},
            {"kind": "origin", "connection_id": "0191-uuid", "channel_id": "C123", "thread_id": "1788328904.404579"},
        ),
        # Created somewhere we cannot map: refuse rather than divert to the default.
        ({"platform": "telegram", "chat_id": "-1001"}, None),
        ({"platform": "api_server", "chat_id": "api_9f2c1b"}, None),
        # The boot checklist runs under a session but not a conversation.
        ({"platform": "api_server", "chat_id": "agentbarn-boot"}, {"kind": "default"}),
        ({"platform": "api_server", "chat_id": "connection::C123:root"}, None),
        ({"platform": "api_server", "chat_id": "connection:0191-uuid"}, None),
    ],
)
def test_origin_maps_only_to_conversations_the_adapter_minted(monkeypatch, tmp_path, origin, expected):
    client = _client(monkeypatch, tmp_path)
    assert_that(client.destination_for_origin(origin), equal_to(expected))


_THREADED = {"platform": "api_server", "chat_id": "connection:0191-uuid:C123:1788991850.702569"}


@pytest.mark.parametrize(
    "deliver,expected_thread",
    [
        # Says nothing about routing: keep the thread the conversation happened in.
        (None, "1788991850.702569"),
        ("origin", "1788991850.702569"),
        ("local", "1788991850.702569"),
        ("all", "1788991850.702569"),
        ("origin,all", "1788991850.702569"),
        # Same channel, empty thread segment: post at channel level.
        ("slack:C123:", None),
        ("slack:C123", None),
        # Same channel, explicit thread.
        ("slack:C123:1788000000.000001", "1788000000.000001"),
    ],
)
def test_deliver_moves_a_job_within_its_own_channel(monkeypatch, tmp_path, deliver, expected_thread):
    client = _client(monkeypatch, tmp_path)
    destination = client.destination_for_origin(_THREADED, deliver)
    assert_that(destination["channel_id"], equal_to("C123"))
    assert_that(destination["thread_id"], equal_to(expected_thread))


@pytest.mark.parametrize("deliver", ["slack:C999:", "slack:C999:178.000001", "telegram:-1001:17"])
def test_deliver_naming_another_channel_is_refused_not_silently_rerouted(monkeypatch, tmp_path, deliver):
    client = _client(monkeypatch, tmp_path)
    assert_that(client.destination_for_origin(_THREADED, deliver), equal_to(None))


def test_unmappable_origin_is_never_delivered_to_the_default(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.capture_completion("one", "Scheduled result", {"platform": "telegram", "chat_id": "-1001"})
    client.capture_completion("two", "Scheduled result", None)
    with client._spool() as db:
        rows = db.execute("SELECT run_id, request FROM completions").fetchall()
    assert_that(rows, has_length(1))
    assert_that(rows[0][0], equal_to("two"))
    assert_that(json.loads(rows[0][1])["destination"], equal_to({"kind": "default"}))
