import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[2] / "domains/agents/scripts/hermes"
SETUP = SCRIPTS / "bot-setup.py"
RUN = SCRIPTS / "bot-run.py"
BOT_A = "aaaaaaaa-0000-4000-8000-00000000000a"
BOT_B = "bbbbbbbb-0000-4000-8000-00000000000b"
PARENT_SECRET = "sk-parent-secret-value"
PARENT_ENV = {
    "API_SERVER_KEY": PARENT_SECRET,
    "OPENAI_API_KEY": PARENT_SECRET,
    "OPENROUTER_BASE_URL": "http://localhost:8090",
    "AGENT_ID": "parent-id",
    "COMMUNICATIONS_API_KEY": PARENT_SECRET,
    "INGEST_API_KEY": PARENT_SECRET,
    "MEMORY_API_KEY": PARENT_SECRET,
    "MEMORY_URL": "http://memory",
    "TELEGRAM_BOT_TOKEN": "parent-telegram",
    "ARTIFACT_API_KEY": "",
}
BOT_CONFIG = {
    "model": {"default": "bot/model"},
    "skills": {"external_dirs": ["/workspace/skills"]},
    "platforms": {"api_server": {"enabled": False}},
}
SOUL = (
    "Bot soul. Identity: `/workspace/IDENTITY.md`. Memory: `/opt/data/memories/USER.md`. "
    "Notes: `/workspace/memory/YYYY-MM-DD.md`."
)
MEMORY_SETUP_STUB = """
import json
import os
from pathlib import Path
home = Path(os.environ["HERMES_HOME"])
(home / "memory-setup.json").write_text(json.dumps(sorted(k for k in os.environ if k.startswith(("MEMORY_", "HINDSIGHT_")))))
"""
HELPER_STUB = """
import json
import os
import sys
from pathlib import Path
Path(sys.argv[0]).parents[1].joinpath("out").joinpath(f"{Path(sys.argv[0]).stem}-{os.environ.get('AGENT_ID')}.json").write_text(json.dumps(dict(os.environ)))
"""


def _symlinks_work() -> bool:
    with tempfile.TemporaryDirectory() as directory:
        try:
            os.symlink(Path(directory) / "target", Path(directory) / "link")
        except OSError:
            return False
    return True


pytestmark = pytest.mark.skipif(not _symlinks_work(), reason="needs symlink privileges; runs in CI and in Docker")


class Pod:
    def __init__(self, base: Path):
        self.root = base / "data"
        self.workspace = base / "workspace"
        self.config = base / "config"
        self.env_dir = base / "env"
        self.secrets = base / "secrets"
        self.files = base / "files"
        self.out = base / "out"
        for path in (self.root, self.workspace, self.config, self.env_dir, self.secrets, self.files, self.out):
            path.mkdir()
        shutil.copy(SCRIPTS / "config-merge.py", self.config / "config-merge.py")
        (self.config / "memory-setup.py").write_text(MEMORY_SETUP_STUB)
        (self.config / "AGENTS.md").write_text("Parent instructions")
        (self.root / "SOUL.md").write_text("Parent soul")
        (self.workspace / "AGENTS.md").write_text("Parent instructions")
        for helper in ("communications-runtime-adapter.py", "agent-trigger-server.py", "boot-run.py"):
            (self.config / helper).write_text(HELPER_STUB)

    def env(self, **extra) -> dict[str, str]:
        return {
            "PATH": os.environ["PATH"],
            **PARENT_ENV,
            "BOT_ROOT": str(self.root),
            "BOT_WORKSPACE": str(self.workspace),
            "BOT_CONFIG": str(self.config),
            "BOT_ENV_DIR": str(self.env_dir),
            "BOT_SECRET_ROOT": str(self.secrets),
            "BOT_CONFIG_ROOT": str(self.files),
            **extra,
        }

    def manifest(self, bots=(BOT_A,), deleted=(), passthrough=("AAI_CONFIG", "ARTIFACT_API_KEY", "MEMORY_API_KEY")):
        (self.config / "bots.json").write_text(
            json.dumps(
                {
                    "bots": [{"id": bot, "slot": slot} for slot, bot in enumerate(bots, start=1)],
                    "deleted_ids": list(deleted),
                    "passthrough": list(passthrough),
                }
            )
        )

    def bot(self, bot_id=BOT_A, secret=None, config=None, skills=None):
        secret_dir = self.secrets / bot_id
        secret_dir.mkdir()
        values = {
            "AGENT_ID": bot_id,
            "API_SERVER_KEY": f"key-{bot_id}",
            "OPENAI_API_KEY": f"llm-{bot_id}",
            "OPENROUTER_BASE_URL": "http://localhost:8090",
            "ARTIFACT_API_KEY": f"artifact-{bot_id}",
            "COMMUNICATIONS_API_KEY": f"comms-{bot_id}",
            "INGEST_API_KEY": f"ingest-{bot_id}",
            "INGEST_URL": "http://ingest",
            "SLACK_BOT_TOKEN": f"xoxb-{bot_id}",
            **(secret or {}),
        }
        for name, value in values.items():
            (secret_dir / name).write_text(value)
        files = self.files / bot_id
        files.mkdir()
        (files / "hermes-config.yaml").write_text(
            config if isinstance(config, str) else yaml.safe_dump(config or BOT_CONFIG)
        )
        (files / "SOUL.md").write_text(SOUL)
        (files / "AGENTS.md").write_text("Bot instructions in `/workspace/TOOLS.md` and `./skills/x/SKILL.md`")
        for name in ("IDENTITY.md", "TOOLS.md", "BOOT.md", "HEARTBEAT.md", "USER.md"):
            (files / name).write_text(f"bot {name}")
        (files / "telemetry-push-plugin.yaml").write_text("name: telemetry-push")
        (files / "telemetry-push-init.py").write_text("x = 1")
        if skills is not None:
            (files / "skills.json").write_text(json.dumps(skills))

    def home(self, bot_id=BOT_A) -> Path:
        return self.root / "profiles" / bot_id

    def setup(self, *args, **extra):
        return subprocess.run(
            [sys.executable, str(SETUP), *args], env=self.env(**extra), capture_output=True, text=True, check=False
        )

    def run_bot(self, bot_id=BOT_A, slot="1", script="communications-runtime-adapter.py"):
        return subprocess.run(
            [sys.executable, str(RUN), bot_id, slot, str(self.config / script)],
            env=self.env(),
            capture_output=True,
            text=True,
            check=False,
        )

    def served(self) -> list[str]:
        return [entry["id"] for entry in json.loads((self.env_dir / "active-bots.json").read_text())]

    def dotenv(self, path: Path) -> dict[str, str]:
        lines = [line.split("=", 1) for line in path.read_text().splitlines()]
        return {name: value.strip('"') for name, value in lines}


@pytest.fixture
def pod(tmp_path):
    return Pod(tmp_path)


def _ok(result):
    assert result.returncode == 0, result.stdout + result.stderr


def test_no_manifest_does_nothing(pod):
    _ok(pod.setup())

    assert not (pod.root / "profiles").exists()
    assert (pod.workspace / "AGENTS.md").read_text() == "Parent instructions"


def test_a_bot_gets_its_own_profile_layout(pod):
    pod.manifest()
    pod.bot()

    _ok(pod.setup())

    home = pod.home()
    for name in ("IDENTITY.md", "TOOLS.md", "BOOT.md", "HEARTBEAT.md", "memories/USER.md"):
        assert (home / name).exists(), name
    assert (home / "plugins/telemetry-push/plugin.yaml").exists()
    assert yaml.safe_load((home / "config.yaml").read_text())["skills"]["external_dirs"] == [str(home / "skills")]
    assert (pod.workspace / "bots" / BOT_A / "memory").is_dir()
    assert not (home / "home").exists()


def test_a_bots_prompt_has_its_own_instructions_and_paths(pod):
    pod.manifest()
    pod.bot()

    _ok(pod.setup())

    soul = (pod.home() / "SOUL.md").read_text()
    assert "Bot soul" in soul and "Bot instructions" in soul
    assert "Parent" not in soul
    assert f"{pod.home()}/IDENTITY.md" in soul
    assert f"{pod.home()}/TOOLS.md" in soul
    assert f"{pod.home()}/memories/USER.md" in soul
    assert f"{pod.home()}/skills/x/SKILL.md" in soul
    assert f"{pod.workspace}/bots/{BOT_A}/memory/YYYY-MM-DD.md" in soul
    assert "`/workspace/IDENTITY.md`" not in soul
    assert "/opt/data/memories" not in soul


def test_the_parents_instructions_move_into_its_soul(pod):
    pod.manifest()
    pod.bot()

    _ok(pod.setup())

    assert (pod.root / "SOUL.md").read_text() == "Parent soul\n\nParent instructions"
    assert (pod.workspace / "AGENTS.md").read_text() == ""


def test_a_bots_env_holds_its_own_values_only(pod):
    pod.manifest()
    pod.bot()

    _ok(pod.setup())

    link = pod.home() / ".env"
    assert link.is_symlink()
    assert Path(os.readlink(link)) == pod.env_dir / f"{BOT_A}.env"
    assert (pod.env_dir / f"{BOT_A}.env").stat().st_mode & 0o777 == 0o600
    env = pod.dotenv(link)
    assert env["API_SERVER_KEY"] == f"key-{BOT_A}"
    assert env["OPENAI_API_KEY"] == f"llm-{BOT_A}"
    assert env["ARTIFACT_API_KEY"] == f"artifact-{BOT_A}"
    assert env["SLACK_BOT_TOKEN"] == f"xoxb-{BOT_A}"
    assert env["AGENT_ID"] == BOT_A
    assert env["INGEST_API_KEY"] == f"ingest-{BOT_A}"
    assert env["AAI_CONFIG"] == f"{pod.home()}/.config/aai-cli/config.toml"
    assert PARENT_SECRET not in link.read_text()
    assert "MEMORY_API_KEY" not in env
    assert "COMMUNICATIONS_API_KEY" not in env


def test_the_parents_env_holds_its_values_and_no_empty_placeholders(pod):
    pod.manifest()
    pod.bot()

    _ok(pod.setup())

    env = pod.dotenv(pod.root / ".env")
    assert (pod.root / ".env").is_symlink()
    assert env["API_SERVER_KEY"] == PARENT_SECRET
    assert env["TELEGRAM_BOT_TOKEN"] == "parent-telegram"
    assert env["MEMORY_API_KEY"] == PARENT_SECRET
    assert env["AAI_CONFIG"] == f"{pod.root}/.config/aai-cli/config.toml"
    assert "ARTIFACT_API_KEY" not in env


def test_a_value_the_env_file_cannot_hold_is_left_out(pod):
    pod.manifest()
    pod.bot(secret={"SLACK_APP_TOKEN": "line1\nline2", "TELEGRAM_BOT_TOKEN": "${X}"})

    result = pod.setup()

    _ok(result)
    env = pod.dotenv(pod.home() / ".env")
    assert "SLACK_APP_TOKEN" not in env and "TELEGRAM_BOT_TOKEN" not in env
    assert "line1" not in result.stdout


def test_a_bot_without_memory_does_not_get_the_parents(pod):
    pod.manifest()
    pod.bot()

    _ok(pod.setup())

    assert json.loads((pod.home() / "memory-setup.json").read_text()) == []


def test_a_bot_with_memory_gets_its_own_key_for_setup(pod):
    pod.manifest()
    pod.bot(secret={"MEMORY_API_KEY": "bot-memory", "MEMORY_URL": "http://memory"})

    _ok(pod.setup())

    assert "HINDSIGHT_API_KEY" in json.loads((pod.home() / "memory-setup.json").read_text())
    assert pod.dotenv(pod.home() / ".env")["HINDSIGHT_API_KEY"] == "bot-memory"


def test_skills_go_in_the_bots_own_folder_and_stale_ones_go(pod):
    pod.manifest()
    pod.bot(skills=[{"path": "a/SKILL.md", "content": "skill"}, {"path": "../../escape.md", "content": "no"}])
    (pod.home() / "skills/old").mkdir(parents=True)

    _ok(pod.setup())

    assert (pod.home() / "skills/a/SKILL.md").read_text() == "skill"
    assert not (pod.home() / "skills/old").exists()
    assert not (pod.root / "profiles/escape.md").exists()


@pytest.mark.parametrize("problem", ["missing_secret", "wrong_identity", "bad_config"])
def test_a_broken_bot_is_not_served_and_the_rest_carry_on(pod, problem):
    pod.manifest(bots=(BOT_A, BOT_B))
    pod.bot(BOT_B)
    if problem == "missing_secret":
        (pod.secrets / BOT_A).mkdir()
        (pod.files / BOT_A).mkdir()
    elif problem == "wrong_identity":
        pod.bot(BOT_A, secret={"AGENT_ID": "parent-id"})
    else:
        pod.bot(BOT_A, config="{not: [yaml")

    _ok(pod.setup())

    assert pod.served() == [BOT_B]
    assert (pod.root / "SOUL.md").read_text().startswith("Parent soul")
    assert not (pod.home(BOT_A) / ".env").exists()


def test_rerunning_is_safe(pod):
    pod.manifest()
    pod.bot()

    _ok(pod.setup())
    (pod.root / "SOUL.md").write_text("Parent soul")
    (pod.home() / "memories/MEMORY.md").write_text("kept")
    _ok(pod.setup())

    assert pod.served() == [BOT_A]
    assert (pod.home() / "memories/MEMORY.md").read_text() == "kept"
    assert (pod.home() / ".env").is_symlink()


def test_a_deleted_bots_files_are_removed_without_following_links(pod):
    keep = pod.root / "outside"
    keep.mkdir()
    (keep / "file").write_text("x")
    (pod.root / "profiles").mkdir()
    os.symlink(keep, pod.home(BOT_B))
    (pod.workspace / "bots" / BOT_B).mkdir(parents=True)
    pod.manifest(deleted=(BOT_B, "../../outside"))
    pod.bot()

    _ok(pod.setup())

    assert not pod.home(BOT_B).is_symlink() and not pod.home(BOT_B).exists()
    assert (keep / "file").exists()
    assert not (pod.workspace / "bots" / BOT_B).exists()


def test_only_deleted_bots_cleans_up_and_writes_no_env(pod):
    (pod.workspace / "bots" / BOT_B).mkdir(parents=True)
    pod.manifest(bots=(), deleted=(BOT_B,))

    _ok(pod.setup())

    assert not (pod.workspace / "bots" / BOT_B).exists()
    assert not (pod.root / ".env").exists()
    assert (pod.workspace / "AGENTS.md").read_text() == "Parent instructions"


def test_approvals_sync_from_the_newest_saved_profile(pod):
    pod.manifest()
    pod.home().mkdir(parents=True)
    (pod.root / "config.yaml").write_text(yaml.safe_dump({"command_allowlist": ["old"]}))
    time.sleep(0.02)
    (pod.home() / "config.yaml").write_text(yaml.safe_dump({"command_allowlist": ["new"]}))

    _ok(pod.setup("--sync-allowlists"))

    for home in (pod.root, pod.home()):
        assert json.loads((home / "agentbarn-command-allowlist.json").read_text()) == ["new"]


def test_a_helper_runs_as_its_bot_only(pod):
    pod.manifest()
    pod.bot()
    _ok(pod.setup())

    _ok(pod.run_bot())

    env = json.loads((pod.out / f"communications-runtime-adapter-{BOT_A}.json").read_text())
    assert env["AGENT_ID"] == BOT_A
    assert env["COMMUNICATIONS_API_KEY"] == f"comms-{BOT_A}"
    assert env["RUNTIME_API_URL"] == f"http://127.0.0.1:8642/p/{BOT_A}"
    assert env["RUNTIME_API_KEY"] == f"key-{BOT_A}"
    assert env["AGENT_TRIGGER_PORT"] == "8101"
    assert env["GATEWAY_MULTIPLEX_PROFILES"] == "1"
    assert env["OPENAI_API_KEY"] == f"llm-{BOT_A}"
    assert env["BOOT_FILE"] == f"{pod.home()}/BOOT.md"
    assert PARENT_SECRET not in json.dumps(env)
    assert "MEMORY_API_KEY" not in env


@pytest.mark.parametrize("problem", ["not_served", "missing_secret", "wrong_identity"])
def test_a_helper_never_starts_for_a_broken_bot(pod, problem):
    pod.manifest()
    if problem == "not_served":
        pod.bot()
        (pod.env_dir / "active-bots.json").write_text("[]")
    elif problem == "missing_secret":
        (pod.env_dir / "active-bots.json").write_text(json.dumps([{"id": BOT_A, "slot": 1}]))
    else:
        pod.bot(secret={"AGENT_ID": "parent-id"})
        (pod.env_dir / "active-bots.json").write_text(json.dumps([{"id": BOT_A, "slot": 1}]))

    result = pod.run_bot()

    assert result.returncode != 0
    assert list(pod.out.iterdir()) == []


def test_launch_starts_the_helpers_for_served_bots_only(pod):
    pod.manifest(bots=(BOT_A, BOT_B))
    pod.bot(BOT_B)
    (pod.secrets / BOT_A).mkdir()
    (pod.files / BOT_A).mkdir()
    _ok(pod.setup())

    _ok(pod.setup("--launch"))

    deadline = time.time() + 10
    expected = {
        f"{stem}-{BOT_B}.json" for stem in ("communications-runtime-adapter", "agent-trigger-server", "boot-run")
    }
    while time.time() < deadline and {path.name for path in pod.out.iterdir()} != expected:
        time.sleep(0.1)
    assert {path.name for path in pod.out.iterdir()} == expected


def test_every_profile_lists_the_same_passthrough_names(pod):
    pod.manifest()
    pod.bot()
    (pod.root / "config.yaml").write_text(yaml.safe_dump({"model": {"default": "parent"}}))

    _ok(pod.setup())

    names = ["AAI_CONFIG", "ARTIFACT_API_KEY", "MEMORY_API_KEY"]
    assert yaml.safe_load((pod.home() / "config.yaml").read_text())["terminal"]["env_passthrough"] == names
    assert yaml.safe_load((pod.root / "config.yaml").read_text())["terminal"]["env_passthrough"] == names


def test_the_aai_cli_setup_reads_the_bots_own_config(pod):
    pod.manifest()
    pod.bot()
    script = f"cp /app/config/aai-cli-config.toml {pod.out}/seen.toml || echo $0 > {pod.out}/missing\n"
    (pod.files / BOT_A / "aai-cli-setup.sh").write_text(f"grep -q . /app/config/aai-cli-config.toml; {script}")
    (pod.files / BOT_A / "aai-cli-config.toml").write_text("bot config")

    _ok(pod.setup())

    assert (pod.out / "seen.toml").read_text() == "bot config"


def test_the_gog_setup_reads_the_bots_own_files(pod):
    pod.manifest()
    pod.bot()
    (pod.files / BOT_A / "gog-setup.sh").write_text(f"cp /app/config/gog-shim.sh {pod.out}/gog\n")
    (pod.files / BOT_A / "gog-shim.sh").write_text("bot shim")

    _ok(pod.setup())

    assert (pod.out / "gog").read_text() == "bot shim"


def test_a_failing_gog_setup_means_the_bot_is_not_served(pod):
    pod.manifest()
    pod.bot()
    (pod.files / BOT_A / "gog-setup.sh").write_text("exit 3\n")

    _ok(pod.setup())

    assert pod.served() == []
