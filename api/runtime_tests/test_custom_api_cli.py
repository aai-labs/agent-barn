"""Consume Barn's generated profiles and startup reconciliation with the real CLI."""

import hashlib
import json
import os
import shutil
import subprocess
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from hamcrest import assert_that, contains_string, equal_to, has_length, not_

from api.domains.custom_api.models import CustomApiConnection
from api.domains.custom_api.runtime import materialize_custom_api
from api.infrastructure.crypto import encrypt_token
from api.tests.steps.agent import TEST_ENCRYPTION_KEY


def _binary() -> str:
    path = os.environ.get("AAI_CLI_TEST_BINARY") or shutil.which("aai-cli")
    if not path:
        pytest.fail("Custom API runtime contracts require AAI_CLI_TEST_BINARY or aai-cli on PATH")
    return str(Path(path).resolve())


def _connection(slug: str = "inventory", isolated: bool = False) -> CustomApiConnection:
    return CustomApiConnection(
        id=uuid4(),
        agent_id=uuid4(),
        slug=slug,
        name="Inventory",
        base_url="https://api.example.com:8443/v1",
        isolated=isolated,
        credentials_encrypted=encrypt_token(
            json.dumps(
                {
                    "auth": {"type": "bearer", "token": "fixture-direct-token"},
                    "headers": [
                        {"name": "X-Secret", "value": "fixture-secret-header", "secret": True},
                        {"name": "X-Optional", "value": "", "secret": False},
                    ],
                }
            ),
            TEST_ENCRYPTION_KEY,
        ),
    )


def _install(root: Path, rows: list[CustomApiConnection], gateway: str = "http://gateway.test"):
    artifacts = materialize_custom_api(rows, TEST_ENCRYPTION_KEY, gateway, Mock(), uuid4(), home_dir=str(root))
    config = root / "mounted-config.toml"
    store = root / ".config/aai-cli"
    config.write_text(
        f'secrets_file = "{store}/aai-secrets.enc.json"\nkey_file = "{store}/key"\n'
        + artifacts.files["custom-api-profiles.toml"]
    )
    executable_dir = root / "bin"
    executable_dir.mkdir(exist_ok=True)
    binary = executable_dir / "aai-cli"
    if not binary.exists():
        binary.symlink_to(_binary())
    env = {**os.environ, **artifacts.env, "PATH": f"{executable_dir}:{os.environ['PATH']}"}
    script = artifacts.files["custom-api-setup.sh"].replace("/app/config/aai-cli-config.toml", str(config))
    result = subprocess.run(
        ["sh", "-c", "set -eu\numask 077\n" + script], env=env, capture_output=True, text=True, check=False
    )
    assert_that(result.returncode, equal_to(0), result.stdout + result.stderr)
    return artifacts, store / "config.toml"


def _run(config: Path, *args: str, request: dict | None = None):
    # No pod credential environment reaches this terminal command.
    return subprocess.run(
        [_binary(), "--config", str(config), *args],
        input=json.dumps(request) if request else None,
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
    )


def test_real_cli_reconciles_direct_credentials_on_isolation_and_removal(tmp_path: Path):
    row = _connection()
    artifacts, config = _install(tmp_path, [row])
    assert_that(json.dumps(artifacts.files), not_(contains_string("fixture-direct-token")))
    assert_that(json.dumps(artifacts.files), not_(contains_string("fixture-secret-header")))
    profiles = tomllib.loads(config.read_text())["profiles"]
    assert_that(profiles["custom-api-inventory"]["auth_type"], equal_to("bearer_token"))
    assert_that(profiles["custom-api-inventory"]["headers"][1]["value"], equal_to(""))
    keys = _run(config, "secrets", "list")
    assert_that(keys.returncode, equal_to(0), keys.stderr)
    assert_that(json.loads(keys.stdout)["keys"], has_length(2))
    seeded = _run(config, "secrets", "set", "jira.api_token", "--value", "fixture-built-in-token")
    assert_that(seeded.returncode, equal_to(0), seeded.stderr)
    row.isolated = True
    isolated, config = _install(tmp_path, [row])
    assert_that("fixture-direct-token" in isolated.env.values(), equal_to(False))
    keys = json.loads(_run(config, "secrets", "list").stdout)["keys"]
    assert_that(keys, equal_to([f"custom-api.{row.id.hex}.gateway", "jira.api_token"]))
    _, config = _install(tmp_path, [])
    assert_that(json.loads(_run(config, "secrets", "list").stdout)["keys"], equal_to(["jira.api_token"]))
    missing = _run(
        config,
        "--profile",
        "custom-api-inventory",
        "custom-api",
        "request",
        "--url",
        "https://api.example.com:8443/v1/items",
    )
    assert_that(missing.returncode == 0, equal_to(False))


def test_real_cli_uses_generation_token_from_materialized_store_without_environment(tmp_path: Path):
    requests: list[dict] = []
    auth: list[str | None] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            auth.append(self.headers.get("Authorization"))
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps({"status": 200, "body": {"items": ["fixture-item"]}}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        row = _connection(isolated=True)
        _, config = _install(tmp_path, [row], f"http://127.0.0.1:{server.server_port}")
        request = {"method": "POST", "url": row.base_url + "/items", "query": {"limit": 3}, "body": {"name": "item"}}
        result = _run(
            config, "--profile", "custom-api-inventory", "custom-api", "request", "--request-json", "-", request=request
        )
        assert_that(result.returncode, equal_to(0), result.stdout + result.stderr)
        assert_that(json.loads(result.stdout), equal_to({"status": 200, "body": {"items": ["fixture-item"]}}))
        assert_that(requests[0]["url"], equal_to(request["url"]))
        assert_that(requests[0]["body"], equal_to(request["body"]))
        authorization = auth[0]
        assert authorization is not None
        token = authorization.removeprefix("Bearer ")
        assert_that(hashlib.sha256(token.encode()).hexdigest(), equal_to(row.token_hash))
        refused = _run(config, "--profile", "custom-api-inventory", "custom-api", "request", "--url", "/relative")
        assert_that(refused.returncode == 0, equal_to(False))
        assert_that(requests, has_length(1))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
