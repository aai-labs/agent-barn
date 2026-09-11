import json
import os
import sys

import yaml

ALLOWLIST_KEY = "command_allowlist"
SIDECAR_NAME = "agentbarn-command-allowlist.json"
MANUAL_MODE = "manual"


def _load_yaml(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _load_sidecar(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, ValueError):
        return []
    return [entry for entry in loaded if isinstance(entry, str)] if isinstance(loaded, list) else []


def _write_atomically(path: str, write) -> None:
    staged = f"{path}.tmp"
    with open(staged, "w", encoding="utf-8") as handle:
        write(handle)
    os.replace(staged, path)


def main() -> int:
    source, target = sys.argv[1], sys.argv[2]
    with open(source, encoding="utf-8") as handle:
        managed = yaml.safe_load(handle) or {}
    if not isinstance(managed, dict):
        return 1

    sidecar = os.path.join(os.path.dirname(target), SIDECAR_NAME)
    current = _load_yaml(target).get(ALLOWLIST_KEY)
    written = [entry for entry in current if isinstance(entry, str)] if isinstance(current, list) else []
    saved = list(dict.fromkeys([*_load_sidecar(sidecar), *written]))
    _write_atomically(sidecar, lambda handle: json.dump(saved, handle))

    approvals = managed.get("approvals")
    mode = approvals.get("mode") if isinstance(approvals, dict) else None
    if saved and mode != MANUAL_MODE:
        managed[ALLOWLIST_KEY] = saved

    _write_atomically(
        target,
        lambda handle: yaml.safe_dump(managed, handle, default_flow_style=False, sort_keys=False),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
