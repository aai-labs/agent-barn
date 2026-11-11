import json
import os
import sys
from pathlib import Path

STATE = Path(os.environ.get("BOT_STATE", "/home/node/.openclaw"))
SECRET_ROOT = Path(os.environ.get("BOT_SECRET_ROOT", "/run/agentbarn/bots"))
ACTIVE = Path(os.environ.get("BOT_ACTIVE_FILE", "/tmp/agentbarn-active-bots.json"))
INHERITED_NAMES = ("PATH", "HOME", "LANG", "TZ")
INHERITED_PREFIXES = ("LC_", "PYTHON", "SSL_")
TRIGGER_BASE_PORT = 8100


def main():
    bot_id, slot, script = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    served = json.loads(ACTIVE.read_text(encoding="utf-8")) if ACTIVE.exists() else []
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
    gateway_token = os.environ["OPENCLAW_GATEWAY_TOKEN"]
    env["OPENCLAW_GATEWAY_TOKEN"] = env["RUNTIME_API_KEY"] = gateway_token
    env["RUNTIME_API_URL"] = os.environ["RUNTIME_API_URL"]
    env["RUNTIME_MODEL"] = f"openclaw/{bot_id}"
    env["RUNTIME_SESSION_PREFIX"] = f"agent:{bot_id}:"
    env["AGENT_TRIGGER_PORT"] = str(TRIGGER_BASE_PORT + slot)
    env["AGENT_TRIGGER_RECEIPT_PATH"] = str(STATE / "bots" / bot_id / "agent-trigger-receipts.sqlite3")
    os.execve(sys.executable, [sys.executable, script], env)


if __name__ == "__main__":
    sys.exit(main())
