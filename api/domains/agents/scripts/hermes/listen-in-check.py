"""Fall back to mentions when the listen-in guard can't load.

Free-response rooms answer every message, and only the agentbarn-listen-in plugin
keeps them quiet. Hermes starts anyway when a plugin fails to load, so this loads
Hermes the way the gateway does, asks its plugin manager whether the guard loaded
and, if not, removes the rooms and the plugin from the config.
"""

import os
import sys
from pathlib import Path

import yaml

_PLUGIN = "agentbarn-listen-in"
_ROOM_SETTINGS = (
    ("slack", "free_response_channels"),
    ("discord", "free_response_channels"),
    ("telegram", "free_response_chats"),
)


def _load_failure() -> str | None:
    sys.path.insert(0, "/opt/hermes")
    import run_agent  # noqa: F401  # ty: ignore[unresolved-import]
    from hermes_cli.plugins import get_plugin_manager  # ty: ignore[unresolved-import]

    loaded = get_plugin_manager()._plugins.get(_PLUGIN)
    if loaded is None:
        return "Hermes did not load the plugin"
    if loaded.error or not loaded.enabled:
        return loaded.error or "Hermes did not enable the plugin"
    return None if loaded.hooks_registered else "the plugin registered no hooks"


def _disable_listen_in(config: dict, config_path: Path) -> None:
    config["plugins"]["enabled"].remove(_PLUGIN)
    for platform, setting in _ROOM_SETTINGS:
        (config.get(platform) or {}).pop(setting, None)
        extra = ((config.get("platforms") or {}).get(platform) or {}).get("extra") or {}
        if setting in extra:
            extra[setting] = []
    staged = config_path.with_name(f"{config_path.name}.tmp")
    staged.write_text(yaml.safe_dump(config, default_flow_style=False, sort_keys=False))
    os.replace(staged, config_path)


def check(config_path: Path) -> None:
    config = yaml.safe_load(config_path.read_text()) or {}
    if _PLUGIN not in ((config.get("plugins") or {}).get("enabled") or []):
        return
    os.environ["HERMES_HOME"] = str(config_path.parent)
    try:
        failure = _load_failure()
    except Exception as exc:
        failure = repr(exc)
    if failure:
        print(f"[listen-in-check] guard failed to load, answering mentions only: {failure}", file=sys.stderr)
        _disable_listen_in(config, config_path)


if __name__ == "__main__":
    check(Path(sys.argv[1]))
