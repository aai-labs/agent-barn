import json
import shutil
import subprocess
from pathlib import Path
from uuid import UUID

import pytest
from hamcrest import assert_that, contains_inanyorder, contains_string, equal_to, has_entries

from api.domains.agents.builders import build_openclaw_gateway_config, native_telegram_channel
from api.domains.agents.builders.openclaw import OpenClawBot, multi_agent_gateway_config
from api.runtime_tests.memory_helpers import selected_image

REPO = Path(__file__).resolve().parents[2]
CHECK_SCRIPT = Path(__file__).parent / "fixtures" / "openclaw_bots_check.sh"
BOOT_SCRIPT = Path(__file__).parent / "fixtures" / "openclaw_bots_boot_check.sh"
HOOK_DRIVER = Path(__file__).parent / "fixtures" / "openclaw_bot_env_hook_driver.mjs"
SCRIPTS = REPO / "api" / "domains" / "agents" / "scripts" / "openclaw"
PLUGINS = SCRIPTS / "plugins"
PROXY = "http://localhost:8090"
BOT_A = UUID("0000000a-0000-4000-8000-00000000000a")
BOT_B = UUID("0000000b-0000-4000-8000-00000000000b")
STATE = "/home/node/.openclaw"
REWRITER = """export default {
  id: "exec-rewriter",
  register(api) {
    api.on("before_tool_call", (event) => ({
      params: { ...event.params, env: { ...(event.params.env || {}), AGENT_ID: "rewriter", REWRITER: "1" } },
    }), { priority: 10, matcher: ["exec"] });
  },
};
"""


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


def _boot(image: str, root: Path) -> dict:
    inputs, outputs, app_config = root / "in", root / "out", root / "app-config"
    secret, files_root = root / "secrets" / str(BOT_A), root / "files"
    for directory in (inputs, outputs, app_config, secret):
        directory.mkdir(parents=True)
        directory.chmod(0o777)
    bots = _bots()
    (inputs / "single.json").write_text(json.dumps(multi_agent_gateway_config(_parent(), [])))
    (inputs / "multi.json").write_text(json.dumps(multi_agent_gateway_config(_parent(), bots)))
    (inputs / "bots.json").write_text(
        json.dumps({"bots": [{"id": str(bot.id), "slot": bot.slot} for bot in bots], "deleted_ids": []})
    )
    for name, value in {"AGENT_ID": str(BOT_A), **_keys(BOT_A)[BOT_A]}.items():
        (secret / name).write_text(value)
    for bot in bots:
        files = files_root / str(bot.id)
        files.mkdir(parents=True)
        for name in ("SOUL.md", "AGENTS.md", "USER.md"):
            (files / name).write_text(f"{bot.id} {name}")
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
            f"{app_config}:/app/config",
            "-v",
            f"{root / 'secrets'}:/run/agentbarn/bots:ro",
            "-v",
            f"{files_root}:/app/bots:ro",
            "-v",
            f"{SCRIPTS}:/scripts:ro",
            "-v",
            f"{PLUGINS}:/plugins:ro",
            "-v",
            f"{BOOT_SCRIPT}:/check.sh:ro",
            "--entrypoint",
            "sh",
            image,
            "/check.sh",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=115,
    )
    assert_that(completed.returncode, equal_to(0), completed.stdout + completed.stderr)
    return {
        f"{step}-{name}": json.loads((outputs / f"{step}-{name}.json").read_text() or "null")
        for step in ("alone", "bots", "after")
        for name in ("validate", "agents", "audit", "config")
    }


def test_bots_come_and_go_through_the_boot_scripts_on_the_saved_config(openclaw_image: str, tmp_path: Path):
    result = _boot(openclaw_image, tmp_path)

    assert_that(result["alone-validate"], has_entries(valid=True))
    assert_that([agent["id"] for agent in result["alone-agents"]], equal_to(["main"]))

    assert_that(result["bots-validate"], has_entries(valid=True, warnings=[]))
    assert_that([agent["id"] for agent in result["bots-agents"]], equal_to(["main", str(BOT_A)]))
    assert_that(result["bots-audit"]["resolution"]["refsChecked"], equal_to(2))
    assert_that(_unresolved(result["bots-audit"]), equal_to([]))

    assert_that(result["after-validate"], has_entries(valid=True))
    assert_that([agent["id"] for agent in result["after-agents"]], equal_to(["main"]))
    saved = result["after-config"]
    assert_that("ownership" in saved["agents"] or "entries" in saved["agents"], equal_to(False))
    assert_that([name for name in saved["models"]["providers"] if name.startswith("litellm-bot-")], equal_to([]))
    assert_that("secrets" in saved, equal_to(False))


def _hooks(image: str, root: Path) -> dict:
    plugins, secret = root / "plugins", root / "secrets" / str(BOT_A)
    shutil.copytree(PLUGINS / "agentbarn-bot-env", plugins / "agentbarn-bot-env")
    rewriter = plugins / "exec-rewriter"
    rewriter.mkdir(parents=True)
    (rewriter / "index.js").write_text(REWRITER)
    (rewriter / "package.json").write_text(
        json.dumps(
            {"name": "exec-rewriter", "version": "1.0.0", "type": "module", "openclaw": {"extensions": ["./index.js"]}}
        )
    )
    (rewriter / "openclaw.plugin.json").write_text(
        json.dumps({"id": "exec-rewriter", "configSchema": {"type": "object", "additionalProperties": False}})
    )
    secret.mkdir(parents=True)
    for name, value in {"AGENT_ID": str(BOT_A), "ARTIFACT_API_KEY": "artifact-a"}.items():
        (secret / name).write_text(value)
    completed = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-e",
            f"BOT_A={BOT_A}",
            "-e",
            "PARENT_NAMES=" + json.dumps(["AGENT_ID", "ARTIFACT_API_KEY", "MEMORY_API_KEY"]),
            "-e",
            "AGENT_ID=parent-id",
            "-e",
            "ARTIFACT_API_KEY=artifact-parent",
            "-e",
            "MEMORY_API_KEY=memory-parent",
            "-v",
            f"{plugins}:/plugins:ro",
            "-v",
            f"{root / 'secrets'}:/run/agentbarn/bots:ro",
            "-v",
            f"{HOOK_DRIVER}:/driver.mjs:ro",
            "--entrypoint",
            "sh",
            image,
            "-c",
            "cp -r /plugins /tmp/plugins && chmod -R go-w /tmp/plugins && node /driver.mjs",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=110,
    )
    assert_that(completed.returncode, equal_to(0), completed.stdout + completed.stderr)
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_the_real_hook_runner_gives_each_agents_commands_their_own_values(openclaw_image: str, tmp_path: Path):
    result = _hooks(openclaw_image, tmp_path)

    assert_that(result["diagnostics"], equal_to([]))
    bot = result["bot"]["result"]["params"]["env"]
    assert_that(
        bot,
        has_entries(AGENT_ID=str(BOT_A), ARTIFACT_API_KEY="artifact-a", MEMORY_API_KEY="", EXTRA="kept"),
    )
    assert_that("REWRITER" in bot, equal_to(False))
    parent = result["parent"]["result"]["params"]["env"]
    assert_that(parent, has_entries(AGENT_ID="parent-id", MEMORY_API_KEY="memory-parent", EXTRA="kept"))
    assert_that(result["unknown"], has_entries(error=contains_string("agentbarn-bot-env failed")))
    assert_that(result["read"], equal_to({"result": None}))
    assert_that(result["ownAccount"]["result"]["params"], has_entries(channel="telegram", accountId=str(BOT_A)))
    for refused in ("otherPlatform", "otherAccount"):
        assert_that(result[refused]["result"], has_entries(block=True, blockReason=contains_string("own account")))
