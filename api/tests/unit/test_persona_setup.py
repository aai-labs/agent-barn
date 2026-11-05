import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml
from hamcrest import assert_that, contains_string, equal_to, has_item, has_key, not_

SCRIPTS = Path(__file__).resolve().parents[2] / "domains/agents/scripts/hermes"
SETUP = SCRIPTS / "persona-setup.py"
SECRET_VALUE = "sk-secret-value-123456"
BASE_ENV = {
    "API_SERVER_KEY": SECRET_VALUE,
    "OPENAI_API_KEY": SECRET_VALUE,
    "OPENROUTER_BASE_URL": "http://localhost:8090",
    "FIRECRAWL_API_KEY": SECRET_VALUE,
    "FIRECRAWL_API_URL": "http://firecrawl",
    "FIRECRAWL_BROWSER_TTL": "600",
    "HINDSIGHT_API_KEY": SECRET_VALUE,
    "SLACK_BOT_TOKEN": "xoxb-token",
    "TELEGRAM_ALLOWED_USERS": "111",
    "INGEST_API_KEY": SECRET_VALUE,
    "COMMUNICATIONS_API_KEY": SECRET_VALUE,
    "AGENT_TRIGGER_KEY": SECRET_VALUE,
    "MEMORY_API_KEY": SECRET_VALUE,
    "AF_GATEWAY_TOKEN_GITHUB": SECRET_VALUE,
}
MANAGED_CONFIG = {
    "model": {"default": "m/m", "base_url": "http://localhost:8090"},
    "plugins": {"enabled": ["telemetry-push", "agentbarn-observer", "agentbarn-slack-access"]},
    "platforms": {"slack": {"extra": {"markdown_blocks": True}}},
    "slack": {"mention": True},
    "discord": {"x": 1},
    "telegram": {"y": 2},
    "display": {"tool_progress": "all", "platforms": {"slack": {"tool_progress": "off"}}},
    "skills": {"external_dirs": ["/workspace/skills"]},
    "approvals": {"mode": "smart"},
}
MEMORY_SETUP_STUB = """
import os
from pathlib import Path
home = Path(os.environ["HERMES_HOME"])
(home / "hindsight").mkdir(exist_ok=True)
(home / "hindsight" / "config.json").write_text(str(home))
"""


def _symlinks_work() -> bool:
    with tempfile.TemporaryDirectory() as directory:
        try:
            os.symlink(Path(directory) / "target", Path(directory) / "link")
        except OSError:
            return False
    return True


pytestmark = pytest.mark.skipif(not _symlinks_work(), reason="needs permission to create symlinks")


class Tree:
    def __init__(self, base: Path, *, keys=("sales",), deleted=(), default_names=("SLACK_BOT_TOKEN",)):
        self.root = base / "data"
        self.workspace = base / "workspace"
        self.config = base / "config"
        self.env_dir = base / "env"
        for path in (self.root, self.workspace, self.config):
            path.mkdir()
        self.write_manifest(keys, deleted, default_names)
        (self.config / "hermes-config.yaml").write_text(yaml.safe_dump(MANAGED_CONFIG))
        (self.config / "USER.md").write_text("template user")
        (self.config / "telemetry-push-plugin.yaml").write_text("name: telemetry-push")
        (self.config / "telemetry-push-init.py").write_text("def register(ctx): pass")
        (self.config / "memory-setup.py").write_text(MEMORY_SETUP_STUB)
        shutil.copy(SCRIPTS / "config-merge.py", self.config / "config-merge.py")
        for key in keys:
            self.write_persona(key)

    def write_manifest(self, keys, deleted=(), default_names=("SLACK_BOT_TOKEN",)) -> None:
        (self.config / "personas.json").write_text(
            json.dumps(
                {
                    "active": [{"key": key} for key in keys],
                    "deleted_keys": list(deleted),
                    "default_env_names": list(default_names),
                }
            )
        )

    def write_persona(self, key: str) -> None:
        (self.config / f"persona-{key}-SOUL.md").write_text(f"{key} soul")
        (self.config / f"persona-{key}-IDENTITY.md").write_text(f"{key} identity")

    def home(self, key: str) -> Path:
        return self.root / "profiles" / key

    def run(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SETUP), *args],
            env={
                **os.environ,
                **BASE_ENV,
                **(env or {}),
                "PERSONA_ROOT": str(self.root),
                "PERSONA_WORKSPACE": str(self.workspace),
                "PERSONA_CONFIG": str(self.config),
                "PERSONA_ENV_DIR": str(self.env_dir),
            },
            capture_output=True,
            text=True,
            check=False,
        )

    def env_names(self, path: Path) -> set[str]:
        return {line.split("=", 1)[0] for line in path.read_text().splitlines()}


@pytest.fixture
def tree(tmp_path) -> Tree:
    return Tree(tmp_path)


def test_without_a_manifest_it_changes_nothing(tree):
    (tree.config / "personas.json").unlink()

    result = tree.run()

    assert_that(result.returncode, equal_to(0))
    assert_that(tree.env_dir.exists(), equal_to(False))
    assert_that((tree.root / "profiles").exists(), equal_to(False))


def test_it_lays_out_a_persona_profile(tree):
    assert_that(tree.run().returncode, equal_to(0))

    home = tree.home("sales")
    assert_that((home / "SOUL.md").read_text(), equal_to("sales soul"))
    assert_that((home / "IDENTITY.md").read_text(), equal_to("sales identity"))
    assert_that((home / "memories" / "USER.md").read_text(), equal_to("template user"))
    assert_that((home / "plugins" / "telemetry-push" / "plugin.yaml").exists(), equal_to(True))
    assert_that((home / "plugins" / "telemetry-push" / "__init__.py").exists(), equal_to(True))
    assert_that((home / "hindsight" / "config.json").read_text(), equal_to(str(home)))
    assert_that((tree.workspace / "personas" / "sales" / "memory").is_dir(), equal_to(True))
    assert_that(json.loads((tree.env_dir / "active-personas.json").read_text()), equal_to(["sales"]))


def test_a_profile_never_gets_a_home_folder(tree):
    tree.run()

    assert_that((tree.home("sales") / "home").exists(), equal_to(False))


def test_existing_memory_is_kept(tree):
    tree.run()
    (tree.home("sales") / "memories" / "USER.md").write_text("learned")

    tree.run()

    assert_that((tree.home("sales") / "memories" / "USER.md").read_text(), equal_to("learned"))


def test_env_files_are_symlinks_into_the_env_directory(tree):
    tree.run()

    for link, name in ((tree.root / ".env", "default.env"), (tree.home("sales") / ".env", "sales.env")):
        assert_that(link.is_symlink(), equal_to(True))
        assert_that(Path(os.readlink(link)), equal_to(tree.env_dir / name))
    assert_that((tree.env_dir / "sales.env").stat().st_mode & 0o777, equal_to(0o600))


def test_a_persona_env_holds_only_what_a_persona_needs(tree):
    tree.run()

    names = tree.env_names(tree.env_dir / "sales.env")

    assert_that(
        names,
        equal_to(
            {
                "API_SERVER_KEY",
                "OPENAI_API_KEY",
                "OPENROUTER_BASE_URL",
                "FIRECRAWL_API_KEY",
                "FIRECRAWL_API_URL",
                "FIRECRAWL_BROWSER_TTL",
                "HINDSIGHT_API_KEY",
            }
        ),
    )


def test_the_default_env_adds_the_connected_platform_names_from_the_manifest(tmp_path):
    tree = Tree(tmp_path, default_names=("SLACK_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS", "ABSENT_NAME"))

    tree.run()

    names = tree.env_names(tree.env_dir / "default.env")
    assert_that("SLACK_BOT_TOKEN" in names and "TELEGRAM_ALLOWED_USERS" in names, equal_to(True))
    assert_that("ABSENT_NAME" in names, equal_to(False))
    for internal in ("INGEST_API_KEY", "COMMUNICATIONS_API_KEY", "AGENT_TRIGGER_KEY", "MEMORY_API_KEY"):
        assert_that(internal in names, equal_to(False))


def test_values_are_quoted_the_way_hermes_quotes_them(tree):
    tree.run(env={"FIRECRAWL_API_URL": 'a #b "c" d\\e'})

    lines = (tree.env_dir / "sales.env").read_text().splitlines()

    assert_that(lines, has_item('FIRECRAWL_API_URL="a #b \\"c\\" d\\\\e"'))


@pytest.mark.parametrize("value", ["line1\nline2", "x${HOME}y"])
def test_values_the_parsers_cannot_round_trip_are_left_out_by_name(tree, value):
    result = tree.run(env={"FIRECRAWL_API_URL": value})

    assert_that(result.returncode, equal_to(0))
    assert_that("FIRECRAWL_API_URL" in tree.env_names(tree.env_dir / "sales.env"), equal_to(False))
    assert_that(result.stdout, contains_string("FIRECRAWL_API_URL"))
    assert_that(result.stdout, not_(contains_string(value)))


def test_a_persona_config_is_a_copy_with_only_persona_overrides(tree):
    tree.run()

    config = yaml.safe_load((tree.home("sales") / "config.yaml").read_text())

    assert_that(config["model"], equal_to(MANAGED_CONFIG["model"]))
    assert_that(config["approvals"], equal_to(MANAGED_CONFIG["approvals"]))
    assert_that(config["plugins"]["enabled"], equal_to(["telemetry-push"]))
    assert_that(config["platforms"], equal_to({"api_server": {"enabled": False}}))
    assert_that(config["skills"]["external_dirs"], equal_to(["/workspace/skills", str(tree.root / "skills")]))
    assert_that(config["display"], equal_to({"tool_progress": "all"}))
    for section in ("slack", "discord", "telegram"):
        assert_that(config, not_(has_key(section)))


def test_a_broken_merge_still_leaves_a_usable_persona_config(tree):
    (tree.config / "config-merge.py").write_text("raise SystemExit(1)")

    tree.run()

    config = yaml.safe_load((tree.home("sales") / "config.yaml").read_text())
    assert_that(config["plugins"]["enabled"], equal_to(["telemetry-push"]))
    assert_that(json.loads((tree.env_dir / "active-personas.json").read_text()), equal_to(["sales"]))


def test_a_rerun_leaves_the_same_result(tree):
    tree.run()
    first = (tree.home("sales") / "config.yaml").read_text()

    result = tree.run()

    assert_that(result.returncode, equal_to(0))
    assert_that((tree.home("sales") / "config.yaml").read_text(), equal_to(first))
    assert_that((tree.home("sales") / ".env").is_symlink(), equal_to(True))


def test_deleted_personas_are_removed_even_with_none_active(tree):
    tree.run()
    (tree.workspace / "personas" / "sales" / "memory" / "note.md").write_text("note")
    tree.write_manifest((), deleted=("sales",))
    (tree.root / ".env").unlink()

    result = tree.run()

    assert_that(result.returncode, equal_to(0))
    assert_that(tree.home("sales").exists(), equal_to(False))
    assert_that((tree.workspace / "personas" / "sales").exists(), equal_to(False))
    assert_that((tree.root / ".env").is_symlink(), equal_to(False))


def test_a_deleted_key_cannot_escape_the_profiles_folder(tree):
    outside = tree.root / "keep"
    outside.mkdir()
    tree.write_manifest(("sales",), deleted=("../keep", "..", "a/b", "sales\n"))

    result = tree.run()

    assert_that(result.returncode, equal_to(0))
    assert_that(outside.is_dir(), equal_to(True))


def test_a_symlinked_profile_is_unlinked_and_never_followed(tree):
    outside = tree.root / "precious"
    outside.mkdir()
    (outside / "file").write_text("keep")
    (tree.root / "profiles").mkdir()
    tree.home("gone").symlink_to(outside)
    tree.home("sales").symlink_to(outside)
    tree.write_manifest(("sales",), deleted=("gone",))

    assert_that(tree.run().returncode, equal_to(0))

    assert_that((outside / "file").read_text(), equal_to("keep"))
    assert_that(tree.home("gone").is_symlink(), equal_to(False))
    assert_that(tree.home("sales").is_symlink(), equal_to(False))
    assert_that((outside / "SOUL.md").exists(), equal_to(False))
    assert_that((tree.home("sales") / "SOUL.md").exists(), equal_to(True))


def test_leftover_env_temp_files_are_removed(tree):
    (tree.root / "profiles" / "sales").mkdir(parents=True)
    (tree.root / ".env_abc.tmp").write_text("secret")
    (tree.home("sales") / ".env_def.tmp").write_text("secret")

    tree.run()

    assert_that((tree.root / ".env_abc.tmp").exists(), equal_to(False))
    assert_that((tree.home("sales") / ".env_def.tmp").exists(), equal_to(False))


def test_one_bad_persona_does_not_stop_the_others_or_leak_values(tmp_path):
    tree = Tree(tmp_path, keys=("one", "two", "three"))
    (tree.config / "persona-two-SOUL.md").unlink()

    result = tree.run()

    assert_that(result.returncode, equal_to(0))
    assert_that(json.loads((tree.env_dir / "active-personas.json").read_text()), equal_to(["one", "three"]))
    assert_that(result.stdout, contains_string("two"))
    assert_that(result.stdout, not_(contains_string(SECRET_VALUE)))
    assert_that(result.stderr, not_(contains_string(SECRET_VALUE)))


def test_an_invalid_active_key_is_skipped(tmp_path):
    tree = Tree(tmp_path)
    tree.write_manifest(("sales", "../bad"))

    assert_that(tree.run().returncode, equal_to(0))

    assert_that(json.loads((tree.env_dir / "active-personas.json").read_text()), equal_to(["sales"]))
    assert_that((tree.root / "bad").exists(), equal_to(False))


def test_failing_to_write_the_default_env_stops_the_boot(tree):
    tree.env_dir.write_text("not a directory")

    assert_that(tree.run().returncode == 0, equal_to(False))


def _write_config(home: Path, allowlist=None) -> None:
    home.mkdir(parents=True, exist_ok=True)
    config = {"model": "m"}
    if allowlist is not None:
        config["command_allowlist"] = allowlist
    (home / "config.yaml").write_text(yaml.safe_dump(config))


def _allowlist_after_merge(tree: Tree, home: Path) -> list[str]:
    subprocess.run(
        [
            sys.executable,
            str(tree.config / "config-merge.py"),
            str(tree.config / "hermes-config.yaml"),
            str(home / "config.yaml"),
        ],
        check=True,
    )
    return yaml.safe_load((home / "config.yaml").read_text()).get("command_allowlist", [])


def _set_mtime(home: Path, stamp: int) -> None:
    os.utime(home / "config.yaml", (stamp, stamp))


def test_the_newest_saved_approvals_reach_every_profile(tmp_path):
    tree = Tree(tmp_path, keys=("sales", "lawyer"))
    _write_config(tree.root, ["old"])
    _write_config(tree.home("sales"), ["old", "granted"])
    _write_config(tree.home("lawyer"), ["old"])
    _set_mtime(tree.root, 1000)
    _set_mtime(tree.home("sales"), 3000)
    _set_mtime(tree.home("lawyer"), 2000)

    assert_that(tree.run("--sync-allowlists").returncode, equal_to(0))

    for home in (tree.root, tree.home("sales"), tree.home("lawyer")):
        assert_that(_allowlist_after_merge(tree, home), equal_to(["old", "granted"]))


def test_a_revoke_in_the_newest_profile_is_not_undone(tmp_path):
    tree = Tree(tmp_path, keys=("sales",))
    _write_config(tree.root, ["kept", "revoked"])
    _write_config(tree.home("sales"), ["kept"])
    _set_mtime(tree.root, 1000)
    _set_mtime(tree.home("sales"), 2000)

    tree.run("--sync-allowlists")

    assert_that(_allowlist_after_merge(tree, tree.root), equal_to(["kept"]))


def test_a_new_persona_inherits_approvals_through_its_sidecar(tree):
    _write_config(tree.root, ["granted"])

    tree.run("--sync-allowlists")
    tree.run()

    config = yaml.safe_load((tree.home("sales") / "config.yaml").read_text())
    assert_that(config["command_allowlist"], equal_to(["granted"]))


def test_manual_mode_keeps_approvals_in_the_sidecar(tmp_path):
    tree = Tree(tmp_path)
    (tree.config / "hermes-config.yaml").write_text(yaml.safe_dump({**MANAGED_CONFIG, "approvals": {"mode": "manual"}}))
    _write_config(tree.root, ["granted"])

    tree.run("--sync-allowlists")
    tree.run()

    config = yaml.safe_load((tree.home("sales") / "config.yaml").read_text())
    assert_that(config, not_(has_key("command_allowlist")))
    sidecar = json.loads((tree.home("sales") / "agentbarn-command-allowlist.json").read_text())
    assert_that(sidecar, equal_to(["granted"]))


def test_syncing_without_a_manifest_changes_nothing(tree):
    (tree.config / "personas.json").unlink()
    _write_config(tree.root, ["granted"])
    before = (tree.root / "config.yaml").read_text()

    assert_that(tree.run("--sync-allowlists").returncode, equal_to(0))

    assert_that((tree.root / "config.yaml").read_text(), equal_to(before))
