"""Offline real-image Gmail contract: the generated aai-cli setup wires the credential.

Google's token endpoint is compiled into aai-cli, so an offline run cannot fake Google.
It proves everything up to that call instead: the generated setup stores both Gmail
secrets, the generated profile validates, and a Gmail command resolves them and starts
the token refresh. Removing the refresh token turns that into a missing-credentials
error, which is what tells the two apart.
"""

import json
import os
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest
from hamcrest import assert_that, equal_to

from api.domains.agents.models import SecretProvider
from api.domains.integrations.plugins.base import EgressMode
from api.domains.integrations.runtime import RuntimeBinding, RuntimeContext, materialize_integrations
from api.tests.core.givenpy import given, then, when
from api.tests.helpers.integration_credentials import credential_for


def _prepare(runtime: str, root: Path):
    def step(context):
        context.image = os.environ.get(f"{runtime.upper()}_TEST_IMAGE")
        if not context.image:
            pytest.fail(f"{runtime.upper()}_TEST_IMAGE must name a rebuilt runtime image")
        home = "/opt/data" if runtime == "hermes" else "/home/node"
        store = f"{home}/.config/aai-cli" if runtime == "hermes" else "/home/node/.openclaw/aai-cli"
        selected = RuntimeContext(
            home_dir=home,
            gog_home_dir=home,
            store_dir=store,
            gateway_base_url="http://127.0.0.1:18080/gateway/v1",
            gateway_tokens={},
        )
        artifacts = materialize_integrations(
            [RuntimeBinding(SecretProvider.GMAIL, credential_for(SecretProvider.GMAIL), EgressMode.DIRECT)],
            selected,
        )
        (root / "artifacts.json").write_text(json.dumps({"home": home, "direct": asdict(artifacts)}))
        (root / "config").mkdir(mode=0o777)
        (root / "config").chmod(0o777)
        root.chmod(0o755)

    return step


def gmail_should_be_wired(runtime: str, root: Path) -> None:
    with given([_prepare(runtime, root)]) as context:
        with when("generated setup and a real Gmail command run without external networking"):
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--pull=never",
                    "--network=none",
                    "--mount",
                    f"type=bind,src={root},dst=/contract,readonly",
                    "--mount",
                    f"type=bind,src={root / 'config'},dst=/app/config",
                    "--mount",
                    f"type=bind,src={Path(__file__).parent / 'fixtures/gmail_driver.py'},dst=/driver.py,readonly",
                    "--entrypoint",
                    "python3",
                    context.image,
                    "/driver.py",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        with then("the stored credential reaches the Google token refresh"):
            assert_that(result.returncode, equal_to(0), result.stdout + result.stderr)
            assert_that(json.loads(result.stdout)["refresh_attempted"], equal_to(True))
