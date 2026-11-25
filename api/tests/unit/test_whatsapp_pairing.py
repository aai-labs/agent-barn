import fcntl
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from api.domains.communications.whatsapp_pairing import (
    _HERMES_PAIRING_SCRIPT,
    _MARKER,
    _OPENCLAW_PAIRING_SCRIPT,
    pairing_event,
)

QR_A = "data:image/png;base64,AAAA"
QR_B = "data:image/png;base64,BBBB"


def test_pairing_event_passes_only_png_qr_images() -> None:
    assert pairing_event(json.dumps({"event": "qr_image", "image": QR_A})) == {"event": "qr_image", "image": QR_A}
    assert pairing_event(json.dumps({"event": "qr_image", "image": "data:image/svg+xml;base64,PHN2Zz4="})) is None
    assert pairing_event(json.dumps({"event": "qr_image", "image": "https://example.com/qr.png"})) is None
    assert pairing_event(json.dumps({"event": "qr_image"})) is None


def test_pairing_event_rebuilds_events_without_extra_fields() -> None:
    assert pairing_event('{"event":"qr","qr":"2@abc","session":"/opt/data"}') == {"event": "qr", "qr": "2@abc"}
    assert pairing_event('{"event":"connected","user":{"id":"15551234567:3@s.whatsapp.net"}}') == {
        "event": "connected",
        "phone": "+15551234567",
    }
    assert pairing_event('{"event":"connected"}') == {"event": "connected", "phone": None}
    assert pairing_event('{"event":"error","error":"busy"}') == {
        "event": "error",
        "message": "Another Link phone attempt is already running for this Agent.",
    }
    assert pairing_event('{"event":"error","error":"Boom /secret/path"}') == {
        "event": "error",
        "message": "WhatsApp pairing failed.",
    }
    assert pairing_event('{"event":"already_linked","phone":"+15551234567"}') == {
        "event": "already_linked",
        "phone": "+15551234567",
    }
    assert pairing_event('{"event":"already_linked","phone":"<b>unknown</b>"}') == {
        "event": "already_linked",
        "phone": None,
    }
    for line in ("not json", "[]", '{"event":"started"}', '{"level":40,"msg":"stream errored"}'):
        assert pairing_event(line) is None


# The scripts run in the Agent images, which have these; Linux CI runners do too.
needs_shell_tools = pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("flock", "jq", "timeout")) or not Path("/proc/self/cmdline").exists(),
    reason="needs Linux with flock, jq and timeout, as in the Agent images",
)
_PATH = "/usr/bin:/bin:/usr/local/bin"


def _install(bin_dir: Path, name: str, script: str) -> None:
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / name).write_text(script)
    (bin_dir / name).chmod(0o755)


def _events(stdout: str) -> list[dict]:
    return [event for line in stdout.splitlines() if (event := pairing_event(line))]


def _command(script: str, *args: str) -> list[str]:
    return ["sh", "-c", script, _MARKER, *args]


# Stands in for `openclaw gateway call METHOD --json --params P --timeout T`: logs each
# call, then answers with the next canned reply for that method ("FAIL" exits 1,
# "SLEEP" hangs like a wait nobody answers).
_FAKE_OPENCLAW = """#!/bin/sh
method="$3"; params="$6"
printf '%s %s\\n' "$method" "$params" >> "$HOME/calls.log"
n=$(cat "$HOME/$method.n" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$HOME/$method.n"
reply=$(sed -n "${n}p" "$HOME/$method.replies")
[ "$reply" = FAIL ] && exit 1
[ "$reply" = SLEEP ] && exec sleep 60
printf '%s\\n' "$reply"
"""


def _openclaw_home(tmp_path: Path, start: list[str], wait: list[str], health: tuple[str, ...] = ("{}",)) -> dict:
    _install(tmp_path / "bin", "openclaw", _FAKE_OPENCLAW)
    (tmp_path / "web.login.start.replies").write_text("\n".join(start) + "\n")
    (tmp_path / "web.login.wait.replies").write_text("\n".join(wait) + "\n")
    (tmp_path / "health.replies").write_text("\n".join(health) + "\n")
    return {"HOME": str(tmp_path), "PATH": f"{tmp_path / 'bin'}:{_PATH}"}


def _calls(tmp_path: Path) -> list[tuple[str, dict]]:
    log = tmp_path / "calls.log"
    lines = log.read_text().splitlines() if log.exists() else []
    return [(line.split(" ", 1)[0], json.loads(line.split(" ", 1)[1])) for line in lines]


def _run_openclaw_pairing(
    tmp_path: Path, start: list[str], wait: list[str], health: tuple[str, ...] = ("{}",), *args: str
) -> tuple[list[dict], list[tuple[str, dict]]]:
    env = _openclaw_home(tmp_path, start, wait, health)
    result = subprocess.run(
        _command(_OPENCLAW_PAIRING_SCRIPT, *args), env=env, capture_output=True, text=True, timeout=30, check=True
    )
    return _events(result.stdout), _calls(tmp_path)


@needs_shell_tools
def test_openclaw_pairing_follows_the_rotating_qr_until_the_phone_links(tmp_path: Path) -> None:
    events, calls = _run_openclaw_pairing(
        tmp_path,
        [json.dumps({"qrDataUrl": QR_A, "message": "Scan this QR"})],
        [
            json.dumps({"connected": False, "message": "Still waiting for the QR scan."}),
            json.dumps({"connected": False, "message": "QR refreshed.", "qrDataUrl": QR_B}),
            json.dumps({"connected": True, "message": "Linked"}),
        ],
    )

    assert events == [
        {"event": "qr_image", "image": QR_A},
        {"event": "qr_image", "image": QR_B},
        {"event": "connected", "phone": None},
        {"event": "linked"},
    ]
    # A linked phone is left alone unless the person asked to replace it, and each
    # wait names the QR the person sees.
    assert calls[0] == ("web.login.start", {"timeoutMs": 30000, "force": False})
    assert [params["currentQrDataUrl"] for _, params in calls[1:]] == [QR_A, QR_A, QR_B]


@needs_shell_tools
def test_openclaw_pairing_reports_a_linked_phone_instead_of_logging_it_out(tmp_path: Path) -> None:
    linked = {"message": "WhatsApp is already linked (+15551234567). Say “relink” if you want a fresh QR."}
    events, calls = _run_openclaw_pairing(tmp_path, [json.dumps(linked)], [])

    assert events == [{"event": "already_linked", "phone": "+15551234567"}]
    assert [method for method, _ in calls] == ["web.login.start"]


@needs_shell_tools
def test_openclaw_pairing_logs_the_linked_phone_out_only_when_asked_to_replace_it(tmp_path: Path) -> None:
    events, calls = _run_openclaw_pairing(
        tmp_path, [json.dumps({"qrDataUrl": QR_A})], [json.dumps({"connected": True})], ("{}",), "replace"
    )

    assert events[-1] == {"event": "linked"}
    assert calls[0] == ("web.login.start", {"timeoutMs": 30000, "force": True})


@needs_shell_tools
@pytest.mark.parametrize(
    ("start", "wait", "expected"),
    [
        (["FAIL"], [], {"event": "error", "message": "WhatsApp pairing failed."}),
        ([json.dumps({"message": "no QR"})], [], {"event": "error", "message": "WhatsApp pairing failed."}),
        ([json.dumps({"qrDataUrl": QR_A})], [json.dumps({"message": "The login QR expired."})], {"event": "expired"}),
        (
            [json.dumps({"qrDataUrl": QR_A})],
            [json.dumps({"message": "WhatsApp reported the session is logged out."})],
            {"event": "error", "message": "WhatsApp refused the link. Try again from Linked devices on the phone."},
        ),
        ([json.dumps({"qrDataUrl": QR_A})], ["FAIL"], {"event": "error", "message": "WhatsApp pairing failed."}),
    ],
)
def test_openclaw_pairing_ends_with_one_outcome(tmp_path: Path, start: list[str], wait: list[str], expected) -> None:
    events, _ = _run_openclaw_pairing(tmp_path, start, wait)

    assert events[-1] == expected
    assert [event["event"] for event in events[:-1]] in ([], ["qr_image"])


@needs_shell_tools
def test_openclaw_pairing_says_the_agent_is_starting_while_its_gateway_is_down(tmp_path: Path) -> None:
    events, _ = _run_openclaw_pairing(tmp_path, ["FAIL"], [], ("FAIL",))

    assert events == [
        {
            "event": "error",
            "message": "The Agent is still starting. On its first start with WhatsApp this takes a few minutes; "
            "try again then.",
        }
    ]


@needs_shell_tools
def test_a_new_openclaw_attempt_ends_an_abandoned_one(tmp_path: Path) -> None:
    # The first attempt's browser is gone, but its script still waits for a scan.
    env = _openclaw_home(
        tmp_path,
        [json.dumps({"qrDataUrl": QR_A}), json.dumps({"qrDataUrl": QR_B})],
        ["SLEEP", json.dumps({"connected": True})],
    )
    abandoned = subprocess.Popen(_command(_OPENCLAW_PAIRING_SCRIPT), env=env, stdout=subprocess.DEVNULL)
    _wait_for(lambda: (tmp_path / "web.login.wait.n").exists())

    started = time.monotonic()
    result = subprocess.run(
        _command(_OPENCLAW_PAIRING_SCRIPT), env=env, capture_output=True, text=True, timeout=30, check=True
    )

    assert _events(result.stdout) == [
        {"event": "qr_image", "image": QR_B},
        {"event": "connected", "phone": None},
        {"event": "linked"},
    ]
    assert time.monotonic() - started < 5
    assert abandoned.wait(timeout=5) != 0


@needs_shell_tools
def test_a_lock_held_by_something_else_is_not_taken_over(tmp_path: Path) -> None:
    (tmp_path / ".openclaw").mkdir()
    with (tmp_path / ".openclaw" / "whatsapp-pairing.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        events, calls = _run_openclaw_pairing(tmp_path, [json.dumps({"qrDataUrl": QR_A})], [])

    assert events == [{"event": "error", "message": "Another Link phone attempt is already running for this Agent."}]
    assert calls == []


def _wait_for(condition, seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.05)


# Stands in for Hermes' bridge in --pair-only mode, run as `node bridge.js ... --session DIR`.
# BRIDGE_OUTCOME picks what the phone does.
_FAKE_NODE = """#!/bin/sh
session="$5"
echo '{"event":"qr","qr":"2@abc"}'
case "$BRIDGE_OUTCOME" in
  link) mkdir -p "$session" && echo new > "$session/creds.json"
        echo '{"event":"connected","user":{"id":"15551234567:3@s.whatsapp.net"}}' ;;
  fail) mkdir -p "$session" && echo new > "$session/creds.json"; exit 1 ;;
  expire) exit 124 ;;
  hang) exec sleep 59 ;;
esac
"""


def _hermes_env(tmp_path: Path, outcome: str) -> dict:
    _install(tmp_path / "bin", "node", _FAKE_NODE)
    (tmp_path / "bridge").mkdir(exist_ok=True)
    return {
        "HERMES_HOME": str(tmp_path / "home"),
        "WHATSAPP_BRIDGE_DIR": str(tmp_path / "bridge"),
        "BRIDGE_OUTCOME": outcome,
        "PATH": f"{tmp_path / 'bin'}:{_PATH}",
    }


def _run_hermes_pairing(tmp_path: Path, outcome: str) -> list[dict]:
    result = subprocess.run(
        _command(_HERMES_PAIRING_SCRIPT),
        env=_hermes_env(tmp_path, outcome),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return _events(result.stdout)


def _old_session(tmp_path: Path, subdir: str = "platforms/whatsapp") -> Path:
    session = tmp_path / "home" / subdir / "session"
    session.mkdir(parents=True)
    (session / "creds.json").write_text("old")
    return session


@needs_shell_tools
def test_hermes_pairing_swaps_in_the_new_session_and_stops_the_old_bridge(tmp_path: Path) -> None:
    session = _old_session(tmp_path)
    bridge = subprocess.Popen(["sh", "-c", "sleep 60; : bridge.js"])
    (session / "bridge.pid").write_text(f"{bridge.pid}\n")

    events = _run_hermes_pairing(tmp_path, "link")

    assert [event["event"] for event in events] == ["qr", "connected", "linked"]
    assert (session / "creds.json").read_text() == "new\n"
    assert not (session.parent / "pairing").exists()
    assert not (session.parent / "session.previous").exists()
    assert bridge.wait(timeout=5) != 0


@needs_shell_tools
def test_hermes_pairing_never_kills_a_process_that_is_not_the_bridge(tmp_path: Path) -> None:
    session = _old_session(tmp_path)
    stranger = subprocess.Popen(["sleep", "60"])
    (session / "bridge.pid").write_text(f"{stranger.pid}\n")
    try:
        assert _run_hermes_pairing(tmp_path, "link")[-1] == {"event": "linked"}
        assert stranger.poll() is None
    finally:
        stranger.kill()


@needs_shell_tools
@pytest.mark.parametrize(("outcome", "events"), [("nothing", ["qr"]), ("fail", ["qr"]), ("expire", ["qr", "expired"])])
def test_hermes_pairing_leaves_the_working_session_alone_unless_a_phone_links(
    tmp_path: Path, outcome: str, events: list[str]
) -> None:
    session = _old_session(tmp_path)

    assert [event["event"] for event in _run_hermes_pairing(tmp_path, outcome)] == events
    assert (session / "creds.json").read_text() == "old"
    assert not (session.parent / "pairing").exists()


@needs_shell_tools
def test_hermes_pairing_links_into_the_legacy_session_hermes_still_uses(tmp_path: Path) -> None:
    legacy = _old_session(tmp_path, "whatsapp")

    assert _run_hermes_pairing(tmp_path, "link")[-1] == {"event": "linked"}
    assert (legacy / "creds.json").read_text() == "new\n"
    assert not (tmp_path / "home" / "platforms" / "whatsapp" / "session").exists()


@needs_shell_tools
def test_a_new_hermes_attempt_ends_an_abandoned_one(tmp_path: Path) -> None:
    session = _old_session(tmp_path)
    abandoned = subprocess.Popen(
        _command(_HERMES_PAIRING_SCRIPT), env=_hermes_env(tmp_path, "hang"), stdout=subprocess.DEVNULL
    )
    _wait_for(lambda: (session.parent / "pairing.holder").exists())

    events = _run_hermes_pairing(tmp_path, "link")

    assert events[-1] == {"event": "linked"}
    assert abandoned.wait(timeout=5) != 0
    assert (session / "creds.json").read_text() == "new\n"
    assert not any("sleep 59" in _cmdline(pid) for pid in os.listdir("/proc") if pid.isdigit())


def _cmdline(pid: str) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    except OSError:
        return ""
