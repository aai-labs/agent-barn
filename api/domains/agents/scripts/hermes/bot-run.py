import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("BOT_ROOT", "/opt/data"))
ENV_DIR = Path(os.environ.get("BOT_ENV_DIR", "/run/agentbarn/env"))
SECRET_ROOT = Path(os.environ.get("BOT_SECRET_ROOT", "/run/agentbarn/bots"))
INHERITED_NAMES = ("PATH", "HOME", "LANG", "TZ", "VIRTUAL_ENV")
INHERITED_PREFIXES = ("LC_", "PYTHON", "SSL_")
TRIGGER_BASE_PORT = 8100


def main():
    bot_id, slot, script = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    active = ENV_DIR / "active-bots.json"
    served = json.loads(active.read_text(encoding="utf-8")) if active.exists() else []
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
    if bot_id not in [entry["id"] for entry in served] or secret.get("AGENT_ID") != bot_id:
        print(f"[bot-run] not starting {Path(script).name} for {bot_id}", flush=True)
        return 1

    env = {
        name: value
        for name, value in os.environ.items()
        if name in INHERITED_NAMES or name.startswith(INHERITED_PREFIXES)
    }
    env.update(secret)
    env["RUNTIME_API_URL"] = f"http://127.0.0.1:8642/p/{bot_id}"
    env["RUNTIME_API_KEY"] = secret["API_SERVER_KEY"]
    env["AGENT_TRIGGER_PORT"] = str(TRIGGER_BASE_PORT + slot)
    env["AGENTBARN_LLM_ERROR_MARKER"] = f"/tmp/agentbarn-llm-error-{bot_id}.json"
    env["BOOT_FILE"] = str(ROOT / "profiles" / bot_id / "BOOT.md")
    os.execve(sys.executable, [sys.executable, script], env)


if __name__ == "__main__":
    sys.exit(main())
