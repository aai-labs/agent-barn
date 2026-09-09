"""The boot runner is the only thing that executes BOOT.md on Hermes.

Pinned Hermes reads BOOT.md solely through a `gateway:startup` hook it does not ship,
so without this script a template's boot checklist silently never runs -- no error, no
log line, just a cron job that never appears.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from hamcrest import assert_that, contains_string, equal_to, has_length

_MESSAGING = Path(__file__).parents[2] / "domains/agents/scripts/messaging"
_BOOT_RUN = Path(__file__).parents[2] / "domains/agents/scripts/hermes/boot-run.py"


def _load(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNTIME_API_URL", "http://runtime:8080")
    monkeypatch.setenv("RUNTIME_API_KEY", "runtime-key")
    monkeypatch.syspath_prepend(str(_MESSAGING))
    spec = importlib.util.spec_from_file_location("hermes_boot_run_test", _BOOT_RUN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.BOOT_FILE = tmp_path / "BOOT.md"
    sys.modules.pop("hermes_boot_run_test", None)
    return module


def _capture(module, monkeypatch, failures=0):
    """Record posted runs, failing the first `failures` attempts."""
    posted: list[dict] = []
    state = {"remaining": failures}

    def fake_post(path, payload):
        if state["remaining"]:
            state["remaining"] -= 1
            raise OSError("gateway not up yet")
        posted.append({"path": path, "payload": payload})
        return {"id": "run-1"}

    monkeypatch.setattr(module, "_post", fake_post)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    return posted


def test_boot_checklist_runs_under_a_session_with_no_conversation(monkeypatch, tmp_path):
    module = _load(monkeypatch, tmp_path)
    module.BOOT_FILE.write_text("## Cron Maintenance\n\nEnsure the time-teller job exists.")
    posted = _capture(module, monkeypatch)

    module.main()

    assert_that(posted, has_length(1))
    assert_that(posted[0]["path"], equal_to("/v1/runs"))
    payload = posted[0]["payload"]
    # The reserved session marks this run as having no originating conversation, which
    # is what routes jobs it creates to the Agent's configured default.
    assert_that(payload["session_id"], equal_to(module.BOOT_SESSION_ID))
    assert_that(payload["resume_session"], equal_to(False))
    assert_that(payload["input"], contains_string("Ensure the time-teller job exists."))


def test_a_missing_boot_file_submits_nothing(monkeypatch, tmp_path):
    module = _load(monkeypatch, tmp_path)
    posted = _capture(module, monkeypatch)

    module.main()

    assert_that(posted, equal_to([]))


@pytest.mark.parametrize("content", ["", "   \n\n  "])
def test_an_empty_boot_file_submits_nothing(monkeypatch, tmp_path, content):
    module = _load(monkeypatch, tmp_path)
    module.BOOT_FILE.write_text(content)
    posted = _capture(module, monkeypatch)

    module.main()

    assert_that(posted, equal_to([]))


def test_the_checklist_waits_for_a_gateway_that_is_not_listening_yet(monkeypatch, tmp_path):
    """start.sh backgrounds this before the gateway binds, so the first attempts fail."""
    module = _load(monkeypatch, tmp_path)
    module.BOOT_FILE.write_text("## Cron Maintenance\n\nEnsure the time-teller job exists.")
    posted = _capture(module, monkeypatch, failures=4)

    module.main()

    assert_that(posted, has_length(1))


def test_the_boot_session_is_the_one_communications_routes_to_the_default(monkeypatch, tmp_path):
    """Both halves must agree, or boot-created jobs are refused as unmappable origins."""
    module = _load(monkeypatch, tmp_path)
    import agentbarn_message

    assert_that(
        agentbarn_message.destination_for_origin({"platform": "api_server", "chat_id": module.BOOT_SESSION_ID}),
        equal_to({"kind": "default"}),
    )
    assert_that(json.dumps(module.BOOT_SESSION_ID), equal_to('"agentbarn-boot"'))
