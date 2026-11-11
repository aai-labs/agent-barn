import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID

import pytest

from api.domains.agents.builders import build_openclaw_gateway_config, native_discord_channel, native_telegram_channel
from api.domains.agents.builders.openclaw import START_SH, OpenClawBot, multi_agent_gateway_config

SCRIPTS = Path(__file__).resolve().parents[2] / "domains/agents/scripts/openclaw"
SETUP = SCRIPTS / "bot-setup.py"
RUN = SCRIPTS / "bot-run.py"
INIT = SCRIPTS / "init-openclaw.js"
BOT_A = "0000000a-0000-4000-8000-00000000000a"
BOT_B = "0000000b-0000-4000-8000-00000000000b"
GONE = "0000000c-0000-4000-8000-00000000000c"
PROXY = "http://localhost:8090"
PARENT_TOKEN = "parent-gateway-token"
PARENT_ENV = {
    "AGENT_ID": "parent-id",
    "OPENCLAW_GATEWAY_TOKEN": PARENT_TOKEN,
    "RUNTIME_API_KEY": PARENT_TOKEN,
    "RUNTIME_API_URL": "http://127.0.0.1:18789",
    "RUNTIME_MODEL": "openclaw/main",
    "RUNTIME_KIND": "openclaw",
    "LITELLM_API_KEY": "sk-parent",
    "COMMUNICATIONS_API_KEY": "comms-parent",
    "INGEST_API_KEY": "ingest-parent",
    "TELEGRAM_BOT_TOKEN": "1:parent",
}
HELPER_STUB = """
import json
import os
import sys
from pathlib import Path
out = Path(sys.argv[0]).parents[1] / "out"
out.joinpath(f"{Path(sys.argv[0]).stem}-{os.environ.get('AGENT_ID')}.json").write_text(json.dumps(dict(os.environ)))
"""
FAKE_OPENCLAW = """
import json
import os
import sys
from pathlib import Path
log = Path(os.environ["BOT_TEST_OUT"]) / "openclaw-calls.json"
calls = json.loads(log.read_text()) if log.exists() else []
calls.append(sys.argv[1:])
log.write_text(json.dumps(calls))
if sys.argv[1:3] == ["automations", "list"]:
    if len(calls) == 1:
        sys.exit(1)
    print(json.dumps({"jobs": [
        {"id": "job-gone", "agentId": "GONE_ID"},
        {"id": "job-a", "agentId": "BOT_A_ID"},
        {"id": "job-main", "agentId": "main"},
    ]}))
""".replace("GONE_ID", GONE).replace("BOT_A_ID", BOT_A)
HELPERS_NEED_POSIX = pytest.mark.skipif(
    os.name == "nt", reason="a Windows interpreter needs SYSTEMROOT, which Bot helpers never inherit"
)


def _overlay(bots):
    parent = build_openclaw_gateway_config(
        "litellm/gpt-5", PROXY, {"telegram": native_telegram_channel({"dm_policy": "open"})}, memory_enabled=True
    )
    return multi_agent_gateway_config(parent, bots)


def _bots():
    return [
        OpenClawBot(
            UUID(BOT_A),
            1,
            build_openclaw_gateway_config(
                "litellm/gpt-5-mini", PROXY, {"telegram": native_telegram_channel({"dm_policy": "open"})}
            ),
        ),
        OpenClawBot(
            UUID(BOT_B),
            2,
            build_openclaw_gateway_config(
                "litellm/gpt-5-nano", PROXY, {"discord": native_discord_channel({"allowed_user_ids": ["D"]})}
            ),
        ),
    ]


class Pod:
    def __init__(self, base: Path):
        self.state = base / "state"
        self.config = base / "config"
        self.secrets = base / "secrets"
        self.files = base / "files"
        self.keys = base / "keys"
        self.out = base / "out"
        self.active = base / "active-bots.json"
        for path in (self.state, self.config, self.secrets, self.files, self.out):
            path.mkdir()
        for helper in ("communications-runtime-adapter.py", "agent-trigger-server.py"):
            (self.config / helper).write_text(HELPER_STUB)
        (self.out / "openclaw.py").write_text(FAKE_OPENCLAW)
        (self.state / "openclaw.json").write_text(json.dumps(_overlay(_bots())))

    def env(self, **extra) -> dict[str, str]:
        return {
            "PATH": os.environ["PATH"],
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            **PARENT_ENV,
            "BOT_STATE": str(self.state),
            "BOT_CONFIG": str(self.config),
            "BOT_SECRET_ROOT": str(self.secrets),
            "BOT_CONFIG_ROOT": str(self.files),
            "BOT_KEY_DIR": str(self.keys),
            "BOT_ACTIVE_FILE": str(self.active),
            "BOT_OPENCLAW_COMMAND": f'"{sys.executable}" "{self.out / "openclaw.py"}"',
            "BOT_JOB_RETRY_SECONDS": "0",
            "BOT_TEST_OUT": str(self.out),
            **extra,
        }

    def manifest(self, bots=(BOT_A, BOT_B), deleted=()):
        (self.config / "bots.json").write_text(
            json.dumps(
                {
                    "bots": [{"id": bot, "slot": slot} for slot, bot in enumerate(bots, start=1)],
                    "deleted_ids": list(deleted),
                }
            )
        )

    def bot(self, bot_id, secret=None, skills=None, scripts=None):
        directory = self.secrets / bot_id
        directory.mkdir()
        values = {
            "AGENT_ID": bot_id,
            "LITELLM_API_KEY": f"sk-{bot_id}",
            "TELEGRAM_BOT_TOKEN": f"1:{bot_id}",
            "COMMUNICATIONS_API_KEY": f"comms-{bot_id}",
            "INGEST_API_KEY": f"ingest-{bot_id}",
            "OPENCLAW_GATEWAY_TOKEN": f"own-{bot_id}",
            "RUNTIME_API_KEY": f"own-{bot_id}",
            "RUNTIME_MODEL": "openclaw/default",
            **(secret or {}),
        }
        for name, value in values.items():
            (directory / name).write_text(value)
        files = self.files / bot_id
        files.mkdir()
        (files / "AGENTS.md").write_text(
            "Send files from /home/node/.openclaw/workspace/out and /home/node/.openclaw/workspace."
        )
        for name in ("SOUL.md", "IDENTITY.md", "USER.md", "TOOLS.md", "BOOT.md", "BOOTSTRAP.md", "HEARTBEAT.md"):
            (files / name).write_text(f"bot {name}")
        if skills is not None:
            (files / "skills.json").write_text(json.dumps(skills))
        for name, body in (scripts or {}).items():
            (files / name).write_text(body)

    def setup(self, *args, **extra):
        return subprocess.run(
            [sys.executable, str(SETUP), *args],
            env=self.env(**extra),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def run_helper(self, bot_id, slot, helper="communications-runtime-adapter.py"):
        return subprocess.run(
            [sys.executable, str(RUN), bot_id, str(slot), str(self.config / helper)],
            env=self.env(),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def config_json(self) -> dict:
        return json.loads((self.state / "openclaw.json").read_text())

    def served(self) -> list[str]:
        return [entry["id"] for entry in json.loads(self.active.read_text())]


@pytest.fixture
def pod(tmp_path):
    return Pod(tmp_path)


def _wait_for(path: Path) -> Path:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not path.exists():
        time.sleep(0.2)
    return path


def test_no_manifest_does_nothing(pod):
    before = (pod.state / "openclaw.json").read_text()

    assert pod.setup().returncode == 0

    assert (pod.state / "openclaw.json").read_text() == before
    assert not pod.active.exists()


def test_a_bot_gets_its_own_workspace_agent_directory_and_home(pod):
    pod.manifest(bots=(BOT_A,))
    pod.bot(BOT_A)

    pod.setup()

    workspace = pod.state / f"workspace-{BOT_A}"
    for name in ("SOUL.md", "IDENTITY.md", "USER.md", "TOOLS.md", "BOOT.md", "BOOTSTRAP.md", "HEARTBEAT.md"):
        assert (workspace / name).read_text() == f"bot {name}"
    assert (pod.state / "agents" / BOT_A / "agent").is_dir()
    assert (pod.state / "bots" / BOT_A).is_dir()
    assert pod.served() == [BOT_A]


def test_a_bots_instructions_point_at_its_own_workspace(pod):
    pod.manifest(bots=(BOT_A,))
    pod.bot(BOT_A)

    pod.setup()

    workspace = pod.state / f"workspace-{BOT_A}"
    assert (workspace / "AGENTS.md").read_text() == (
        f"Send files from /home/node/.openclaw/workspace-{BOT_A}/out and /home/node/.openclaw/workspace-{BOT_A}."
    )


def test_a_bots_own_user_file_survives_a_restart(pod):
    pod.manifest(bots=(BOT_A,))
    pod.bot(BOT_A)
    pod.setup()
    (pod.state / f"workspace-{BOT_A}" / "USER.md").write_text("learned about the user")

    pod.setup()

    assert (pod.state / f"workspace-{BOT_A}" / "USER.md").read_text() == "learned about the user"


def test_a_bots_skills_are_written_into_its_workspace_and_cannot_escape_it(pod):
    pod.manifest(bots=(BOT_A,))
    pod.bot(BOT_A, skills=[{"path": "x/SKILL.md", "content": "skill"}, {"path": "../../escape.md", "content": "no"}])

    pod.setup()

    assert (pod.state / f"workspace-{BOT_A}" / "skills/x/SKILL.md").read_text() == "skill"
    assert not (pod.state / "escape.md").exists()


def test_a_bots_keys_go_to_a_private_file_with_only_its_keys(pod):
    pod.manifest(bots=(BOT_A,))
    pod.bot(BOT_A)

    pod.setup()

    key_file = pod.keys / f"{BOT_A}.json"
    assert json.loads(key_file.read_text()) == {"LITELLM_API_KEY": f"sk-{BOT_A}", "TELEGRAM_BOT_TOKEN": f"1:{BOT_A}"}
    if os.name != "nt":
        assert key_file.stat().st_mode & 0o777 == 0o600
        assert pod.keys.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("problem", ["missing", "mismatched", "no-key", "no-files"])
def test_a_bot_that_cannot_be_set_up_is_not_served_and_leaves_the_config(pod, problem):
    pod.manifest()
    pod.bot(BOT_A)
    if problem == "mismatched":
        pod.bot(BOT_B, secret={"AGENT_ID": BOT_A})
    elif problem == "no-key":
        pod.bot(BOT_B, secret={"LITELLM_API_KEY": ""})
    elif problem == "no-files":
        pod.bot(BOT_B)
        for path in (pod.files / BOT_B).iterdir():
            path.unlink()
        (pod.files / BOT_B).rmdir()

    assert pod.setup().returncode == 0

    assert pod.served() == [BOT_A]
    config = pod.config_json()
    assert list(config["agents"]["entries"]) == ["main", BOT_A]
    assert [binding["agentId"] for binding in config["bindings"]] == ["main", BOT_A]
    assert "discord" not in config["channels"]
    assert "litellm-bot-2" not in config["models"]["providers"]
    assert list(config["secrets"]["providers"]) == ["bot1"]
    assert config["plugins"]["entries"]["active-memory"]["config"]["agents"] == ["main", BOT_A]
    assert not (pod.keys / f"{BOT_B}.json").exists()


def test_rerunning_is_safe(pod):
    pod.manifest()
    pod.bot(BOT_A)
    pod.bot(BOT_B)

    pod.setup()
    first = pod.config_json()
    pod.setup()

    assert pod.config_json() == first
    assert pod.served() == [BOT_A, BOT_B]


def test_a_deleted_bots_files_and_key_are_removed(pod):
    for path in (f"workspace-{GONE}", f"agents/{GONE}/agent", f"bots/{GONE}/aai-cli"):
        (pod.state / path).mkdir(parents=True)
    pod.keys.mkdir()
    (pod.keys / f"{GONE}.json").write_text("{}")
    pod.manifest(bots=(), deleted=(GONE, "../escape"))
    (pod.state.parent / "escape").mkdir()

    assert pod.setup().returncode == 0

    for path in (f"workspace-{GONE}", f"agents/{GONE}", f"bots/{GONE}"):
        assert not (pod.state / path).exists()
    assert not (pod.keys / f"{GONE}.json").exists()
    assert (pod.state.parent / "escape").exists()
    assert pod.served() == []


def test_the_aai_cli_setup_runs_with_the_bots_own_files_and_values(pod):
    script = 'cp /app/config/aai-cli-config.toml "$BOT_TEST_OUT/copied.toml"\necho "$AGENT_ID" > "$BOT_TEST_OUT/setup-agent.txt"\n'
    pod.manifest(bots=(BOT_A,))
    pod.bot(BOT_A, scripts={"aai-cli-setup.sh": script, "aai-cli-config.toml": "bot profile"})

    pod.setup()

    assert (pod.out / "copied.toml").read_text() == "bot profile"
    assert (pod.out / "setup-agent.txt").read_text().strip() == BOT_A


def test_a_failing_setup_script_means_the_bot_is_not_served(pod):
    pod.manifest()
    pod.bot(BOT_A)
    pod.bot(BOT_B, scripts={"gog-setup.sh": "exit 3\n"})

    pod.setup()

    assert pod.served() == [BOT_A]


@HELPERS_NEED_POSIX
def test_a_helper_runs_as_its_bot_through_the_parents_gateway(pod):
    pod.manifest()
    pod.bot(BOT_A)
    pod.bot(BOT_B)
    pod.setup()

    assert pod.run_helper(BOT_B, 2).returncode == 0

    env = json.loads(_wait_for(pod.out / f"communications-runtime-adapter-{BOT_B}.json").read_text())
    assert env["AGENT_ID"] == BOT_B
    assert env["COMMUNICATIONS_API_KEY"] == f"comms-{BOT_B}"
    assert env["RUNTIME_API_URL"] == "http://127.0.0.1:18789"
    assert env["RUNTIME_API_KEY"] == env["OPENCLAW_GATEWAY_TOKEN"] == PARENT_TOKEN
    assert env["RUNTIME_MODEL"] == f"openclaw/{BOT_B}"
    assert env["RUNTIME_SESSION_PREFIX"] == f"agent:{BOT_B}:"
    assert env["AGENT_TRIGGER_PORT"] == "8102"
    assert env["AGENT_TRIGGER_RECEIPT_PATH"] == str(pod.state / "bots" / BOT_B / "agent-trigger-receipts.sqlite3")
    assert env["LITELLM_API_KEY"] == f"sk-{BOT_B}"
    assert "sk-parent" not in env.values()
    assert "ingest-parent" not in env.values()


@pytest.mark.parametrize("problem", ["unserved", "mismatched"])
def test_a_helper_never_starts_for_a_bot_that_is_not_served(pod, problem):
    pod.manifest(bots=(BOT_A,))
    pod.bot(BOT_A)
    pod.setup()
    target = BOT_B if problem == "unserved" else BOT_A
    if problem == "unserved":
        pod.bot(BOT_B)
    else:
        (pod.secrets / BOT_A / "AGENT_ID").write_text(BOT_B)

    assert pod.run_helper(target, 1).returncode == 1

    assert not (pod.out / f"communications-runtime-adapter-{target}.json").exists()


@HELPERS_NEED_POSIX
def test_launch_starts_both_helpers_for_served_bots_only(pod):
    pod.manifest()
    pod.bot(BOT_A)
    pod.setup()

    assert pod.setup("--launch").returncode == 0

    expected = {f"{helper}-{BOT_A}.json" for helper in ("communications-runtime-adapter", "agent-trigger-server")}
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not expected <= {path.name for path in pod.out.iterdir()}:
        time.sleep(0.2)
    assert expected <= {path.name for path in pod.out.iterdir()}
    assert not [path for path in pod.out.iterdir() if BOT_B in path.name]


def test_a_deleted_bots_jobs_are_removed_once_the_gateway_answers(pod):
    pod.manifest(bots=(BOT_A,), deleted=(GONE,))

    assert pod.setup("--clean-jobs").returncode == 0

    calls = json.loads((pod.out / "openclaw-calls.json").read_text())
    assert calls[0][:2] == calls[1][:2] == ["automations", "list"]
    assert calls[2:] == [["automations", "rm", "job-gone"]]


def test_no_deleted_bots_means_no_job_cleanup(pod):
    pod.manifest(bots=(BOT_A,))

    assert pod.setup("--clean-jobs").returncode == 0

    assert not (pod.out / "openclaw-calls.json").exists()


def test_startup_sets_up_bots_after_the_parents_integrations_and_launches_them_last():
    setup = START_SH.index("python3 /app/config/bot-setup.py\n")

    assert START_SH.index("sh /app/config/gog-setup.sh") < setup < START_SH.index("file-sync.py --once")
    launch = START_SH.index("python3 /app/config/bot-setup.py --launch")
    clean = START_SH.index("python3 /app/config/bot-setup.py --clean-jobs &")
    assert setup < launch < clean < START_SH.index("exec openclaw gateway")


def _init(tmp_path: Path, existing: dict, overlay: dict) -> dict:
    state = tmp_path / ".openclaw"
    state.mkdir(exist_ok=True)
    (state / "openclaw.json").write_text(json.dumps(existing))
    (tmp_path / "openclaw-config-overlay.json").write_text(json.dumps(overlay))
    script = tmp_path / "init-openclaw.js"
    script.write_text(
        INIT.read_text()
        .replace("'/app/config'", json.dumps(str(tmp_path)))
        .replace("const HOME = process.env.HOME || '/home/node';", f"const HOME = {json.dumps(str(tmp_path))};")
    )
    subprocess.run(["node", str(script)], check=True, capture_output=True)
    return json.loads((state / "openclaw.json").read_text())


def test_the_first_bot_makes_the_saved_config_multi_agent(tmp_path):
    overlay = _overlay(_bots())

    merged = _init(tmp_path, _overlay([]), overlay)

    for key in ("ownership", "entries"):
        assert merged["agents"][key] == overlay["agents"][key]
    assert merged["agents"]["defaults"]["systemAgent"] == {"agentId": "main"}
    assert merged["secrets"] == overlay["secrets"]
    assert merged["channels"] == overlay["channels"]


def test_removing_the_last_bot_returns_the_saved_config_to_one_agent(tmp_path):
    saved = _overlay(_bots())
    saved["secrets"]["providers"]["vault"] = {"source": "env"}

    merged = _init(tmp_path, saved, _overlay([]))

    assert "ownership" not in merged["agents"]
    assert "entries" not in merged["agents"]
    assert "systemAgent" not in merged["agents"]["defaults"]
    assert [name for name in merged["models"]["providers"] if name.startswith("litellm-bot-")] == []
    assert merged["secrets"]["providers"] == {"vault": {"source": "env"}}
    assert merged["channels"] == _overlay([])["channels"]
    assert merged["bindings"] == []


def test_removing_one_bot_leaves_nothing_of_it_in_the_saved_config(tmp_path):
    merged = _init(tmp_path, _overlay(_bots()), _overlay(_bots()[:1]))

    assert list(merged["agents"]["entries"]) == ["main", BOT_A]
    assert list(merged["models"]["providers"]) == ["litellm", "litellm-bot-1"]
    assert list(merged["secrets"]["providers"]) == ["bot1"]
