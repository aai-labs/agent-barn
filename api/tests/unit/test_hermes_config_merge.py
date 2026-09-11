"""start.sh copied the ConfigMap over /opt/data/config.yaml on every boot, which is
where Hermes persists an `always` approval as root-level `command_allowlist` -- so
every pod restart silently revoked every permanent approval.

The merge has to run in one direction only. Agent Barn owns every settings-derived
key (model, approvals.mode, plugins, web, browser); preserving those from the PVC
would freeze an agent on whatever it first started with, so a user could switch
Manual to Off in the UI, get a 200, restart, and still be prompted.
"""

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

_MERGE_SCRIPT = Path(__file__).parents[2] / "domains/agents/scripts/hermes/config-merge.py"

_MANAGED = {
    "model": {"default": "gpt-5"},
    "approvals": {"mode": "off"},
    "plugins": {"enabled": ["telemetry-push"]},
}


@pytest.fixture
def merge():
    spec = importlib.util.spec_from_file_location("hermes_config_merge", _MERGE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(merge, tmp_path: Path, target_text: str | None, *, mode: str = "off") -> dict:
    source = tmp_path / "hermes-config.yaml"
    source.write_text(yaml.safe_dump({**_MANAGED, "approvals": {"mode": mode}}), encoding="utf-8")
    target = tmp_path / "config.yaml"
    if target_text is not None:
        target.write_text(target_text, encoding="utf-8")

    merge.sys.argv = ["config-merge.py", str(source), str(target)]
    assert merge.main() == 0
    return yaml.safe_load(target.read_text(encoding="utf-8"))


def _saved(tmp_path: Path) -> list[str]:
    return json.loads((tmp_path / "agentbarn-command-allowlist.json").read_text(encoding="utf-8"))


def test_manual_mode_hides_saved_grants_from_the_runtime(merge, tmp_path: Path) -> None:
    granted_in_auto = yaml.safe_dump({"command_allowlist": ["script execution via -e/-c flag"]})

    merged = _run(merge, tmp_path, granted_in_auto, mode="manual")

    assert "command_allowlist" not in merged
    assert _saved(tmp_path) == ["script execution via -e/-c flag"]


def test_grants_come_back_when_manual_mode_is_left(merge, tmp_path: Path) -> None:
    _run(merge, tmp_path, yaml.safe_dump({"command_allowlist": ["recursive delete"]}), mode="manual")
    manual_config = (tmp_path / "config.yaml").read_text(encoding="utf-8")

    merged = _run(merge, tmp_path, manual_config, mode="smart")

    assert merged["command_allowlist"] == ["recursive delete"]


def test_a_grant_made_since_the_last_boot_joins_the_saved_ones(merge, tmp_path: Path) -> None:
    (tmp_path / "agentbarn-command-allowlist.json").write_text(json.dumps(["recursive delete"]), encoding="utf-8")

    merged = _run(merge, tmp_path, yaml.safe_dump({"command_allowlist": ["recursive delete", "cargo *"]}), mode="smart")

    assert merged["command_allowlist"] == ["recursive delete", "cargo *"]
    assert _saved(tmp_path) == ["recursive delete", "cargo *"]


def test_a_corrupt_saved_grant_file_still_yields_a_bootable_runtime(merge, tmp_path: Path) -> None:
    (tmp_path / "agentbarn-command-allowlist.json").write_text("{not json", encoding="utf-8")

    merged = _run(merge, tmp_path, None, mode="smart")

    assert merged == {**_MANAGED, "approvals": {"mode": "smart"}}


def test_permanent_approvals_survive_a_restart(merge, tmp_path: Path) -> None:
    existing = yaml.safe_dump({"command_allowlist": ["cargo *", "git status"], "model": {"default": "stale-model"}})

    merged = _run(merge, tmp_path, existing)

    assert merged["command_allowlist"] == ["cargo *", "git status"]


def test_settings_derived_keys_are_never_taken_from_the_pvc(merge, tmp_path: Path) -> None:
    stale = yaml.safe_dump(
        {
            "command_allowlist": ["cargo *"],
            "model": {"default": "stale-model"},
            "approvals": {"mode": "manual"},
            "plugins": {"enabled": ["something-removed"]},
        }
    )

    merged = _run(merge, tmp_path, stale)

    assert merged["model"] == {"default": "gpt-5"}
    assert merged["approvals"] == {"mode": "off"}
    assert merged["plugins"] == {"enabled": ["telemetry-push"]}


def test_first_boot_writes_the_managed_config(merge, tmp_path: Path) -> None:
    merged = _run(merge, tmp_path, None)

    assert merged == _MANAGED
    assert "command_allowlist" not in merged


def test_a_corrupt_pvc_config_still_yields_a_bootable_runtime(merge, tmp_path: Path) -> None:
    merged = _run(merge, tmp_path, "{{ not: valid: yaml")

    assert merged == _MANAGED


def test_an_empty_allowlist_is_not_carried_forward(merge, tmp_path: Path) -> None:
    merged = _run(merge, tmp_path, yaml.safe_dump({"command_allowlist": []}))

    assert "command_allowlist" not in merged


def test_the_target_is_replaced_atomically(merge, tmp_path: Path) -> None:
    _run(merge, tmp_path, yaml.safe_dump({"command_allowlist": ["cargo *"]}))

    assert not list(tmp_path.glob("*.tmp"))
