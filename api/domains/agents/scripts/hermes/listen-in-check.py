"""Fall back to mentions when the listen-in guard can't load.

Free-response rooms answer every message, and only the agentbarn-listen-in plugin
keeps them quiet. Hermes starts anyway when a plugin fails to load, so this loads
it first and, if that fails, removes the rooms and the plugin from the config.
"""

import importlib.util
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


class _Probe:
    def __init__(self) -> None:
        self.registered = 0

    def register_hook(self, *_) -> None:
        self.registered += 1

    def register_tool(self, *_) -> None:
        self.registered += 1


def _load_guard(config_path: Path, plugin_path: Path) -> None:
    os.environ["HERMES_HOME"] = str(config_path.parent)
    spec = importlib.util.spec_from_file_location("agentbarn_listen_in_check", plugin_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"no plugin at {plugin_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    probe = _Probe()
    module.register(probe)
    if not probe.registered:
        raise RuntimeError("the plugin registered nothing")


def _disable_listen_in(config: dict, config_path: Path) -> None:
    config["plugins"]["enabled"].remove(_PLUGIN)
    for platform, setting in _ROOM_SETTINGS:
        (config.get(platform) or {}).pop(setting, None)
    staged = config_path.with_name(f"{config_path.name}.tmp")
    staged.write_text(yaml.safe_dump(config, default_flow_style=False, sort_keys=False))
    os.replace(staged, config_path)


def check(config_path: Path, plugin_path: Path) -> None:
    config = yaml.safe_load(config_path.read_text()) or {}
    if _PLUGIN not in ((config.get("plugins") or {}).get("enabled") or []):
        return
    try:
        _load_guard(config_path, plugin_path)
    except Exception as exc:
        print(f"[listen-in-check] guard failed to load, answering mentions only: {exc!r}", file=sys.stderr)
        _disable_listen_in(config, config_path)


if __name__ == "__main__":
    check(Path(sys.argv[1]), Path(sys.argv[2]))
