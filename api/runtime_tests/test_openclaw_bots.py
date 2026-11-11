import json
import subprocess
from pathlib import Path
from uuid import UUID

import pytest
from hamcrest import assert_that, contains_inanyorder, equal_to, has_entries

from api.domains.agents.builders import build_openclaw_gateway_config, native_telegram_channel
from api.domains.agents.builders.openclaw import OpenClawBot, multi_agent_gateway_config
from api.runtime_tests.memory_helpers import selected_image

REPO = Path(__file__).resolve().parents[2]
CHECK_SCRIPT = Path(__file__).parent / "fixtures" / "openclaw_bots_check.sh"
PLUGINS = REPO / "api" / "domains" / "agents" / "scripts" / "openclaw" / "plugins"
PROXY = "http://localhost:8090"
BOT_A = UUID("0000000a-0000-4000-8000-00000000000a")
BOT_B = UUID("0000000b-0000-4000-8000-00000000000b")
STATE = "/home/node/.openclaw"


@pytest.fixture
def openclaw_image() -> str:
    return selected_image("openclaw")


def _parent() -> dict:
    channels = {"telegram": native_telegram_channel({"dm_policy": "allowlist", "allowed_user_ids": ["111"]})}
    return build_openclaw_gateway_config("litellm/gpt-5", PROXY, channels, memory_enabled=True)


def _bots() -> list[OpenClawBot]:
    telegram = {"telegram": native_telegram_channel({"dm_policy": "open"})}
    return [
        OpenClawBot(BOT_A, 1, build_openclaw_gateway_config("litellm/gpt-5-mini", PROXY, telegram)),
        OpenClawBot(BOT_B, 2, build_openclaw_gateway_config("litellm/gpt-5-nano", PROXY, {})),
    ]


def _check(image: str, root: Path, config: dict, keys: dict[UUID, dict]) -> dict:
    inputs, outputs = root / "in", root / "out"
    (inputs / "keys").mkdir(parents=True)
    outputs.mkdir()
    outputs.chmod(0o777)
    (inputs / "openclaw.json").write_text(json.dumps(config))
    for bot_id, values in keys.items():
        (inputs / "keys" / f"{bot_id}.json").write_text(json.dumps(values))
    completed = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            f"{inputs}:/in:ro",
            "-v",
            f"{outputs}:/out",
            "-v",
            f"{PLUGINS}:/plugins:ro",
            "-v",
            f"{CHECK_SCRIPT}:/check.sh:ro",
            "--entrypoint",
            "sh",
            image,
            "/check.sh",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=110,
    )
    assert_that(completed.returncode, equal_to(0), completed.stdout + completed.stderr)
    return {
        name: json.loads((outputs / f"{name}.json").read_text() or "null") for name in ("validate", "agents", "audit")
    }


def _keys(*bot_ids: UUID) -> dict[UUID, dict]:
    return {bot_id: {"LITELLM_API_KEY": f"sk-{bot_id}", "TELEGRAM_BOT_TOKEN": f"1:{bot_id}"} for bot_id in bot_ids}


def _unresolved(audit: dict) -> list[str]:
    return [finding["jsonPath"] for finding in audit["findings"] if finding["code"] == "REF_UNRESOLVED"]


def test_a_parent_without_bots_keeps_a_valid_single_agent_config(openclaw_image: str, tmp_path: Path):
    result = _check(openclaw_image, tmp_path, multi_agent_gateway_config(_parent(), []), {})

    assert_that(result["validate"], has_entries(valid=True))
    assert_that([agent["id"] for agent in result["agents"]], equal_to(["main"]))


def test_a_parent_with_bots_runs_each_bot_as_its_own_agent(openclaw_image: str, tmp_path: Path):
    config = multi_agent_gateway_config(_parent(), _bots())

    result = _check(openclaw_image, tmp_path, config, _keys(BOT_A, BOT_B))

    assert_that(result["validate"], has_entries(valid=True, warnings=[]))
    agents = {agent["id"]: agent for agent in result["agents"]}
    assert_that(list(agents), contains_inanyorder("main", str(BOT_A), str(BOT_B)))
    assert_that(agents["main"], has_entries(model="litellm/gpt-5", bindingDetails=["telegram accountId=default"]))
    assert_that(
        agents[str(BOT_A)],
        has_entries(
            workspace=f"{STATE}/workspace-{BOT_A}",
            agentDir=f"{STATE}/agents/{BOT_A}/agent",
            model="litellm-bot-1/gpt-5-mini",
            bindingDetails=[f"telegram accountId={BOT_A}"],
        ),
    )
    assert_that(agents[str(BOT_B)], has_entries(model="litellm-bot-2/gpt-5-nano", bindings=0))
    assert_that(result["audit"]["resolution"]["refsChecked"], equal_to(3))
    assert_that(_unresolved(result["audit"]), equal_to([]))


def test_a_bot_whose_key_file_is_missing_is_the_only_one_unresolved(openclaw_image: str, tmp_path: Path):
    config = multi_agent_gateway_config(_parent(), _bots())

    result = _check(openclaw_image, tmp_path, config, _keys(BOT_A))

    assert_that(_unresolved(result["audit"]), equal_to(["models.providers.litellm-bot-2.apiKey"]))
