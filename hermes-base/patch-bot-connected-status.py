import sys
from pathlib import Path

STATUS = (
    'self._update_platform_runtime_status(f"{profile_name}:{platform.value}", '
    'platform_state="connected", error_code=None, error_message=None)\n'
)
EDITS = (
    (
        "                    profile_map[platform] = adapter\n",
        "                    if credential_claim is not None:\n",
    ),
    (
        "                            profile_map[platform] = adapter\n",
        "                            self._sync_voice_mode_state_to_adapter(adapter)\n",
    ),
)


def patched(source):
    for before, after in EDITS:
        indent = before[: len(before) - len(before.lstrip())]
        inserted = before + indent + STATUS + after
        if inserted in source:
            continue
        if source.count(before + after) != 1:
            raise SystemExit("Hermes Bot connection source changed; review the Bot status patch")
        source = source.replace(before + after, inserted)
    return source


def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/opt/hermes/gateway/run.py")
    source = target.read_text(encoding="utf-8")
    result = patched(source)
    compile(result, str(target), "exec")
    if result != source:
        target.write_text(result, encoding="utf-8")


if __name__ == "__main__":
    main()
