import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path(tempfile.mkdtemp())
os.environ["HERMES_HOME"] = str(HOME)
sys.path.insert(0, "/opt/hermes")

import yaml
from hermes_cli import plugins  # ty: ignore[unresolved-import]
from hermes_cli.tools_config import _get_platform_tools  # ty: ignore[unresolved-import]
from tools.registry import registry  # ty: ignore[unresolved-import]

PLUGIN_ID = "agentbarn-first-conversation"
STATE_DIR = Path("/workspace/.agentbarn")
SCRIPT = "# First conversation\n\n1. Greet them.\n"


def fail(message):
    raise SystemExit("first-conversation contract broken: " + message)


def seed(source: Path, user_md: Path, state_dir: Path) -> None:
    subprocess.run(["python3", "/seed.py", str(source), str(user_md), str(state_dir)], check=True)


def check_seed() -> None:
    root = Path(tempfile.mkdtemp())
    source = root / "config" / "BOOTSTRAP.md"
    source.parent.mkdir()
    source.write_text(SCRIPT)

    fresh = root / "fresh"
    seed(source, fresh / "memories" / "USER.md", fresh / "workspace" / ".agentbarn")
    if (fresh / "workspace" / ".agentbarn" / "BOOTSTRAP.md").read_text() != SCRIPT:
        fail("a fresh volume was not seeded with the script")
    (fresh / "workspace" / ".agentbarn" / "BOOTSTRAP.md").unlink()
    seed(source, fresh / "memories" / "USER.md", fresh / "workspace" / ".agentbarn")
    if (fresh / "workspace" / ".agentbarn" / "BOOTSTRAP.md").exists():
        fail("a restart brought a finished script back")

    existing = root / "existing"
    (existing / "memories").mkdir(parents=True)
    (existing / "memories" / "USER.md").write_text("learned profile")
    seed(source, existing / "memories" / "USER.md", existing / "workspace" / ".agentbarn")
    if (existing / "workspace" / ".agentbarn" / "BOOTSTRAP.md").exists():
        fail("an Agent with a user profile was given a script")
    if not (existing / "workspace" / ".agentbarn" / "bootstrap-decided").exists():
        fail("an existing Agent was not marked decided")


def load_plugin() -> dict:
    shutil.copytree("/plugin", HOME / "plugins" / PLUGIN_ID)
    config = {"toolsets": ["all"], "plugins": {"enabled": [PLUGIN_ID]}}
    (HOME / "config.yaml").write_text(yaml.safe_dump(config))
    plugins.discover_plugins(force=True)
    if PLUGIN_ID not in plugins.get_plugin_manager()._plugins:
        fail("Hermes did not load the plugin from $HERMES_HOME/plugins")
    if "pre_llm_call" not in plugins.VALID_HOOKS:
        fail("pre_llm_call is no longer a valid hook")
    return config


def contexts(**kwargs) -> list:
    payload = {"session_id": "agent:main:telegram:dm:42", "platform": "telegram", "parent_session_id": ""}
    payload.update(kwargs)
    return [r for r in plugins.invoke_hook("pre_llm_call", **payload) if isinstance(r, dict) and "context" in r]


def check_plugin(config: dict) -> None:
    if registry.get_entry("finish_first_conversation") is None:
        fail("the finish tool was not registered")
    if PLUGIN_ID not in _get_platform_tools(config, "telegram"):
        fail("the finish tool's toolset is not offered on telegram")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "BOOTSTRAP.md").write_text(SCRIPT)
    if contexts(session_id="agentbarn-boot", platform="api_server"):
        fail("BOOT.md runs received the script")
    if contexts(platform="cron"):
        fail("cron runs received the script")
    carried = contexts()
    if len(carried) != 1 or not carried[0]["context"].endswith(SCRIPT):
        fail(f"an interactive telegram turn did not carry the script: {carried}")

    result = registry.dispatch("finish_first_conversation", {})
    if '"done"' not in str(result):
        fail(f"the finish tool returned {result!r}")
    if (STATE_DIR / "BOOTSTRAP.md").exists():
        fail("the finish tool left the script in place")
    if contexts():
        fail("a finished script was still carried")


def main() -> None:
    check_seed()
    check_plugin(load_plugin())
    print("first-conversation contract holds")


if __name__ == "__main__":
    main()
