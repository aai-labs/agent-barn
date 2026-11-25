import fcntl
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from api.domains.communications.whatsapp_pairing import _OPENCLAW_PAIRING_SCRIPT, pairing_event

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
    for line in ("not json", "[]", '{"event":"started"}', '{"level":40,"msg":"stream errored"}'):
        assert pairing_event(line) is None


# The script runs in the OpenClaw image, which has both; Linux CI runners do too.
needs_shell_tools = pytest.mark.skipif(
    not (shutil.which("flock") and shutil.which("jq")), reason="needs flock and jq, as in the OpenClaw image"
)

# Stands in for `openclaw gateway call METHOD --json --params P --timeout T`: logs each
# call, then answers with the next canned reply for that method (exit 1 for "FAIL").
_FAKE_OPENCLAW = """#!/bin/sh
method="$3"; params="$6"
printf '%s %s\\n' "$method" "$params" >> "$HOME/calls.log"
n=$(cat "$HOME/$method.n" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$HOME/$method.n"
reply=$(sed -n "${n}p" "$HOME/$method.replies")
[ "$reply" = FAIL ] && exit 1
printf '%s\\n' "$reply"
"""


def _run_openclaw_pairing(
    tmp_path: Path, start: list[str], wait: list[str], health: tuple[str, ...] = ("{}",)
) -> tuple[list[dict], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "openclaw"
    fake.write_text(_FAKE_OPENCLAW)
    fake.chmod(0o755)
    (tmp_path / "web.login.start.replies").write_text("\n".join(start) + "\n")
    (tmp_path / "web.login.wait.replies").write_text("\n".join(wait) + "\n")
    (tmp_path / "health.replies").write_text("\n".join(health) + "\n")
    result = subprocess.run(
        ["sh", "-c", _OPENCLAW_PAIRING_SCRIPT],
        env={"HOME": str(tmp_path), "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    events = [event for line in result.stdout.splitlines() if (event := pairing_event(line))]
    log = tmp_path / "calls.log"
    return events, log.read_text().splitlines() if log.exists() else []


@needs_shell_tools
def test_openclaw_pairing_follows_the_rotating_qr_until_the_phone_links(tmp_path: Path) -> None:
    events, calls = _run_openclaw_pairing(
        tmp_path,
        start=[json.dumps({"qrDataUrl": QR_A, "message": "Scan this QR"})],
        wait=[
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
    # A linked Agent is logged out first, and each wait names the QR the person sees.
    assert json.loads(calls[0].split(" ", 1)[1]) == {"timeoutMs": 30000, "force": True}
    assert [json.loads(call.split(" ", 1)[1])["currentQrDataUrl"] for call in calls[1:]] == [QR_A, QR_A, QR_B]


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
    events, _ = _run_openclaw_pairing(tmp_path, start=start, wait=wait)

    assert events[-1] == expected
    assert [event["event"] for event in events[:-1]] in ([], ["qr_image"])


@needs_shell_tools
def test_openclaw_pairing_says_the_agent_is_starting_while_its_gateway_is_down(tmp_path: Path) -> None:
    events, _ = _run_openclaw_pairing(tmp_path, start=["FAIL"], wait=[], health=("FAIL",))

    assert events == [
        {
            "event": "error",
            "message": "The Agent is still starting. On its first start with WhatsApp this takes a few minutes; "
            "try again then.",
        }
    ]


@needs_shell_tools
def test_openclaw_pairing_runs_one_attempt_at_a_time(tmp_path: Path) -> None:
    (tmp_path / ".openclaw").mkdir()
    with (tmp_path / ".openclaw" / "whatsapp-pairing.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        events, calls = _run_openclaw_pairing(tmp_path, start=[json.dumps({"qrDataUrl": QR_A})], wait=[])

    assert events == [{"event": "error", "message": "Another Link phone attempt is already running for this Agent."}]
    assert calls == []
