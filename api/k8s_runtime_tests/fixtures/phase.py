"""Runs actual generated setup and CLI against a PVC; prints no credential values."""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

phase, home, store_dir = sys.argv[1:]
store = Path(store_dir)
config = str(Path(home) / ".config/aai-cli/config.toml")
marker = store / "microsoft.sharepoint_refresh_token.sign-in"
cli = ["aai-cli", "--config", config]


def run(args, *, success=True, stdin=None, env=None):
    result = subprocess.run(args, input=stdin, capture_output=True, text=True, env=env, timeout=30, check=False)
    if (result.returncode == 0) != success:
        raise RuntimeError("Fixture command did not have the expected exit status: " + args[0])
    return result.stdout


def snapshot():
    return (store / "aai-secrets.enc.json").read_bytes(), (store / "key").read_bytes(), marker.read_bytes()


broker_host = urlsplit(os.environ["AF_GATEWAY_URL"]).hostname
# The policy controller installs rules asynchronously when the pod starts.
# Wait for enforcement before importing any fixture credentials.
for attempt in range(15):
    try:
        with socket.create_connection((broker_host, 18081), timeout=3):
            pass
    except (TimeoutError, ConnectionRefusedError):
        break
    time.sleep(1)
else:
    raise RuntimeError("NetworkPolicy allowed the fixture boundary on a forbidden port")

with socket.create_connection((broker_host, 18080), timeout=3):
    pass

before = snapshot() if phase == "refused" else None
run(["sh", "/app/config/aai-cli-setup.sh"], success=phase != "refused")
if phase == "refused":
    assert snapshot() == before, "Rejected handoff changed the PVC grant"
else:
    keys = run([*cli, "secrets", "list"])
    if phase in ("direct", "handback"):
        assert "github.token" in keys and "microsoft.sharepoint_refresh_token" in keys
        if phase == "direct":
            run([*cli, "secrets", "set", "microsoft.sharepoint_refresh_token"], stdin="rotated-pvc-grant")
        else:
            endpoint = os.environ["AF_GATEWAY_URL"].removesuffix("/gateway/v1") + "/control"
            payload = json.dumps(
                {
                    "handback": {
                        "store": (store / "aai-secrets.enc.json").read_text(),
                        "key": (store / "key").read_text(),
                    }
                }
            ).encode()
            request = urllib.request.Request(endpoint, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=10):
                pass
            assert marker.read_text().endswith(":service-revision")
    else:
        assert not marker.exists(), "Isolated boot retained the direct sign-in marker"
        for key in (
            "github.token",
            "microsoft.sharepoint_refresh_token",
            "jira.api_token",
            "confluence.api_token",
            "bitbucket.api_token",
            "pipedrive.api_token",
        ):
            assert key not in keys, "Isolated boot retained a renewable credential entry"
        microsoft = [*cli, "--profile", "sharepoint-work", "microsoft", "auth", "status"]
        run(microsoft)
        run([*cli, "--profile", "github-work", "github", "request", "get", "/user"])
        endpoint = os.environ["AF_GATEWAY_URL"].removesuffix("/gateway/v1") + "/observations"
        with urllib.request.urlopen(endpoint, timeout=10) as response:
            count = json.load(response)["tokens"]
        env = {key: value for key, value in os.environ.items() if key != "AF_GATEWAY_TOKEN_SHAREPOINT"}
        env["AAI_API_TOKEN"] = "unrelated-fallback"
        run(microsoft, env=env, success=False)
        with urllib.request.urlopen(endpoint, timeout=10) as response:
            assert json.load(response)["tokens"] == count, "Missing dedicated token used environment fallback"
assert os.getuid() != 0, "Contract must use the runtime image's non-root user"
print(json.dumps({"phase": phase, "status": "ok", "uid": os.getuid()}))
