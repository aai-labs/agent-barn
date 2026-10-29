"""Prepare stable authentication credentials and load hook-generated hashes."""

import ast
import base64
import json
import shlex
import stat
from pathlib import Path
from typing import Any

import pytest

from api.scripts import provision_memory as bootstrap


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    yield


@pytest.fixture
def supplied_credentials(monkeypatch):
    values = {name: "test-" + name for name in bootstrap.CREDENTIAL_NAMES}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


@pytest.fixture
def cluster(monkeypatch):
    state: dict[str, Any] = {"secrets": {}}

    def kubectl(namespace: str, args: list[str], payload=None) -> str:
        assert args[:2] == ["get", "secret"]  # Credential preparation never writes cluster secrets.
        saved = state["secrets"].get((namespace, args[2]))
        return json.dumps(saved) if saved else ""

    monkeypatch.setattr(bootstrap, "kubectl", kubectl)
    return state


def encoded(values):
    return {"data": {name: base64.b64encode(value.encode()).decode() for name, value in values.items()}}


def test_uses_supplied_credentials_without_cluster_generation(supplied_credentials, cluster):
    assert bootstrap.credentials() == supplied_credentials
    assert not cluster["secrets"]


def test_missing_secret_fails_without_generating_replacement(supplied_credentials, monkeypatch, cluster):
    monkeypatch.delenv("HINDSIGHT_DB_PASSWORD")
    with pytest.raises(bootstrap.ProvisioningError, match="HINDSIGHT_DB_PASSWORD"):
        bootstrap.credentials()
    assert not cluster["secrets"]


def test_duplicate_credentials_fail(supplied_credentials, monkeypatch):
    monkeypatch.setenv("MEMORY_RUNTIME_SERVICE_KEY", supplied_credentials["HINDSIGHT_API_KEY"])
    with pytest.raises(bootstrap.ProvisioningError, match="must differ"):
        bootstrap.credentials()


def test_main_exports_only_private_credentials_and_hook_hashes(
    supplied_credentials, cluster, monkeypatch, tmp_path, capsys
):
    destination = tmp_path / "credentials"
    destination.write_text("")
    destination.chmod(0o644)
    monkeypatch.setenv("NAMESPACE", "agent-farm-staging")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr("sys.argv", ["provision_memory.py", "--env-file", str(destination)])
    bootstrap.main()
    values = bootstrap.credentials()
    cluster["secrets"][("agent-farm-staging", "agentbarn-memory-bootstrap")] = encoded(
        {"HINDSIGHT_LITELLM_API_KEY": "sk-obsolete-key"}
    )
    hashes = {"MEMORY_LITELLM_ACTIVE_KEY_HASH": "a" * 64, "MEMORY_LITELLM_KEY_HASHES": "a" * 64 + "," + "b" * 64}
    cluster["secrets"][("agent-farm-staging", "hindsight-litellm-hashes")] = encoded(hashes)
    monkeypatch.setattr("sys.argv", ["provision_memory.py", "--include-key-hashes", "--env-file", str(destination)])
    bootstrap.main()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert dict(shlex.split(line)[0].split("=", 1) for line in destination.read_text().splitlines()) == values | hashes
    output = capsys.readouterr()
    assert all(value not in output.out + output.err for value in values.values())
    assert "sk-obsolete-key" not in destination.read_text()


def test_missing_hook_hash_secret_fails_closed(cluster):
    with pytest.raises(bootstrap.ProvisioningError, match="has not created"):
        bootstrap.key_hashes("agent-farm-staging")


def test_invalid_hook_hashes_fail_closed(cluster):
    cluster["secrets"][("agent-farm-staging", "hindsight-litellm-hashes")] = encoded(
        {"MEMORY_LITELLM_ACTIVE_KEY_HASH": "a" * 64, "MEMORY_LITELLM_KEY_HASHES": "sk-plaintext-key"}
    )
    with pytest.raises(bootstrap.ProvisioningError, match="invalid attribution hashes"):
        bootstrap.key_hashes("agent-farm-staging")


def test_script_syntax_is_compatible_with_ci_runner_python():
    ast.parse(Path(bootstrap.__file__).read_text(), feature_version=(3, 10))
