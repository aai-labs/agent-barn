"""Offline real-image contract for Gmail read with an app password.

The pod gets only a helper script and its gateway token. This runs the generated helper
inside the real runtime image against a stub gateway on localhost, with networking
disabled, and checks what reached the gateway: the list and read requests, carrying the
gateway token, and nothing for an operation the helper does not offer.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest
from hamcrest import assert_that, equal_to, is_not

from api.domains.agents.models import SecretProvider
from api.domains.credential_gateway.models import gateway_token_env_var
from api.domains.integrations.plugins.base import EgressMode
from api.domains.integrations.runtime import RuntimeBinding, RuntimeContext, materialize_integrations
from api.tests.core.givenpy import given, then, when
from api.tests.helpers.integration_credentials import credential_for

_PROVIDER = SecretProvider.GMAIL_APP_PASSWORD


def _prepare(runtime: str, root: Path):
    def step(context):
        context.image = os.environ.get(f"{runtime.upper()}_TEST_IMAGE")
        if not context.image:
            pytest.fail(f"{runtime.upper()}_TEST_IMAGE must name a rebuilt runtime image")
        home = "/opt/data" if runtime == "hermes" else "/home/node"
        selected = RuntimeContext(
            home_dir=home,
            gog_home_dir=home,
            gateway_base_url="http://127.0.0.1:18080/gateway/v1",
            gateway_tokens={_PROVIDER: "agt-mail-fixture"},
        )
        artifacts = materialize_integrations(
            [RuntimeBinding(_PROVIDER, credential_for(_PROVIDER), EgressMode.GATEWAY_SERVED)], selected
        )
        (root / "artifacts.json").write_text(
            json.dumps(
                {"home": home, "env": artifacts.env, "files": {"gmail-read.sh": artifacts.files["gmail-read.sh"]}}
            )
        )
        (root / "config").mkdir(mode=0o777)
        (root / "config").chmod(0o777)
        root.chmod(0o755)

    return step


def gmail_should_be_read_through_the_gateway(runtime: str, root: Path) -> None:
    with given([_prepare(runtime, root)]) as context:
        with when("the generated helper lists and reads mail without external networking"):
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
                    f"type=bind,src={Path(__file__).parent / 'fixtures/gmail_app_password_driver.py'},dst=/driver.py,readonly",
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
        with then("only the list and read requests reached the gateway, with the gateway token"):
            assert_that(result.returncode, equal_to(0), result.stdout + result.stderr)
            observed = json.loads(result.stdout)
            assert_that(observed["uid"], is_not(equal_to(0)))
            assert_that(observed["listed"], equal_to({"messages": [{"id": "7"}]}))
            assert_that(observed["read"], equal_to({"id": "7"}))
            assert_that(observed["refused_exit"], equal_to(2))
            assert_that(
                observed["requests"],
                equal_to(
                    [
                        {
                            "path": "/gateway/v1/mail/messages",
                            "query": {"limit": ["20"], "q": ["from:alice newer_than:7d"]},
                            "auth": "Bearer agt-mail-fixture",
                        },
                        {"path": "/gateway/v1/mail/messages/7", "query": {}, "auth": "Bearer agt-mail-fixture"},
                    ]
                ),
            )
            assert_that(gateway_token_env_var(_PROVIDER) in result.stdout, equal_to(False))
