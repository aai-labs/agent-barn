"""Brokered gog must survive Hermes' real login-shell environment snapshot."""

import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from hamcrest import assert_that, equal_to

from api.domains.agents.builders.hermes import build_hermes_config_map, build_hermes_gateway_config
from api.domains.agents.models import SecretProvider
from api.domains.integrations.plugins.base import EgressMode
from api.domains.integrations.runtime import RuntimeBinding, RuntimeContext, materialize_integrations
from api.tests.helpers.integration_credentials import credential_for

_PROBE = """
import json
from tools.environments.local import LocalEnvironment

environment = LocalEnvironment(cwd="/tmp", timeout=20)
try:
    resolved = environment.execute("command -v gog")
    assert resolved["output"].strip() == "/home/hermes/.local/bin/gog", resolved
    for _ in range(2):
        result = environment.execute("gog calendar events primary --json")
        assert "Using direct access token" in result["output"], result
        assert "www.googleapis.com/calendar" in result["output"], result
        assert "No tokens stored" not in result["output"], result
    assert environment.execute('test -z "${GOG_ACCESS_TOKEN:-}"')["returncode"] == 0
    with open("/tmp/broker-calls") as calls:
        assert len(calls.readlines()) == 2
    print(json.dumps({"broker_calls": 2}))
finally:
    environment.cleanup()
"""


def test_hermes_terminal_fetches_google_authorization_on_every_command(tmp_path: Path):
    tmp_path.chmod(0o755)
    image = os.environ.get("HERMES_TEST_IMAGE")
    if not image:
        pytest.fail("HERMES_TEST_IMAGE must name an already-built Hermes image")
    content = credential_for(SecretProvider.GOOGLE_WORKSPACE)
    artifacts = materialize_integrations(
        [RuntimeBinding(SecretProvider.GOOGLE_WORKSPACE, content, EgressMode.TOKEN_BROKER)],
        RuntimeContext(
            home_dir="/opt/data",
            gog_home_dir="/home/hermes",
            gateway_base_url="http://fixture/gateway/v1",
            gateway_tokens={SecretProvider.GOOGLE_WORKSPACE: "fixture-gateway-token"},
        ),
    )
    config = build_hermes_config_map(
        uuid4(),
        uuid4(),
        "fixture",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        build_hermes_gateway_config("litellm/fixture", "http://fixture"),
        gog_setup_sh=artifacts.files["gog-setup.sh"],
        gog_shim_sh=artifacts.files["gog-shim.sh"],
    )
    for name, value in config.data.items():
        (tmp_path / name).write_text(value)
    (tmp_path / "probe.py").write_text(_PROBE)
    (tmp_path / "curl").write_text(
        '#!/bin/sh\nset -eu\necho call >> /tmp/broker-calls\nprintf \'{"access_token":"fixture-access-token"}\\n\'\n'
    )
    environment_file = tmp_path / "fixture.env"
    environment_file.write_text("".join(f"{key}={value}\n" for key, value in artifacts.env.items()))
    environment_file.chmod(0o600)
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--env-file",
            str(environment_file),
            "--mount",
            f"type=bind,src={tmp_path},dst=/app/config,readonly",
            "--entrypoint",
            "/bin/sh",
            image,
            "-c",
            (
                "set -e\ncp /app/config/hermes-config.yaml /opt/data/config.yaml\n"
                "sh /app/config/gog-setup.sh\n"
                "cp /app/config/curl /home/hermes/.local/bin/curl\n"
                "chmod 755 /home/hermes/.local/bin/curl\n"
                'export PATH="/home/hermes/.local/bin:$PATH" PYTHONPATH=/opt/hermes\n'
                "/opt/hermes/.venv/bin/python /app/config/probe.py"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert_that(result.returncode, equal_to(0), result.stdout + result.stderr)
