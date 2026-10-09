"""Offline real-CLI contract driver; only a loopback token/handoff stub is reachable."""

import http.server
import json
import os
import subprocess
import threading
from pathlib import Path

artifacts = json.loads(Path("/contract/artifacts.json").read_text())
requests = []
refuse_handoff = True


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": json.loads(body) if body else None,
            }
        )
        code = 409 if self.path.endswith("/handoff") and refuse_handoff else 200
        reply = json.dumps(
            {"access_token": "temporary-graph-access", "expires_in": 3600, "scopes": ["Sites.Read.All"]}
        ).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, format, *args):
        pass


server = http.server.HTTPServer(("127.0.0.1", 18080), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
config = Path("/app/config")
home = artifacts["home"]
store = Path(artifacts["store"])
marker = store / "microsoft.sharepoint_refresh_token.sign-in"
config_path = str(Path(home) / ".config/aai-cli/config.toml")


def install(name):
    selected = artifacts[name]
    for path, content in selected["files"].items():
        (config / path).write_text(content)
    return {**os.environ, **selected["env"], "HOME": home}


def run(args, env, *, success=True, stdin=None):
    result = subprocess.run(args, input=stdin, capture_output=True, text=True, env=env, timeout=20, check=False)
    if success:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
    return result


def setup(env, *, success=True):
    return run(["sh", "/app/config/aai-cli-setup.sh"], env, success=success)


def snapshot():
    return {"store": (store / "aai-secrets.enc.json").read_text(), "key": (store / "key").read_text()}


direct_env = install("direct")
setup(direct_env)
run(
    ["aai-cli", "--config", config_path, "secrets", "set", "microsoft.sharepoint_refresh_token"],
    direct_env,
    stdin="rotated-pvc-grant",
)
setup(direct_env)  # Restart must keep the CLI's newest rotation.
prior = snapshot()
isolated_env = install("isolated")
setup(isolated_env, success=False)
assert snapshot() == prior and marker.exists(), "Failed handoff erased the only PVC grant"
refuse_handoff = False
setup(isolated_env)
assert not marker.exists()
# A repeat boot still succeeds; the real gateway's idempotence is verified in DB tests.
setup(isolated_env)
removed = run(["aai-cli", "--config", config_path, "secrets", "list"], isolated_env).stdout
assert "microsoft.sharepoint_refresh_token" not in removed
assert "github.token" in removed, "Isolation erased an unrelated direct credential"
for cleared in ("jira.api_token", "confluence.api_token", "bitbucket.api_token", "pipedrive.api_token"):
    assert cleared not in removed, f"An isolated provider still has its renewable credential: {cleared}"
run(["aai-cli", "--config", config_path, "config", "profiles", "list"], isolated_env)

cli = ["aai-cli", "--config", config_path, "--profile", "sharepoint-work", "microsoft"]
run([*cli, "auth", "status"], isolated_env)
count = len(requests)
missing_env = {k: v for k, v in isolated_env.items() if k != "AF_GATEWAY_TOKEN_SHAREPOINT"}
missing_env["AAI_API_TOKEN"] = "unrelated-fallback"
run([*cli, "auth", "status"], missing_env, success=False)
assert len(requests) == count, "Missing dedicated token used an unrelated credential"

# Typed commands must pass their auth gate and fetch a brokered token. Graph is
# unreachable under --network none, so no fixture credential can leave the container.
Path("/tmp/upload.txt").write_text("fixture")
for command in (
    ["sharepoint", "files", "download", "fixture.txt", "--drive-id", "fixture-drive", "--output", "/tmp/download.txt"],
    ["sharepoint", "files", "upload", "/tmp/upload.txt", "fixture.txt", "--drive-id", "fixture-drive"],
    ["excel", "worksheets", "list", "--drive-id", "fixture-drive", "--path", "fixture.xlsx"],
):
    count = len(requests)
    result = run([*cli, *command], isolated_env, success=False)
    assert "unsupported_auth" not in result.stdout + result.stderr
    assert len(requests) > count, f"Typed command never reached broker: {command}"

# Handback imports the latest service grant with a new marker revision.
handback_env = install("handback")
setup(handback_env)
assert marker.read_text().endswith(":service-revision")
print(json.dumps({"prior": prior, "final": snapshot(), "requests": requests, "uid": os.getuid()}))
server.shutdown()
