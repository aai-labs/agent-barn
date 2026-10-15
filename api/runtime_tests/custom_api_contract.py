"""Consume materialized Custom API profiles with each image's installed aai-cli."""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from hamcrest import assert_that, equal_to, has_entries

from api.domains.custom_api.models import CustomApiConnection
from api.domains.custom_api.runtime import materialize_custom_api
from api.infrastructure.crypto import encrypt_token
from api.tests.steps.agent import TEST_ENCRYPTION_KEY

FIXTURE = """
import http.server, json, os, subprocess, threading
from pathlib import Path
root = Path('/tmp/custom-api-contract')
root.mkdir()
config = root / '.config/aai-cli/config.toml'
env = dict(os.environ)
class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert self.headers.get('Authorization') == 'Bearer fixture-runtime-token'
        body = json.dumps({'status': 200, 'body': request}).encode()
        self.send_response(200); self.end_headers(); self.wfile.write(body)
    def log_message(self, *args): pass
server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
fixture = json.loads(Path('/app/config/artifacts.json').read_text())
for stage in ('direct', 'isolated', 'removed'):
    artifacts = fixture[stage]
    config_text = artifacts['config'].replace('GATEWAY_PORT', str(server.server_port))
    mounted = root / 'mounted.toml'
    mounted.write_text(config_text)
    script = artifacts['setup'].replace('/app/config/aai-cli-config.toml', str(mounted))
    installed = subprocess.run(['sh', '-c', 'set -eu; umask 077; ' + script],
        env=dict(env, **artifacts['env']), text=True, capture_output=True)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    keys = subprocess.run(['aai-cli', '--config', str(config), 'secrets', 'list'],
        env=env, text=True, capture_output=True)
    assert keys.returncode == 0, keys.stdout + keys.stderr
    keys = json.loads(keys.stdout)['keys']
    if stage == 'direct':
        assert len(keys) == 1, keys
    elif stage == 'isolated':
        assert len(keys) == 1 and keys[0].endswith('.gateway'), keys
        request = {'method':'POST','url':'https://api.example.com:8443/v1/items',
                   'query':{'limit':3},'body':{'name':'item'}}
        command = ['aai-cli', '--config', str(config), '--profile', 'custom-api-inventory',
                   'custom-api', 'request', '--request-json', '-']
        result = subprocess.run(command, input=json.dumps(request), env=env,
            text=True, capture_output=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)['body']['url'] == request['url'], result.stdout
        request['url'] = '/relative'
        refused = subprocess.run(command, input=json.dumps(request), env=env,
            text=True, capture_output=True)
        assert refused.returncode != 0 and 'fixture-runtime-token' not in refused.stdout
    else:
        assert keys == [], keys
server.shutdown()
print(json.dumps({'cli':'ok','absolute_urls':'required','runtime_user':os.getuid()}))
"""


def custom_api_should_run(runtime: str, root: Path) -> None:
    image = os.environ.get(f"{runtime.upper()}_TEST_IMAGE")
    if not image:
        pytest.fail(f"{runtime.upper()}_TEST_IMAGE must name a built runtime image")
    row = CustomApiConnection(
        id=uuid4(),
        agent_id=uuid4(),
        slug="inventory",
        name="Inventory",
        base_url="https://api.example.com:8443/v1",
        credentials_encrypted=encrypt_token(
            json.dumps({"auth": {"type": "bearer", "token": "fixture-direct-token"}}), TEST_ENCRYPTION_KEY
        ),
    )
    fixtures = {}
    for stage in ("direct", "isolated", "removed"):
        row.isolated = stage == "isolated"
        artifacts = materialize_custom_api(
            [] if stage == "removed" else [row],
            TEST_ENCRYPTION_KEY,
            "http://127.0.0.1:GATEWAY_PORT",
            Mock(),
            home_dir="/tmp/custom-api-contract",
        )
        env = artifacts.env
        if stage == "isolated":
            env = {name: "fixture-runtime-token" for name in env}
        store = "/tmp/custom-api-contract/.config/aai-cli"
        fixtures[stage] = {
            "config": f'secrets_file = "{store}/aai-secrets.enc.json"\nkey_file = "{store}/key"\n'
            + artifacts.files["custom-api-profiles.toml"],
            "setup": artifacts.files["custom-api-setup.sh"],
            "env": env,
        }
    for name, source in {"custom-api-fixture.py": FIXTURE, "artifacts.json": json.dumps(fixtures)}.items():
        (root / name).write_text(source)
        (root / name).chmod(0o644)
    root.chmod(0o755)
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--mount",
            f"type=bind,src={root},dst=/app/config,readonly",
            "--entrypoint",
            "python3",
            image,
            "/app/config/custom-api-fixture.py",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert_that(result.returncode, equal_to(0), result.stdout + result.stderr)
    parsed = json.loads(result.stdout)
    assert_that(parsed, has_entries(cli="ok", absolute_urls="required"))
    assert_that(parsed["runtime_user"] != 0, equal_to(True))
