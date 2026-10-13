"""Offline real-image Apollo direct/isolated routing and store cleanup contract."""

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
            gateway_tokens={SecretProvider.APOLLO: "agt_apollo_fixture"},
        )
        payload = {"home": home, "store": store}
        for name, mode in (("direct", EgressMode.DIRECT), ("isolated", EgressMode.GATEWAY_PROXY)):
            payload[name] = asdict(
                materialize_integrations(
                    [
                        RuntimeBinding(SecretProvider.APOLLO, credential_for(SecretProvider.APOLLO), mode),
                        RuntimeBinding(SecretProvider.GITHUB, credential_for(SecretProvider.GITHUB), EgressMode.DIRECT),
                    ],
                    selected,
                )
            )
        (root / "artifacts.json").write_text(json.dumps(payload))
        (root / "config").mkdir(mode=0o777)
        (root / "config").chmod(0o777)
        root.chmod(0o755)

    return step


def apollo_should_route(runtime: str, root: Path) -> None:
    with given([_prepare(runtime, root)]) as context:
        with when("generated setup and real Apollo commands run without external networking"):
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
                    f"type=bind,src={Path(__file__).parent / 'fixtures/apollo_driver.py'},dst=/driver.py,readonly",
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
        with then("both routes preserve auth, API prefixes and persistent-store cleanup"):
            assert_that(result.returncode, equal_to(0), result.stdout + result.stderr)
            assert_that(json.loads(result.stdout)["isolated_requests"], equal_to(3))
