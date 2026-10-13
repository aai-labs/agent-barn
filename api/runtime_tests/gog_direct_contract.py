"""Prove the generated direct credential setup is consumed by the pinned gog binary."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from hamcrest import assert_that, equal_to

from api.domains.agents.models import SecretProvider
from api.domains.integrations.plugins.base import EgressMode
from api.domains.integrations.runtime import RuntimeBinding, RuntimeContext, materialize_integrations
from api.tests.core.givenpy import given, then, when
from api.tests.helpers.integration_credentials import credential_for


def direct_google_is_materialized(runtime: str, root: Path):
    def step(context) -> None:
        image_variable = f"{runtime.upper()}_TEST_IMAGE"
        image = os.environ.get(image_variable)
        if not image:
            pytest.fail(f"{image_variable} must name an already-built {runtime} image")
        subprocess.run(["docker", "image", "inspect", image], capture_output=True, check=True)
        home = "/home/hermes" if runtime == "hermes" else "/home/node"
        content = credential_for(SecretProvider.GOOGLE_WORKSPACE)
        artifacts = materialize_integrations(
            [RuntimeBinding(SecretProvider.GOOGLE_WORKSPACE, content, EgressMode.DIRECT)],
            RuntimeContext(home_dir="/opt/data" if runtime == "hermes" else home, gog_home_dir=home),
        )
        context.image = image
        context.script = root / "gog-setup.sh"
        context.script.write_text(artifacts.files["gog-setup.sh"])
        context.script.chmod(0o644)
        context.env_file = root / "gog.env"
        context.env_file.write_text("".join(f"{key}={value}\n" for key, value in artifacts.env.items()))
        context.env_file.chmod(0o600)

    return step


def import_and_list_tokens(context) -> dict:
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--env-file",
            str(context.env_file),
            "--mount",
            f"type=bind,src={context.script},dst=/app/config/gog-setup.sh,readonly",
            "--entrypoint",
            "/bin/sh",
            context.image,
            "-c",
            (
                "set -e\nsh /app/config/gog-setup.sh >/dev/null\n"
                "/usr/local/bin/gog auth tokens export fixture@example.com --out /tmp/gog-contract-token.json >/dev/null\n"
                "cat /tmp/gog-contract-token.json"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert_that(result.returncode, equal_to(0), result.stderr)
    return json.loads(result.stdout)


def direct_google_should_import(runtime: str, root: Path) -> None:
    with given([direct_google_is_materialized(runtime, root)]) as context:
        with when("the real gog binary imports the generated client and renewable grant without network access"):
            imported = import_and_list_tokens(context)
        with then("gog can read the imported account back from its encrypted keyring"):
            assert_that(imported["email"], equal_to("fixture@example.com"))
            assert_that(imported["refresh_token"], equal_to("google_workspace-provider-secret"))
            assert_that(imported["services"], equal_to(["gmail"]))
