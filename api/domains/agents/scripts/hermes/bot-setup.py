import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("BOT_ROOT", "/opt/data"))
WORKSPACE = Path(os.environ.get("BOT_WORKSPACE", "/workspace"))
CONFIG = Path(os.environ.get("BOT_CONFIG", "/app/config"))
ENV_DIR = Path(os.environ.get("BOT_ENV_DIR", "/run/agentbarn/env"))
SECRET_ROOT = Path(os.environ.get("BOT_SECRET_ROOT", "/run/agentbarn/bots"))
CONFIG_ROOT = Path(os.environ.get("BOT_CONFIG_ROOT", "/app/bots"))
ACTIVE_FILE = "active-bots.json"
BOT_ID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
ALLOWLIST_KEY = "command_allowlist"
SIDECAR = "agentbarn-command-allowlist.json"
PROFILE_ENV_NAMES = (
    "API_SERVER_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_BASE_URL",
    "FIRECRAWL_API_KEY",
    "FIRECRAWL_API_URL",
    "FIRECRAWL_BROWSER_TTL",
    "AGENT_ID",
    "INGEST_URL",
    "INGEST_API_KEY",
)
PLATFORM_PREFIXES = ("SLACK_", "TELEGRAM_", "AGENTBARN_SLACK_")
MEMORY_PREFIXES = ("MEMORY_", "HINDSIGHT_")
PERSONALITY_FILES = ("IDENTITY.md", "TOOLS.md", "BOOT.md", "HEARTBEAT.md")
PLUGINS = (
    ("telemetry-push", "telemetry-push"),
    ("agentbarn-observer", "agentbarn-observer"),
    ("agentbarn-slack-access", "slack-access"),
)
HELPERS = ("communications-runtime-adapter.py", "agent-trigger-server.py", "boot-run.py")


def log(message):
    print(f"[bot-setup] {message}", flush=True)


def quote(value):
    needs_quoting = (
        "#" in value or '"' in value or "'" in value or value != value.strip() or any(c.isspace() for c in value)
    )
    if not needs_quoting:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_env(path, values):
    lines = []
    for name, value in values.items():
        if "\n" in value or "\r" in value or "${" in value:
            log(f"left out {name}")
            continue
        lines.append(f"{name}={quote(value)}\n")
    staged = path.with_name(f"{path.name}.tmp")
    staged.write_text("".join(lines), encoding="utf-8")
    staged.chmod(0o600)
    staged.replace(path)


def link(target, link_path):
    if link_path.is_symlink() or link_path.exists():
        link_path.unlink()
    link_path.symlink_to(target)


def remove_tree(path):
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def env_values(source, home, passthrough):
    names = [*PROFILE_ENV_NAMES, *passthrough, *[name for name in source if name.startswith(PLATFORM_PREFIXES)]]
    values = {name: source[name] for name in names if source.get(name)}
    if source.get("MEMORY_API_KEY"):
        values["HINDSIGHT_API_KEY"] = source["MEMORY_API_KEY"]
    values["AAI_CONFIG"] = str(home / ".config/aai-cli/config.toml")
    return values


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
    if secret.get("AGENT_ID") != bot_id or not secret.get("API_SERVER_KEY"):
        raise ValueError("missing or mismatched Secret")
    return secret


def localized(text, bot_id, home):
    for old, new in (
        *[(f"/workspace/{name}", f"{home}/{name}") for name in (*PERSONALITY_FILES, "AGENTS.md")],
        ("/opt/data/memories/", f"{home}/memories/"),
        ("/workspace/skills", f"{home}/skills"),
        ("./skills/", f"{home}/skills/"),
        ("/workspace/memory/", f"{WORKSPACE}/bots/{bot_id}/memory/"),
    ):
        text = text.replace(old, new)
    return text


def write_config(files, home, passthrough):
    config = yaml.safe_load((files / "hermes-config.yaml").read_text(encoding="utf-8"))
    config.setdefault("skills", {})["external_dirs"] = [str(home / "skills")]
    config.setdefault("terminal", {})["env_passthrough"] = passthrough
    target = home / "config.yaml"
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as staged:
        yaml.safe_dump(config, staged, default_flow_style=False, sort_keys=False)
    try:
        subprocess.run([sys.executable, str(CONFIG / "config-merge.py"), staged.name, str(target)], check=True)
    except subprocess.CalledProcessError:
        shutil.copyfile(staged.name, target)
    finally:
        os.unlink(staged.name)


def write_skills(files, home):
    skills = home / "skills"
    remove_tree(skills)
    skills.mkdir(parents=True)
    manifest = files / "skills.json"
    if not manifest.exists():
        return
    for entry in json.loads(manifest.read_text(encoding="utf-8")):
        target = (skills / entry["path"]).resolve()
        if not target.is_relative_to(skills.resolve()):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(entry["content"], encoding="utf-8")


def setup_bot(bot_id, passthrough):
    secret = read_secret(bot_id)
    files = CONFIG_ROOT / bot_id
    home = ROOT / "profiles" / bot_id
    if home.is_symlink():
        home.unlink()
    for directory in (home / "memories", home / ".config/aai-cli", WORKSPACE / "bots" / bot_id / "memory"):
        directory.mkdir(parents=True, exist_ok=True)

    write_config(files, home, passthrough)
    agents = localized((files / "AGENTS.md").read_text(encoding="utf-8"), bot_id, home)
    soul = localized((files / "SOUL.md").read_text(encoding="utf-8"), bot_id, home)
    (home / "SOUL.md").write_text(f"{soul}\n\n{agents}", encoding="utf-8")
    (home / "AGENTS.md").write_text(agents, encoding="utf-8")
    for name in PERSONALITY_FILES:
        (home / name).write_text(localized((files / name).read_text(encoding="utf-8"), bot_id, home), encoding="utf-8")
    user = home / "memories/USER.md"
    if not user.exists():
        shutil.copyfile(files / "USER.md", user)
    for plugin, source in PLUGINS:
        if (files / f"{source}-plugin.yaml").exists():
            directory = home / "plugins" / plugin
            directory.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(files / f"{source}-plugin.yaml", directory / "plugin.yaml")
            shutil.copyfile(files / f"{source}-init.py", directory / "__init__.py")
    write_skills(files, home)

    values = env_values(secret, home, passthrough)
    environment = {name: value for name, value in os.environ.items() if not name.startswith(MEMORY_PREFIXES)}
    subprocess.run(
        [sys.executable, str(CONFIG / "memory-setup.py")],
        check=True,
        env={
            **environment,
            **{name: value for name, value in values.items() if name.startswith(MEMORY_PREFIXES)},
            "HERMES_HOME": str(home),
        },
    )
    for name in ("aai-cli-setup.sh", "gog-setup.sh"):
        setup_script = files / name
        if setup_script.exists():
            script = setup_script.read_text(encoding="utf-8").replace("/app/config/", f"{files}/")
            subprocess.run(["sh", "-c", script], check=True, env={**environment, **values})
    target = ENV_DIR / f"{bot_id}.env"
    write_env(target, values)
    link(target, home / ".env")


def setup_parent(passthrough):
    target = ENV_DIR / "default.env"
    values = env_values(dict(os.environ), ROOT, passthrough)
    if os.environ.get("API_SERVER_MODEL_NAME"):
        values["API_SERVER_MODEL_NAME"] = os.environ["API_SERVER_MODEL_NAME"]
    write_env(target, values)
    link(target, ROOT / ".env")
    config_path = ROOT / "config.yaml"
    if config_path.exists():
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        config.setdefault("terminal", {})["env_passthrough"] = passthrough
        config_path.write_text(yaml.safe_dump(config, default_flow_style=False, sort_keys=False), encoding="utf-8")
    soul = ROOT / "SOUL.md"
    instructions = (CONFIG / "AGENTS.md").read_text(encoding="utf-8")
    soul.write_text(f"{soul.read_text(encoding='utf-8')}\n\n{instructions}", encoding="utf-8")
    (WORKSPACE / "AGENTS.md").write_text("", encoding="utf-8")


def clean_deleted(manifest):
    for bot_id in manifest.get("deleted_ids", []):
        if not BOT_ID_PATTERN.fullmatch(bot_id):
            log("ignored an invalid deleted id")
            continue
        for path in (ROOT / "profiles" / bot_id, WORKSPACE / "bots" / bot_id):
            try:
                remove_tree(path)
            except OSError as error:
                log(f"could not remove {bot_id}: {type(error).__name__}")


def live_entries(manifest):
    entries = []
    for entry in manifest.get("bots", []):
        if BOT_ID_PATTERN.fullmatch(entry["id"]):
            entries.append(entry)
        else:
            log("ignored an invalid bot id")
    return entries


def read_allowlist(home):
    try:
        loaded = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        loaded = {}
    current = loaded.get(ALLOWLIST_KEY) if isinstance(loaded, dict) else None
    if isinstance(current, list):
        return [entry for entry in current if isinstance(entry, str)]
    try:
        stored = json.loads((home / SIDECAR).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [entry for entry in stored if isinstance(entry, str)] if isinstance(stored, list) else []


def sync_allowlists(manifest):
    homes = [ROOT, *[ROOT / "profiles" / entry["id"] for entry in live_entries(manifest)]]
    existing = [home for home in homes if (home / "config.yaml").exists()]
    if not existing:
        return
    newest = max(existing, key=lambda home: (home / "config.yaml").stat().st_mtime_ns)
    chosen = read_allowlist(newest)
    for home in homes:
        home.mkdir(parents=True, exist_ok=True)
        (home / SIDECAR).write_text(json.dumps(chosen), encoding="utf-8")
        config_path = home / "config.yaml"
        if not config_path.exists():
            continue
        try:
            loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        loaded.pop(ALLOWLIST_KEY, None)
        config_path.write_text(yaml.safe_dump(loaded, default_flow_style=False, sort_keys=False), encoding="utf-8")
    log(f"synced {len(chosen)} approvals")


def launch():
    active = ENV_DIR / ACTIVE_FILE
    if not active.exists():
        return
    runner = Path(__file__).with_name("bot-run.py")
    for entry in json.loads(active.read_text(encoding="utf-8")):
        for helper in HELPERS:
            subprocess.Popen([sys.executable, str(runner), entry["id"], str(entry["slot"]), str(CONFIG / helper)])


def main():
    manifest_path = CONFIG / "bots.json"
    if not manifest_path.exists():
        return 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if "--sync-allowlists" in sys.argv:
        sync_allowlists(manifest)
        return 0
    if "--launch" in sys.argv:
        launch()
        return 0

    clean_deleted(manifest)
    entries = live_entries(manifest)
    if not entries:
        return 0

    ENV_DIR.mkdir(parents=True, exist_ok=True)
    passthrough = manifest.get("passthrough", [])
    setup_parent(passthrough)
    served = []
    for entry in entries:
        try:
            setup_bot(entry["id"], passthrough)
            served.append(entry)
        except Exception as error:
            log(f"could not set up {entry['id']}: {type(error).__name__}")
    (ENV_DIR / ACTIVE_FILE).write_text(json.dumps(served), encoding="utf-8")
    log(f"serving {len(served)} of {len(entries)} bots")
    return 0


if __name__ == "__main__":
    sys.exit(main())
