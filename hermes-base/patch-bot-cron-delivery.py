import sys
from pathlib import Path

EDITS = {
    "gateway/run.py": (
        (
            '                cron_start_kwargs["profile_homes"] = profile_homes\n',
            (
                '                cron_start_kwargs["profile_homes"] = profile_homes\n'
                '                cron_start_kwargs["profile_adapters"] = runner._profile_adapters\n'
            ),
        ),
    ),
    "cron/scheduler_provider.py": (
        (
            "        profile_homes=None,\n    ):\n",
            "        profile_homes=None,\n        profile_adapters=None,\n    ):\n",
        ),
        (
            "                profile_homes=profile_homes,\n                adapters=adapters,\n",
            (
                "                profile_homes=profile_homes,\n"
                "                profile_adapters=profile_adapters,\n"
                "                adapters=adapters,\n"
            ),
        ),
        (
            "        profile_homes,\n        adapters=None,\n",
            "        profile_homes,\n        profile_adapters=None,\n        adapters=None,\n",
        ),
        (
            (
                "                                cron_tick(\n"
                "                                    verbose=False,\n"
                "                                    adapters=adapters,\n"
            ),
            (
                "                                cron_tick(\n"
                "                                    verbose=False,\n"
                '                                    adapters=adapters if entry[0] == "default" '
                "else (profile_adapters or {}).get(entry[0], {}),\n"
            ),
        ),
    ),
    "tools/send_message_tool.py": (
        (
            (
                "        try:\n"
                "            adapter = runner.adapters.get(platform)\n"
                "        except Exception:\n"
                "            adapter = None\n"
            ),
            (
                "        try:\n"
                "            from hermes_constants import get_hermes_home\n"
                '            adapter = None if get_hermes_home().parent.name == "profiles" '
                "else runner.adapters.get(platform)\n"
                "        except Exception:\n"
                "            adapter = None\n"
            ),
        ),
    ),
}


def patched(source, edits):
    for before, after in edits:
        if after in source:
            continue
        if source.count(before) != 1:
            raise SystemExit("Hermes Bot delivery source changed; review the Bot delivery patch")
        source = source.replace(before, after)
    return source


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/opt/hermes")
    results = {}
    for relative, edits in EDITS.items():
        target = root / relative
        result = patched(target.read_text(encoding="utf-8"), edits)
        compile(result, str(target), "exec")
        results[target] = result
    for target, result in results.items():
        target.write_text(result, encoding="utf-8")


if __name__ == "__main__":
    main()
