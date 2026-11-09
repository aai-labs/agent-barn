from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.secret_scope import (  # ty: ignore[unresolved-import]
    build_profile_secret_scope,
    reset_secret_scope,
    set_multiplex_active,
    set_secret_scope,
)
from gateway.authz_mixin import _platform_gate_env  # ty: ignore[unresolved-import]
from gateway.config import GatewayConfig, Platform, PlatformConfig, load_gateway_config  # ty: ignore[unresolved-import]
from gateway.delivery import resolve_delivery_transport  # ty: ignore[unresolved-import]
from hermes_cli.profiles import validate_profile_name  # ty: ignore[unresolved-import]
from hermes_constants import reset_hermes_home_override, set_hermes_home_override  # ty: ignore[unresolved-import]
from tools.env_passthrough import resolve_passthrough_value  # ty: ignore[unresolved-import]

BOT_A = "aaaaaaaa-0000-4000-8000-00000000000a"
BOT_B = "bbbbbbbb-0000-4000-8000-00000000000b"


def home(root: Path, name: str, env: dict[str, str]) -> Path:
    path = root / "profiles" / name
    path.mkdir(parents=True)
    (path / ".env").write_text("".join(f"{key}={value}\n" for key, value in env.items()))
    (path / "config.yaml").write_text("platforms:\n  api_server:\n    enabled: false\n")
    return path


def check(label: str, condition: bool) -> None:
    if not condition:
        raise SystemExit(f"FAILED: {label}")
    print(f"ok: {label}")


def in_scope(path: Path, read):
    token = set_secret_scope(build_profile_secret_scope(path))
    try:
        return read()
    finally:
        reset_secret_scope(token)


def main() -> None:
    root = Path(tempfile.mkdtemp())
    first = home(
        root,
        BOT_A,
        {"ARTIFACT_API_KEY": "key-a", "ONLY_A": "a", "SLACK_BOT_TOKEN": "xoxb-a", "SLACK_APP_TOKEN": "xapp-a"},
    )
    second = home(root, BOT_B, {"ARTIFACT_API_KEY": "key-b", "SLACK_BOT_TOKEN": "xoxb-b", "SLACK_APP_TOKEN": "xapp-b"})
    os.environ.update({"ARTIFACT_API_KEY": "", "ONLY_A": "", "AGENTBARN_SLACK_DM_POLICY": "open"})
    set_multiplex_active(True)

    check("a Bot's id is a valid profile name", validate_profile_name(BOT_A) is None)

    def read_key() -> str | None:
        return resolve_passthrough_value("ARTIFACT_API_KEY", "")

    check("passthrough reads the first Bot's value", in_scope(first, read_key) == "key-a")
    check("passthrough reads the second Bot's value", in_scope(second, read_key) == "key-b")
    check(
        "a name another Bot holds does not reach this Bot",
        not in_scope(second, lambda: resolve_passthrough_value("ONLY_A", "")),
    )

    check(
        "the Slack gate never falls through to process env",
        in_scope(first, lambda: _platform_gate_env("AGENTBARN_SLACK_DM_POLICY", "off")) == "off",
    )

    plugin = Path("/slack-access/__init__.py")
    spec = importlib.util.spec_from_file_location("slack_access", plugin)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.register(MagicMock())
    print("ok: the Slack access plugin registers against this Hermes")

    parent = SimpleNamespace(name="parent adapter")
    shared = GatewayConfig(platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="parent")})
    transport = resolve_delivery_transport(Platform.TELEGRAM, shared, {Platform.TELEGRAM: parent})
    check("a shared platform delivers through the parent's connection", transport.adapter is parent)
    check(
        "a platform the parent lacks has no live transport",
        resolve_delivery_transport(Platform.SLACK, shared, {Platform.TELEGRAM: parent}) is None,
    )

    def bot_slack_token(path: Path) -> str | None:
        token = set_hermes_home_override(path)
        try:
            platform = load_gateway_config().platforms.get(Platform.SLACK)
            return platform.token if platform else None
        finally:
            reset_hermes_home_override(token)

    check(
        "a Bot's scheduled delivery uses its own credential",
        in_scope(first, lambda: bot_slack_token(first)) == "xoxb-a",
    )
    check("another Bot's delivery uses its own", in_scope(second, lambda: bot_slack_token(second)) == "xoxb-b")
    print("All Bot checks passed")


if __name__ == "__main__":
    sys.exit(main())
