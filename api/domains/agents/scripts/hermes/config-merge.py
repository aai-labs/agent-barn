import os
import sys

import yaml

PRESERVED_KEYS = ("command_allowlist",)


def main() -> int:
    source, target = sys.argv[1], sys.argv[2]
    with open(source, encoding="utf-8") as handle:
        managed = yaml.safe_load(handle) or {}
    if not isinstance(managed, dict):
        return 1

    existing = {}
    if os.path.exists(target):
        try:
            with open(target, encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError):
            loaded = None
        if isinstance(loaded, dict):
            existing = loaded

    for key in PRESERVED_KEYS:
        value = existing.get(key)
        if value:
            managed[key] = value

    staged = f"{target}.tmp"
    with open(staged, "w", encoding="utf-8") as handle:
        yaml.safe_dump(managed, handle, default_flow_style=False, sort_keys=False)
    os.replace(staged, target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
