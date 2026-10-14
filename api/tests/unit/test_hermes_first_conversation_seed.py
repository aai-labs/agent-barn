import importlib.util
import re
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).parents[2] / "domains" / "agents" / "scripts" / "hermes"
_SCRIPT_TEXT = "# First conversation\n\n1. Greet them.\n"


def _load_seed():
    spec = importlib.util.spec_from_file_location(
        "test_first_conversation_seed", _SCRIPTS / "first-conversation-seed.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def paths(tmp_path: Path) -> dict[str, Path]:
    config = tmp_path / "config"
    config.mkdir()
    return {
        "source": config / "BOOTSTRAP.md",
        "user_md": tmp_path / "data" / "memories" / "USER.md",
        "state_dir": tmp_path / "workspace" / ".agentbarn",
    }


def _seed(paths: dict[str, Path]) -> None:
    _load_seed().seed(paths["source"], paths["user_md"], paths["state_dir"])


def test_a_new_agent_with_a_script_gets_it_once(paths) -> None:
    paths["source"].write_text(_SCRIPT_TEXT, encoding="utf-8")

    _seed(paths)

    assert (paths["state_dir"] / "BOOTSTRAP.md").read_text(encoding="utf-8") == _SCRIPT_TEXT
    assert (paths["state_dir"] / "bootstrap-decided").exists()


def test_an_agent_that_already_has_a_user_profile_never_gets_a_script(paths) -> None:
    paths["source"].write_text(_SCRIPT_TEXT, encoding="utf-8")
    paths["user_md"].parent.mkdir(parents=True)
    paths["user_md"].write_text("learned profile", encoding="utf-8")

    _seed(paths)

    assert not (paths["state_dir"] / "BOOTSTRAP.md").exists()
    assert (paths["state_dir"] / "bootstrap-decided").exists()


def test_a_new_agent_without_a_script_is_decided_with_nothing_to_run(paths) -> None:
    _seed(paths)

    assert not (paths["state_dir"] / "BOOTSTRAP.md").exists()
    assert (paths["state_dir"] / "bootstrap-decided").exists()


def test_a_restart_never_brings_a_finished_script_back(paths) -> None:
    paths["source"].write_text(_SCRIPT_TEXT, encoding="utf-8")
    _seed(paths)
    (paths["state_dir"] / "BOOTSTRAP.md").unlink()

    _seed(paths)

    assert not (paths["state_dir"] / "BOOTSTRAP.md").exists()


def test_a_restart_keeps_an_unfinished_script_untouched(paths) -> None:
    paths["source"].write_text(_SCRIPT_TEXT, encoding="utf-8")
    _seed(paths)
    paths["source"].write_text("# A newer template script\n\nSomething else.\n", encoding="utf-8")

    _seed(paths)

    assert (paths["state_dir"] / "BOOTSTRAP.md").read_text(encoding="utf-8") == _SCRIPT_TEXT


def test_start_script_seeds_before_it_creates_the_user_profile_and_installs_the_plugin() -> None:
    start = (_SCRIPTS / "start.sh").read_text(encoding="utf-8")

    seed = start.index("first-conversation-seed.py")
    user_copy = re.search(r"cp /app/config/USER\.md /opt/data/memories/USER\.md", start)
    assert user_copy is not None
    assert seed < user_copy.start()
    assert "/app/config/BOOTSTRAP.md /opt/data/memories/USER.md /workspace/.agentbarn" in start
    assert "/opt/data/plugins/agentbarn-first-conversation/plugin.yaml" in start
    assert "/opt/data/plugins/agentbarn-first-conversation/__init__.py" in start
