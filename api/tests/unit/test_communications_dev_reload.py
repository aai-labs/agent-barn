"""Local reload must recover with an active runtime control stream."""

import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml
from hamcrest import assert_that, equal_to, is_not, none

_ROOT = Path(__file__).resolve().parents[3]
_APP = """
import asyncio
import os
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
app = FastAPI()
@app.get("/health")
async def health():
    return {"pid": os.getpid()}
@app.get("/control")
async def control():
    async def events():
        yield "data: ready\\n\\n"
        while True:
            await asyncio.sleep(1)
            yield "data: heartbeat\\n\\n"
    return StreamingResponse(events(), media_type="text/event-stream")
"""


def _pid(base: str) -> int | None:
    try:
        with urllib.request.urlopen(base + "/health", timeout=0.5) as response:
            return json.load(response)["pid"]
    except urllib.error.URLError, TimeoutError, ConnectionError:
        return None


def _wait_pid(base: str, previous: int | None = None) -> int | None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        pid = _pid(base)
        if pid is not None and pid != previous:
            return pid
        time.sleep(0.1)
    return None


@pytest.mark.parametrize("launcher", ["compose", "make"])
def test_communications_reload_recovers_with_open_control_stream(tmp_path, launcher):
    if launcher == "compose":
        command = yaml.safe_load((_ROOT / "compose.yml").read_text())["services"]["communications"]["command"]
        args = command[1:]
    else:
        line = (_ROOT / "Makefile").read_text().split("dev-communications:\n", 1)[1].splitlines()[0]
        args = shlex.split(line.split("uvicorn ", 1)[1])
        args[args.index("--app-dir") + 1] = str(tmp_path)
    # Exercise the shipped launch flags, isolating database/provider setup with
    # an idle stream equivalent to the runtime control connection.
    args[0] = "reload_probe:app"
    args[args.index("--host") + 1] = "127.0.0.1"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    args[args.index("--port") + 1] = str(port)
    app_file = tmp_path / "reload_probe.py"
    app_file.write_text(_APP)
    base = f"http://127.0.0.1:{port}"
    with (tmp_path / "server.log").open("w") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", *args], cwd=tmp_path, stdout=log, stderr=log, start_new_session=True
        )
        try:
            original = _wait_pid(base)
            assert_that(original, is_not(none()), "server must start before testing reload")
            with urllib.request.urlopen(base + "/control", timeout=2) as stream:
                assert_that(stream.readline(), equal_to(b"data: ready\n"))
                # The parent starts its watcher after spawning the ready child.
                time.sleep(1)
                app_file.write_text(_APP + "\n# trigger reload\n")
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and "Reloading" not in (tmp_path / "server.log").read_text():
                    time.sleep(0.1)
                assert_that(
                    "Reloading" in (tmp_path / "server.log").read_text(),
                    equal_to(True),
                    "file watcher must detect the edit",
                )
                replacement = _wait_pid(base, original)
                assert_that(replacement, is_not(none()), "reload must finish while the control stream stays open")
                assert_that(replacement, is_not(equal_to(original)))
        finally:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
