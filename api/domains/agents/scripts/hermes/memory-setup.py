"""Replace persistent Hindsight settings without writing the per-start credential."""

import json
import os
from pathlib import Path

import yaml


def main() -> int:
    managed = yaml.safe_load(Path("/app/config/hermes-config.yaml").read_text())
    memory = managed.get("memory", {})
    target = Path(os.environ.get("HERMES_HOME", "/opt/data")) / "hindsight" / "config.json"
    if memory.get("provider") != "hindsight":
        target.unlink(missing_ok=True)
        return 0
    if not os.environ.get("MEMORY_API_KEY") or not os.environ.get("MEMORY_URL"):
        raise RuntimeError("Agent Memory is enabled but its runtime credentials are missing.")
    settings = {**memory["hindsight"], "api_url": os.environ["MEMORY_URL"]}
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_suffix(".tmp")
    staged.write_text(json.dumps(settings))
    staged.chmod(0o600)
    staged.replace(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
