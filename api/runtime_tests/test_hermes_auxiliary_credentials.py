"""Every Hermes LLM call must reach the in-pod proxy with the runtime's LiteLLM key.

A generated config alone cannot show this: whether Hermes sends the key depends on which
of its resolvers a task goes through, and only the image can answer that. The pin list
once covered two tasks that resolve their key the other way, and their calls went out
with a placeholder key that LiteLLM rejected.
"""

import json
import os
import subprocess
from pathlib import Path
from uuid import UUID

import pytest
import yaml
from hamcrest import assert_that, equal_to

from api.domains.agents.builders.hermes import (
    _HERMES_AUXILIARY_TASKS,
    _HERMES_RUNTIME_INHERITING_TASKS,
    build_hermes_gateway_config,
    build_secret_hermes_runtime,
)
from api.tests.core.givenpy import given, then, when

_PROXY = "http://localhost:8090"
_MODEL = "litellm/openrouter/z-ai/glm-5.2"
_DRIVER = Path(__file__).parent / "fixtures/hermes_auxiliary_credentials_driver.py"


def _runtime_is_configured(root: Path):
    def step(context) -> None:
        context.image = os.environ.get("HERMES_TEST_IMAGE")
        if not context.image:
            pytest.fail("HERMES_TEST_IMAGE must name an already-built Hermes image")
        secret = build_secret_hermes_runtime(
            UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
            UUID("11111111-2222-3333-4444-555555555555"),
            "agent-farm",
            "Contract Agent",
            runtime_api_key="runtime-api-contract",
            litellm_api_key="sk-litellm-contract",
            litellm_base_url=_PROXY,
        )
        context.env = {name: value for name, value in (secret.string_data or {}).items() if value is not None}
        (root / "config.yaml").write_text(yaml.safe_dump(build_hermes_gateway_config(_MODEL, _PROXY)))
        (root / "tasks.json").write_text(json.dumps([*_HERMES_AUXILIARY_TASKS, *_HERMES_RUNTIME_INHERITING_TASKS]))
        root.chmod(0o755)
        for path in root.iterdir():
            path.chmod(0o644)

    return step


def test_every_hermes_llm_call_resolves_the_runtime_litellm_key(tmp_path: Path):
    with given([_runtime_is_configured(tmp_path)]) as context:
        with when("Hermes resolves credentials for its main model and every auxiliary task"):
            env_flags = [flag for name, value in context.env.items() for flag in ("--env", f"{name}={value}")]
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--pull=never",
                    "--network=none",
                    *env_flags,
                    "--mount",
                    f"type=bind,src={tmp_path},dst=/contract,readonly",
                    "--mount",
                    f"type=bind,src={_DRIVER},dst=/driver.py,readonly",
                    "--entrypoint",
                    "python3",
                    context.image,
                    "/driver.py",
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        with then("each one sends the LiteLLM key, not a placeholder"):
            assert_that(result.returncode, equal_to(0), result.stdout + result.stderr)
            report = json.loads(result.stdout.strip().splitlines()[-1])
            assert_that(report["main"], equal_to("runtime_key"))
            without_key = sorted(task for task, key in report["tasks"].items() if key != "runtime_key")
            assert_that(without_key, equal_to([]))
