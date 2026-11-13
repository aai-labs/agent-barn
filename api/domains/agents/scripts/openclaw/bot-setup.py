import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

STATE = Path(os.environ.get("BOT_STATE", "/home/node/.openclaw"))
CONFIG = Path(os.environ.get("BOT_CONFIG", "/app/config"))
SECRET_ROOT = Path(os.environ.get("BOT_SECRET_ROOT", "/run/agentbarn/bots"))
CONFIG_ROOT = Path(os.environ.get("BOT_CONFIG_ROOT", "/app/bots"))
KEY_DIR = Path(os.environ.get("BOT_KEY_DIR", "/tmp/agentbarn-keys"))
ACTIVE = Path(os.environ.get("BOT_ACTIVE_FILE", "/tmp/agentbarn-active-bots.json"))
OPENCLAW = shlex.split(os.environ.get("BOT_OPENCLAW_COMMAND", "openclaw"))
JOB_RETRY_SECONDS = float(os.environ.get("BOT_JOB_RETRY_SECONDS", "5"))
JOB_ATTEMPTS = 24
BOT_ID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
POD_WORKSPACE = "/home/node/.openclaw/workspace"
PARENT_WORKSPACE = re.compile(re.escape(POD_WORKSPACE) + r"(?![\w-])")
KEY_NAMES = ("LITELLM_API_KEY", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN")
WORKSPACE_FILES = (
    "SOUL.md",
    "IDENTITY.md",
    "USER.md",
    "TOOLS.md",
    "AGENTS.md",
    "BOOT.md",
    "BOOTSTRAP.md",
    "HEARTBEAT.md",
)
AGENT_OWNED_FILES = ("USER.md",)
SETUP_SCRIPTS = ("aai-cli-setup.sh", "gog-setup.sh")
HELPERS = ("communications-runtime-adapter.py", "agent-trigger-server.py")


def log(message):
    print(f"[bot-setup] {message}", flush=True)


def remove_tree(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def read_secret(bot_id):
    directory = SECRET_ROOT / bot_id
    secret = (
        {
            path.name: path.read_text()
            for path in directory.iterdir()
            if path.is_file() and not path.name.startswith("..")
        }
        if directory.is_dir()
        else {}
    )
    if secret.get("AGENT_ID") != bot_id or not secret.get("LITELLM_API_KEY"):
        raise ValueError("missing or mismatched Secret")
    return secret


def write_keys(bot_id, secret):
    KEY_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    KEY_DIR.chmod(0o700)
    target = KEY_DIR / f"{bot_id}.json"
    staged = target.with_name(f"{target.name}.tmp")
    descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump({name: secret[name] for name in KEY_NAMES if secret.get(name)}, handle)
    staged.chmod(0o600)
    staged.replace(target)


def write_workspace(files, workspace, bot_id):
    workspace.mkdir(parents=True, exist_ok=True)
    for name in WORKSPACE_FILES:
        source = files / name
        target = workspace / name
        if not source.exists() or (name in AGENT_OWNED_FILES and target.exists()):
            continue
        text = PARENT_WORKSPACE.sub(f"{POD_WORKSPACE}-{bot_id}", source.read_text(encoding="utf-8"))
        target.write_text(text, encoding="utf-8")
    manifest = files / "skills.json"
    if not manifest.exists():
        return
    skills = (workspace / "skills").resolve()
    for entry in json.loads(manifest.read_text(encoding="utf-8")):
        target = (skills / entry["path"]).resolve()
        if not target.is_relative_to(skills):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(entry["content"], encoding="utf-8")


def setup_bot(bot_id):
    secret = read_secret(bot_id)
    files = CONFIG_ROOT / bot_id
    if not (files / "AGENTS.md").exists():
        raise ValueError("missing ConfigMap")
    workspace = STATE / f"workspace-{bot_id}"
    write_workspace(files, workspace, bot_id)
    (STATE / "agents" / bot_id / "agent").mkdir(parents=True, exist_ok=True)
    (STATE / "bots" / bot_id).mkdir(parents=True, exist_ok=True)
    for name in SETUP_SCRIPTS:
        script = files / name
        if script.exists():
            body = script.read_text(encoding="utf-8").replace("/app/config/", f"{files.as_posix()}/")
            subprocess.run(["sh", "-c", body], check=True, env={**os.environ, **secret})
    write_keys(bot_id, secret)


def live_entries(manifest):
    entries = []
    for entry in manifest.get("bots", []):
        if BOT_ID_PATTERN.fullmatch(str(entry.get("id", ""))) and isinstance(entry.get("slot"), int):
            entries.append(entry)
        else:
            log("ignored an invalid bot entry")
    return entries


def deleted_ids(manifest):
    ids = []
    for bot_id in manifest.get("deleted_ids", []):
        if BOT_ID_PATTERN.fullmatch(str(bot_id)):
            ids.append(bot_id)
        else:
            log("ignored an invalid deleted id")
    return ids


def clean_deleted(manifest):
    for bot_id in deleted_ids(manifest):
        for path in (
            STATE / f"workspace-{bot_id}",
            STATE / "agents" / bot_id,
            STATE / "bots" / bot_id,
            KEY_DIR / f"{bot_id}.json",
        ):
            try:
                remove_tree(path)
            except OSError as error:
                log(f"could not remove {bot_id}: {type(error).__name__}")


def prune(unserved):
    path = STATE / "openclaw.json"
    if not unserved or not path.exists():
        return
    config = json.loads(path.read_text(encoding="utf-8"))
    ids = {entry["id"] for entry in unserved}
    for entry in unserved:
        (config.get("models", {}).get("providers") or {}).pop(f"litellm-bot-{entry['slot']}", None)
        (config.get("secrets", {}).get("providers") or {}).pop(f"bot{entry['slot']}", None)
        (KEY_DIR / f"{entry['id']}.json").unlink(missing_ok=True)
    entries = config.get("agents", {}).get("entries") or {}
    for bot_id in ids:
        entries.pop(bot_id, None)
    config["bindings"] = [binding for binding in config.get("bindings", []) if binding.get("agentId") not in ids]
    channels = config.get("channels") or {}
    for platform in list(channels):
        accounts = channels[platform].get("accounts")
        if accounts is None:
            continue
        for bot_id in ids:
            accounts.pop(bot_id, None)
        if not accounts:
            del channels[platform]
    memory = config.get("plugins", {}).get("entries", {}).get("active-memory", {}).get("config")
    if memory and isinstance(memory.get("agents"), list):
        memory["agents"] = [agent for agent in memory["agents"] if agent not in ids]
    staged = path.with_name(f"{path.name}.bot-setup")
    staged.write_text(json.dumps(config, indent=2), encoding="utf-8")
    staged.replace(path)


def setup(manifest):
    clean_deleted(manifest)
    entries = live_entries(manifest)
    served, unserved = [], []
    for entry in entries:
        try:
            setup_bot(entry["id"])
            served.append(entry)
        except Exception as error:
            log(f"could not set up {entry['id']}: {type(error).__name__}")
            unserved.append(entry)
    prune(unserved)
    ACTIVE.write_text(json.dumps(served), encoding="utf-8")
    log(f"serving {len(served)} of {len(entries)} bots")


def launch():
    if not ACTIVE.exists():
        return
    runner = Path(__file__).with_name("bot-run.py")
    for entry in json.loads(ACTIVE.read_text(encoding="utf-8")):
        for helper in HELPERS:
            subprocess.Popen([sys.executable, str(runner), entry["id"], str(entry["slot"]), str(CONFIG / helper)])


def clean_jobs(manifest):
    gone = set(deleted_ids(manifest))
    if not gone:
        return
    for _ in range(JOB_ATTEMPTS):
        listed = subprocess.run(
            [*OPENCLAW, "automations", "list", "--all", "--json"], capture_output=True, text=True, check=False
        )
        if listed.returncode == 0:
            break
        time.sleep(JOB_RETRY_SECONDS)
    else:
        log("could not list scheduled jobs")
        return
    jobs = json.loads(listed.stdout).get("jobs", [])
    for job in jobs:
        if job.get("agentId") in gone:
            removed = subprocess.run(
                [*OPENCLAW, "automations", "rm", job["id"]], capture_output=True, text=True, check=False
            )
            if removed.returncode != 0:
                log("could not remove a deleted bot's job")
    log(f"removed jobs for {len(gone)} deleted bots")


def main():
    manifest_path = CONFIG / "bots.json"
    if not manifest_path.exists():
        return 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if "--launch" in sys.argv:
        launch()
    elif "--clean-jobs" in sys.argv:
        clean_jobs(manifest)
    else:
        setup(manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
