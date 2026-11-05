import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("PERSONA_ROOT", "/opt/data"))
WORKSPACE = Path(os.environ.get("PERSONA_WORKSPACE", "/workspace"))
CONFIG = Path(os.environ.get("PERSONA_CONFIG", "/app/config"))
ENV_DIR = Path(os.environ.get("PERSONA_ENV_DIR", "/run/agentbarn/env"))
ACTIVE_FILE = "active-personas.json"
KEY_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
ALLOWLIST_KEY = "command_allowlist"
SIDECAR = "agentbarn-command-allowlist.json"
STRIPPED_SECTIONS = ("platforms", "slack", "discord", "telegram")
PERSONA_ENV_NAMES = (
    "API_SERVER_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_BASE_URL",
    "FIRECRAWL_API_KEY",
    "FIRECRAWL_API_URL",
    "FIRECRAWL_BROWSER_TTL",
    "HINDSIGHT_API_KEY",
)
DEFAULT_ENV_NAMES = (*PERSONA_ENV_NAMES, "API_SERVER_MODEL_NAME")


def log(message):
    print(f"[persona-setup] {message}", flush=True)


def quote(value):
    if value == "":
        return value
    needs_quoting = (
        "#" in value or '"' in value or "'" in value or value != value.strip() or any(c.isspace() for c in value)
    )
    if not needs_quoting:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_env(path, names):
    lines = []
    for name in names:
        value = os.environ.get(name)
        if value is None:
            continue
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


def persona_config():
    config = copy.deepcopy(yaml.safe_load((CONFIG / "hermes-config.yaml").read_text(encoding="utf-8")) or {})
    for section in STRIPPED_SECTIONS:
        config.pop(section, None)
    if isinstance(config.get("display"), dict):
        config["display"].pop("platforms", None)
    config["plugins"] = {"enabled": ["telemetry-push"]}
    config["platforms"] = {"api_server": {"enabled": False}}
    config.setdefault("skills", {}).setdefault("external_dirs", []).append(str(ROOT / "skills"))
    return config


def write_persona_config(home):
    target = home / "config.yaml"
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as staged:
        yaml.safe_dump(persona_config(), staged, default_flow_style=False, sort_keys=False)
    try:
        subprocess.run([sys.executable, str(CONFIG / "config-merge.py"), staged.name, str(target)], check=True)
    except subprocess.CalledProcessError:
        shutil.copyfile(staged.name, target)
    finally:
        os.unlink(staged.name)


def setup_persona(key):
    home = ROOT / "profiles" / key
    if home.is_symlink():
        home.unlink()
    (home / "memories").mkdir(parents=True, exist_ok=True)
    plugin_dir = home / "plugins" / "telemetry-push"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (WORKSPACE / "personas" / key / "memory").mkdir(parents=True, exist_ok=True)

    shutil.copyfile(CONFIG / f"persona-{key}-SOUL.md", home / "SOUL.md")
    shutil.copyfile(CONFIG / f"persona-{key}-IDENTITY.md", home / "IDENTITY.md")
    user = home / "memories" / "USER.md"
    if not user.exists():
        shutil.copyfile(CONFIG / "USER.md", user)
    shutil.copyfile(CONFIG / "telemetry-push-plugin.yaml", plugin_dir / "plugin.yaml")
    shutil.copyfile(CONFIG / "telemetry-push-init.py", plugin_dir / "__init__.py")

    write_persona_config(home)
    subprocess.run(
        [sys.executable, str(CONFIG / "memory-setup.py")],
        check=True,
        env={**os.environ, "HERMES_HOME": str(home)},
    )
    target = ENV_DIR / f"{key}.env"
    write_env(target, PERSONA_ENV_NAMES)
    link(target, home / ".env")


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


def active_keys(manifest):
    keys = []
    for entry in manifest.get("active", []):
        if KEY_PATTERN.fullmatch(entry["key"]):
            keys.append(entry["key"])
        else:
            log("ignored an invalid active key")
    return keys


def sync_allowlists(manifest):
    homes = [ROOT, *[ROOT / "profiles" / key for key in active_keys(manifest)]]
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


def clean_deleted(manifest):
    for key in manifest.get("deleted_keys", []):
        if not KEY_PATTERN.fullmatch(key):
            log("ignored an invalid deleted key")
            continue
        for path in (ROOT / "profiles" / key, WORKSPACE / "personas" / key):
            try:
                remove_tree(path)
            except OSError as error:
                log(f"could not remove {key}: {type(error).__name__}")


def clean_env_temp_files():
    for leftover in [*ROOT.glob(".env_*"), *ROOT.glob("profiles/*/.env_*")]:
        try:
            leftover.unlink(missing_ok=True)
        except OSError as error:
            log(f"could not remove a temporary env file: {type(error).__name__}")


def main():
    manifest_path = CONFIG / "personas.json"
    if not manifest_path.exists():
        return 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if "--sync-allowlists" in sys.argv:
        sync_allowlists(manifest)
        return 0

    clean_deleted(manifest)
    clean_env_temp_files()
    keys = active_keys(manifest)
    if not keys:
        return 0

    ENV_DIR.mkdir(parents=True, exist_ok=True)
    default_target = ENV_DIR / "default.env"
    write_env(default_target, [*DEFAULT_ENV_NAMES, *manifest.get("default_env_names", [])])
    link(default_target, ROOT / ".env")

    served = []
    for key in keys:
        try:
            setup_persona(key)
            served.append(key)
        except Exception as error:
            log(f"could not set up {key}: {type(error).__name__}")
    (ENV_DIR / ACTIVE_FILE).write_text(json.dumps(served), encoding="utf-8")
    log(f"serving {len(served)} of {len(keys)} personas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
