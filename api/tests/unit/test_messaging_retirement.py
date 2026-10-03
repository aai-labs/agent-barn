import importlib.util
import json
import sqlite3
import subprocess
import tarfile
from pathlib import Path

import pytest

from api.domains.agents.builders.openclaw import build_openclaw_gateway_config

_SCRIPTS = Path(__file__).parents[2] / "domains/agents/scripts"


def _retirement():
    spec = importlib.util.spec_from_file_location("retire_messaging_test", _SCRIPTS / "retire-messaging.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
@pytest.mark.parametrize("state_kind", ["fresh", "upgraded", "restored"])
def test_startup_retires_only_managed_bridge_and_preserves_jobs_history_and_spool(
    tmp_path, runtime, state_kind, capsys
):
    state = tmp_path / "state"
    plugin_root = "plugins" if runtime == "hermes" else "local-plugins"
    preserved = {}
    if state_kind != "fresh":
        files = {
            f"{plugin_root}/agentbarn-messaging/init": "old managed bridge",
            f"{plugin_root}/telemetry-push/init": "telemetry",
            f"{plugin_root}/agentbarn-observer/init": "observer",
            "npm/projects/native/node_modules/@openclaw/slack/package.json": "native plugin",
            "sessions/history": "conversation history",
            "agentbarn-messages.sqlite3": "private pending message content",
            "cron/jobs.json": json.dumps(
                {
                    "jobs": [
                        {
                            "id": "legacy",
                            "prompt": "private job content",
                            "schedule": "0 9 * * *",
                            "origin": {"platform": "api_server", "chat_id": "connection:old:C1:root"},
                            "delivery": {"channel": "last"},
                        },
                        {
                            "id": "native",
                            "deliver": "origin",
                            "origin": {"platform": "slack", "chat_id": "C1"},
                            "delivery": {"mode": "announce", "channel": "slack", "to": "C1"},
                        },
                    ]
                }
            ),
        }
        for name, content in files.items():
            path = state / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            if "agentbarn-messaging" not in name:
                preserved[name] = path.read_bytes()
        if state_kind == "restored":
            archive = tmp_path / "old-archive.tar"
            with tarfile.open(archive, "w") as tar:
                tar.add(state, arcname=".")
            state = tmp_path / "restored"
            with tarfile.open(archive) as tar:
                tar.extractall(state, filter="data")

    module = _retirement()
    report = module.retire(runtime, state)
    assert module.retire(runtime, state) == report
    assert not (state / plugin_root / "agentbarn-messaging").exists()
    assert report["jobs_requiring_repair"] == ([] if state_kind == "fresh" else ["legacy"])
    for name, content in preserved.items():
        assert (state / name).read_bytes() == content
    assert "private" not in capsys.readouterr().out
    assert "private" not in (state / "retired-messaging-audit.json").read_text()


def test_openclaw_audits_actual_sqlite_jobs_read_only(tmp_path):
    store = tmp_path / "state/openclaw.sqlite"
    store.parent.mkdir()
    with sqlite3.connect(store) as db:
        db.execute("CREATE TABLE cron_jobs (job_json TEXT)")
        db.execute("INSERT INTO cron_jobs VALUES (?)", (json.dumps({"id": "legacy", "delivery": {"channel": "last"}}),))
    before = store.read_bytes()
    report = _retirement().retire("openclaw", tmp_path)
    assert report["jobs_requiring_repair"] == ["legacy"]
    assert store.read_bytes() == before


def test_unreadable_job_store_is_reported_without_content_or_changes(tmp_path):
    store = tmp_path / "cron/jobs.json"
    store.parent.mkdir()
    store.write_text("private corrupt job store")
    report = _retirement().retire("hermes", tmp_path)
    assert report["job_audit"] == "unreadable"
    assert store.read_text() == "private corrupt job store"


def test_unwritable_audit_report_does_not_block_startup(tmp_path, capsys):
    state = tmp_path / "state"
    plugin = state / "plugins/agentbarn-messaging"
    plugin.mkdir(parents=True)
    state.chmod(0o555)
    try:
        report = _retirement().retire("hermes", state)
    finally:
        state.chmod(0o755)
    assert not plugin.exists()
    assert report["job_audit"] == "unwritable"
    assert "job_audit=unwritable" in capsys.readouterr().out


def test_openclaw_merged_config_cannot_resurrect_retired_plugin(tmp_path):
    state = tmp_path / ".openclaw"
    state.mkdir()
    config = {
        "plugins": {
            "allow": ["agentbarn-messaging", "other"],
            "entries": {"agentbarn-messaging": {"enabled": True}, "other": {"enabled": True}},
            "installs": {"agentbarn-messaging": {"path": "old"}, "slack": {"path": "native"}},
            "load": {"paths": ["/old/agentbarn-messaging/", "/other"]},
        },
    }
    (state / "openclaw.json").write_text(json.dumps(config))
    (tmp_path / "openclaw-config-overlay.json").write_text(
        json.dumps(build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000"))
    )
    script = tmp_path / "init-openclaw.js"
    script.write_text(
        (_SCRIPTS / "openclaw/init-openclaw.js")
        .read_text()
        .replace("'/app/config'", repr(str(tmp_path)))
        .replace("const HOME = process.env.HOME || '/home/node';", f"const HOME = {json.dumps(str(tmp_path))};")
    )
    subprocess.run(["node", str(script)], check=True, capture_output=True)
    merged = json.loads((state / "openclaw.json").read_text())
    assert "agentbarn-messaging" not in json.dumps(merged)
    assert merged["plugins"]["entries"]["other"] == {"enabled": True}
    assert merged["plugins"]["installs"]["slack"] == {"path": "native"}


@pytest.mark.parametrize(
    "job",
    [
        {"deliver": "origin"},
        {"deliver": "origin", "origin": {"platform": "slack", "chat_id": ""}},
        {"deliver": "slack"},
        {"deliver": "slack:__agentbarn_no_home_channel__"},
    ],
)
def test_unverified_hermes_destinations_are_reported_for_repair(tmp_path, monkeypatch, job):
    monkeypatch.delenv("SLACK_HOME_CHANNEL", raising=False)
    store = tmp_path / "cron/jobs.json"
    store.parent.mkdir()
    store.write_text(json.dumps({"jobs": [{"id": "needs-repair", **job}]}))
    report = _retirement().retire("hermes", tmp_path)
    assert report["jobs_requiring_repair"] == ["needs-repair"]


@pytest.mark.parametrize("home", ["", "__agentbarn_no_home_channel__", "C_HOME"])
def test_hermes_home_jobs_require_a_configured_target(monkeypatch, home):
    monkeypatch.setenv("SLACK_HOME_CHANNEL", home)
    assert _retirement().needs_repair("hermes", {"deliver": "slack", "origin": {"platform": "api_server"}}) == (
        home != "C_HOME"
    )


@pytest.mark.parametrize("deliver", ["slack:", "slack::thread", "origin:unknown", "slack:connection:old:C1:root"])
def test_invalid_explicit_job_target_does_not_fall_back_to_a_home(monkeypatch, deliver):
    monkeypatch.setenv("SLACK_HOME_CHANNEL", "C_HOME")
    job = {"deliver": deliver, "origin": {"platform": "slack", "chat_id": "C1"}}
    assert _retirement().needs_repair("hermes", job)
