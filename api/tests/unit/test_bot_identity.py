import importlib.util
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "domains/agents/scripts"
HERMES = SCRIPTS / "hermes"
PARENT_ENV = {"AGENT_ID": "parent", "INGEST_URL": "http://parent", "INGEST_API_KEY": "parent-key"}
ADAPTER_ENV = {
    "COMMUNICATIONS_URL": "http://communications",
    "COMMUNICATIONS_API_KEY": "key",
    "AGENT_ID": "agent",
    "RUNTIME_API_URL": "http://runtime",
    "RUNTIME_API_KEY": "key",
    "RUNTIME_MODEL": "model",
}


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _installed_plugin(home: Path, plugin: str):
    target = home / "plugins" / plugin
    target.mkdir(parents=True)
    shutil.copy(HERMES / "plugins" / plugin / "__init__.py", target / "__init__.py")
    return _load(target / "__init__.py", f"{plugin.replace('-', '_')}_{home.name}")


@pytest.fixture
def parent_env(monkeypatch):
    for name, value in PARENT_ENV.items():
        monkeypatch.setenv(name, value)


def _write_env(home: Path, text: str) -> None:
    (home / ".env").write_text(text)


BOT_ENV = 'AGENT_ID=bot\nINGEST_URL=http://bot\nINGEST_API_KEY="bot key"\n'


def test_telemetry_uses_its_own_homes_identity(tmp_path, parent_env):
    module = _installed_plugin(tmp_path, "telemetry-push")
    _write_env(tmp_path, BOT_ENV)

    module.register(MagicMock())

    assert (module._agent_id, module._ingest_url, module._ingest_api_key) == ("bot", "http://bot", "bot key")


def test_telemetry_without_a_home_identity_uses_the_process(tmp_path, parent_env):
    module = _installed_plugin(tmp_path, "telemetry-push")

    module.register(MagicMock())

    assert module._agent_id == "parent"


def test_a_home_env_written_by_hermes_is_not_mistaken_for_an_identity(tmp_path, parent_env):
    module = _installed_plugin(tmp_path, "telemetry-push")
    _write_env(tmp_path, "SLACK_HOME_CHANNEL=C1\n")

    module.register(MagicMock())

    assert module._agent_id == "parent"


def test_the_observer_reports_as_its_own_home(tmp_path, parent_env):
    module = _installed_plugin(tmp_path, "agentbarn-observer")
    _write_env(tmp_path, BOT_ENV)

    with patch.object(module.threading, "Thread") as thread:
        module.register(MagicMock())

    url, api_key, home = thread.call_args.kwargs["args"]
    assert (url, api_key) == ("http://bot/agents/bot/communication-events", "bot key")
    assert home == tmp_path.resolve()


def test_the_observer_without_a_home_identity_uses_the_process(tmp_path, parent_env, monkeypatch):
    module = _installed_plugin(tmp_path, "agentbarn-observer")
    monkeypatch.setenv("HERMES_HOME", "/opt/data")

    with patch.object(module.threading, "Thread") as thread:
        module.register(MagicMock())

    url, _, home = thread.call_args.kwargs["args"]
    assert url == "http://parent/agents/parent/communication-events"
    assert home == Path("/opt/data")


def test_the_slack_gate_never_falls_through_to_another_bots_settings():
    source = (HERMES / "plugins/agentbarn-slack-access/__init__.py").read_text()

    assert "_platform_gate_env" in source
    assert "_auth_env" not in source


def _load_healthz():
    with patch("http.server.HTTPServer"), patch("http.server.ThreadingHTTPServer"), patch("threading.Thread"):
        return _load(HERMES / "healthz-server.py", "healthz_server")


def _healthz(monkeypatch, multiplex):
    monkeypatch.delenv("AGENTBARN_LLM_ERROR_MARKER", raising=False)
    if multiplex:
        monkeypatch.setenv("GATEWAY_MULTIPLEX_PROFILES", "1")
    else:
        monkeypatch.delenv("GATEWAY_MULTIPLEX_PROFILES", raising=False)
    return _load_healthz()


def _adapter(monkeypatch, api_key):
    for name, value in ADAPTER_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("OPENAI_API_KEY", api_key)
    return _load(SCRIPTS / "communications-runtime-adapter.py", "runtime_adapter")


def test_each_bots_llm_error_marker_is_its_own(monkeypatch):
    healthz = _healthz(monkeypatch, multiplex=True)

    assert healthz._llm_error_marker("key-a") != healthz._llm_error_marker("key-b")


def test_the_proxy_and_the_adapter_agree_on_a_bots_marker(monkeypatch):
    healthz = _healthz(monkeypatch, multiplex=True)

    assert _adapter(monkeypatch, "key-a")._LLM_ERROR_MARKER == healthz._llm_error_marker("key-a")


def test_without_bots_there_is_one_marker(monkeypatch):
    healthz = _healthz(monkeypatch, multiplex=False)

    assert healthz._llm_error_marker("key-a") == "/tmp/agentbarn-llm-terminal-error.json"
    assert _adapter(monkeypatch, "key-a")._LLM_ERROR_MARKER == "/tmp/agentbarn-llm-terminal-error.json"


def test_recording_an_error_writes_only_that_keys_marker(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTBARN_LLM_ERROR_MARKER", str(tmp_path / "marker"))
    monkeypatch.setenv("GATEWAY_MULTIPLEX_PROFILES", "1")
    healthz = _load_healthz()

    healthz._record_terminal_llm_error("SPEND_LIMIT_REACHED", "key-a")

    assert Path(healthz._llm_error_marker("key-a")).exists()
    assert not Path(healthz._llm_error_marker("key-b")).exists()
