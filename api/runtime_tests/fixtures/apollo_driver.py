"""Real Apollo CLI against an offline loopback provider/gateway boundary."""

import http.server
import json
import os
import subprocess
import threading
from pathlib import Path

artifacts = json.loads(Path("/contract/artifacts.json").read_text())
requests = []


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        requests.append(
            {"path": self.path, "auth": self.headers.get("Authorization"), "key": self.headers.get("x-api-key")}
        )
        reply = b'{"data":[],"healthy":true,"is_logged_in":true}'
        allowed = (
            not self.path.startswith("/gateway/") or self.headers.get("Authorization") == "Bearer agt_apollo_fixture"
        )
        self.send_response(200 if allowed else 403)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, format, *args):
        pass


server = http.server.HTTPServer(("127.0.0.1", 18080), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
config_path = f"{artifacts['home']}/.config/aai-cli/config.toml"
cli = ["aai-cli", "--config", config_path]


def run(args, env, *, success=True):
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=15, check=False)
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    return result


def install(mode):
    selected = artifacts[mode]
    for name, value in selected["files"].items():
        Path(f"/app/config/{name}").write_text(value)
    env = {**os.environ, **selected["env"], "HOME": artifacts["home"]}
    run(["sh", "/app/config/aai-cli-setup.sh"], env)
    return env


commands = (["users", "me"], ["request", "get", "/users/api_profile"], ["health"])
try:
    direct = install("direct")
    # Fixture-only override: direct production profiles retain Apollo's fixed defaults.
    profile = Path(config_path)
    header = "[profiles.apollo-work]\n"
    contents = profile.read_text()
    assert contents.count(header) == 1
    profile.write_text(contents.replace(header, header + 'base_url = "http://127.0.0.1:18080/api/v1"\n', 1))
    for command in commands:
        run([*cli, "--profile", "apollo-work", "apollo", *command], direct)
    assert [item["path"] for item in requests] == [
        "/api/v1/users/api_profile",
        "/api/v1/users/api_profile",
        "/v1/auth/health",
    ], requests
    assert all(item["key"] == "apollo-provider-secret" and item["auth"] is None for item in requests), requests
    stored = run([*cli, "secrets", "list"], direct).stdout
    assert "apollo.api_token" in stored and "github.token" in stored

    requests.clear()
    isolated = install("isolated")
    assert "AAI_SECRET_APOLLO_API_TOKEN" not in isolated
    assert "apollo-provider-secret" not in json.dumps(artifacts["isolated"])
    stored = run([*cli, "secrets", "list"], isolated).stdout
    assert "apollo.api_token" not in stored and "github.token" in stored
    for command in commands:
        run([*cli, "--profile", "apollo-work", "apollo", *command], isolated)
    assert [item["path"] for item in requests] == [
        "/gateway/v1/p/apollo/api/v1/users/api_profile",
        "/gateway/v1/p/apollo/api/v1/users/api_profile",
        "/gateway/v1/p/apollo/v1/auth/health",
    ], requests
    assert all(item["auth"] == "Bearer agt_apollo_fixture" and item["key"] is None for item in requests), requests
    isolated_count = len(requests)
    missing = {key: value for key, value in isolated.items() if key != "AF_GATEWAY_TOKEN_APOLLO"}
    missing["AAI_API_TOKEN"] = "unrelated-fallback"
    run([*cli, "--profile", "apollo-work", "apollo", "users", "me"], missing, success=False)
    assert requests[-1]["auth"] != "Bearer agt_apollo_fixture", requests
    install("isolated")
    restored = install("direct")
    assert "apollo.api_token" in run([*cli, "secrets", "list"], restored).stdout
    print(json.dumps({"isolated_requests": isolated_count, "uid": os.getuid()}))
finally:
    server.shutdown()
