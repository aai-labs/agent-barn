"""Runs inside hermes-base: the real healthz server must report this container's own
cgroup limits, read as the image's own user.

The caller starts the container with `--memory 1g --cpus 0.5`, so the limits are known.
A fake cgroup directory proves the arithmetic; only the image can prove that the files
exist at /sys/fs/cgroup and that the user the runtime runs as may read them.

Usage: python3 hermes_healthz_metrics_driver.py /path/to/healthz-server.py
"""

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

PORT = "18081"
GIB = 1024**3


def samples(text: str) -> dict[str, float]:
    values = {}
    for line in text.splitlines():
        if line and not line.startswith("#"):
            name, value = line.split(" ", 1)
            values[name] = float(value)
    return values


server = subprocess.Popen(
    [sys.executable, sys.argv[1]],
    env={**os.environ, "HEALTHZ_PORT": PORT},
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
try:
    base = f"http://127.0.0.1:{PORT}"
    deadline = time.monotonic() + 15
    while True:
        try:
            urllib.request.urlopen(f"{base}/ready", timeout=1)
            break
        # OSError covers URLError and ConnectionError. A multi-type `except` is spelled
        # without parentheses on Python 3.14 (which ruff would write here), and this
        # file runs on the image's own interpreter, which is older.
        except OSError:
            if time.monotonic() > deadline:
                raise SystemExit("healthz server did not start")
            time.sleep(0.2)

    body = urllib.request.urlopen(f"{base}/metrics", timeout=5).read().decode()
    found = samples(body)

    assert found.get("agent_cgroup_metrics_available") == 1, f"cgroup v2 files unreadable as uid {os.getuid()}: {found}"
    assert found.get("agent_memory_limit_bytes") == GIB, found
    assert found.get("agent_cpu_limit_cores") == 0.5, found
    assert found.get("agent_memory_working_set_bytes", 0) > 0, found
    assert found.get("agent_cpu_usage_seconds_total", 0) > 0, found
    assert "agent_cpu_periods_total" in found and "agent_cpu_throttled_periods_total" in found, found
    print(f"OK: cgroup metrics readable as uid {os.getuid()}")
finally:
    server.terminate()
    server.wait(timeout=5)
