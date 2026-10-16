"""Offline real-image contract for Gmail read with an app password.

The pod gets an aai-cli Custom API profile that holds no credential, plus its gateway
token. This installs the generated aai-cli artifacts inside the real runtime image, runs
the exact commands the agent is told to use against a stub gateway on localhost with
networking disabled, and checks what reached the gateway: the complete request objects,
carrying only the gateway token.
"""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
from hamcrest import assert_that, contains_string, equal_to, is_not

from api.domains.agents.models import SecretProvider
from api.domains.integrations.plugins.base import EgressMode
from api.domains.integrations.plugins.providers import GMAIL_SERVED_BASE_URL
from api.domains.integrations.runtime import RuntimeBinding, RuntimeContext, materialize_integrations
from api.tests.core.givenpy import given, then, when
from api.tests.helpers.integration_credentials import credential_for

_PROVIDER = SecretProvider.GMAIL_APP_PASSWORD
_TOKEN = "agt-mail-fixture"


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
            gateway_tokens={_PROVIDER: _TOKEN},
        )
        artifacts = materialize_integrations(
            [RuntimeBinding(_PROVIDER, credential_for(_PROVIDER), EgressMode.GATEWAY_SERVED)], selected
        )
        # The commands come from the agent's own instructions, so the contract fails if
        # what the agent is told stops working in the image.
        commands = re.findall(r"`(aai-cli --profile gmail-inbox [^`]+)`", artifacts.policy_md)
        context.commands = commands
        (root / "artifacts.json").write_text(
            json.dumps(
                {
                    "home": home,
                    "env": artifacts.env,
                    "files": artifacts.files,
                    "commands": commands,
                    "policy": artifacts.policy_md,
                }
            )
        )
        (root / "config").mkdir(mode=0o777)
        (root / "config").chmod(0o777)
        root.chmod(0o755)

    return step


def gmail_should_be_read_through_the_gateway(runtime: str, root: Path) -> None:
    with given([_prepare(runtime, root)]) as context:
        assert_that(len(context.commands), equal_to(2), "the agent must be told how to list and read")

        with when("aai-cli runs the instructed list and read commands without external networking"):
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

        with then("only the complete request objects reached the gateway, with only the gateway token"):
            assert_that(result.returncode, equal_to(0), result.stdout + result.stderr)
            observed = json.loads(result.stdout)
            assert_that(observed["uid"], is_not(equal_to(0)))
            assert_that(observed["listed"], equal_to({"status": 200, "body": {"messages": [{"id": "7"}]}}))
            assert_that(observed["read"], equal_to({"status": 200, "body": {"id": "7"}}))
            requests = observed["requests"]
            assert_that([r["path"] for r in requests], equal_to(["/gateway/v1/custom-api/request"] * 2))
            assert_that({r["auth"] for r in requests}, equal_to({f"Bearer {_TOKEN}"}))
            assert_that(
                [(r["json"]["method"], r["json"]["url"]) for r in requests],
                equal_to(
                    [("GET", f"{GMAIL_SERVED_BASE_URL}/messages"), ("GET", f"{GMAIL_SERVED_BASE_URL}/messages/7")]
                ),
            )
            assert_that(requests[0]["json"]["query"], equal_to({"q": "from:alice newer_than:7d", "limit": "5"}))
            # Without its gateway token the profile fails closed rather than calling anywhere.
            assert_that(observed["without_token_exit"], is_not(equal_to(0)))
            assert_that(observed["requests_without_token"], equal_to(0))


_HERMES_SCAN = (
    "import sys; sys.path.insert(0, '/opt/hermes'); "
    "from agent.prompt_builder import _scan_context_content; "
    "print(_scan_context_content(open('/contract/policy.md').read(), 'AGENTS.md'))"
)


def gmail_instructions_should_load_in_hermes(root: Path) -> None:
    """Hermes drops a whole AGENTS.md its injection scanner flags, every other instruction
    included, so the generated Gmail block must pass the image's own scanner."""
    with given([_prepare("hermes", root)]) as context:
        (root / "policy.md").write_text(json.loads((root / "artifacts.json").read_text())["policy"])

        with when("the image's context-file scanner reads the generated instructions"):
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--pull=never",
                    "--network=none",
                    "--mount",
                    f"type=bind,src={root},dst=/contract,readonly",
                    "--entrypoint",
                    "python3",
                    context.image,
                    "-c",
                    _HERMES_SCAN,
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

        with then("they load unchanged"):
            assert_that(result.returncode, equal_to(0), result.stderr)
            assert_that(result.stdout, is_not(contains_string("BLOCKED")))
            assert_that(result.stdout, contains_string("aai-cli --profile gmail-inbox custom-api request"))
