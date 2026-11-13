import importlib.util
import sys
from pathlib import Path

import pytest

_PATCH = Path(__file__).parents[3] / "hermes-base" / "patch-bot-connected-status.py"

_SOURCE = """class Runner:
    def initial(self, profile_map, platform, adapter, profile_name, credential_claim, claimed):
        if True:
            if True:
                if success:
                    profile_map[platform] = adapter
                    if credential_claim is not None:
                        claimed[credential_claim] = profile_name

    def reconnect(self, profile_map, platform, adapter, profile_name):
        if True:
            if True:
                if True:
                        if platform not in profile_map:
                            profile_map[platform] = adapter
                            self._sync_voice_mode_state_to_adapter(adapter)
                            logger.info(
                                "connected again (profile: %s)",
                                platform.value,
                                profile_name,
                            )
"""

_CONNECTED = (
    'self._update_platform_runtime_status(f"{profile_name}:{platform.value}", '
    'platform_state="connected", error_code=None, error_message=None)'
)


def _load_patch():
    spec = importlib.util.spec_from_file_location("patch_bot_connected_status", _PATCH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _patch(monkeypatch, target: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["patch", str(target)])
    _load_patch().main()


def test_records_a_bot_as_connected_on_first_connect_and_on_reconnect(monkeypatch, tmp_path) -> None:
    target = tmp_path / "run.py"
    target.write_text(_SOURCE, encoding="utf-8")

    _patch(monkeypatch, target)

    patched = target.read_text(encoding="utf-8")
    assert patched.count(_CONNECTED) == 2
    compile(patched, str(target), "exec")


def test_patching_twice_changes_nothing(monkeypatch, tmp_path) -> None:
    target = tmp_path / "run.py"
    target.write_text(_SOURCE, encoding="utf-8")

    _patch(monkeypatch, target)
    once = target.read_text(encoding="utf-8")
    _patch(monkeypatch, target)

    assert target.read_text(encoding="utf-8") == once


@pytest.mark.parametrize("anchor", ["credential_claim is not None", "_sync_voice_mode_state_to_adapter"])
def test_a_changed_hermes_source_fails_the_build(monkeypatch, tmp_path, anchor) -> None:
    target = tmp_path / "run.py"
    target.write_text(_SOURCE.replace(anchor, "something else"), encoding="utf-8")

    with pytest.raises(SystemExit):
        _patch(monkeypatch, target)
