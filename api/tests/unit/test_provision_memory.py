"""Prepare stable authentication credentials and load hook-generated hashes."""

import ast
import base64
import copy
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
def cluster(monkeypatch):
    state: dict[str, Any] = {"secrets": {}, "pvc": False}

    def kubectl(namespace: str, args: list[str], payload: dict[str, Any] | None = None) -> str:
        if args[:2] == ["get", "secret"]:
            saved = state["secrets"].get((namespace, args[2]))
            return json.dumps(saved) if saved else ""
        if args[:2] == ["get", "pvc"]:
            return "persistentvolumeclaim/data-postgres-hindsight-0" if state["pvc"] else ""
        assert args[0] == "create" and payload is not None
        name = (namespace, payload["metadata"]["name"])
        assert name not in state["secrets"]
        state["secrets"][name] = copy.deepcopy(payload)
        return "created"

    monkeypatch.setattr(bootstrap, "kubectl", kubectl)
    return state


def encoded(values):
    return {"data": {name: base64.b64encode(value.encode()).decode() for name, value in values.items()}}


def test_redeployment_reuses_authentication_credentials(cluster):
    first = bootstrap.credentials("agent-farm-staging")
    assert bootstrap.credentials("agent-farm-staging") == first
    assert len(set(first.values())) == 3
    assert "HINDSIGHT_LITELLM_API_KEY" not in first


def test_environments_get_independent_authentication_credentials(cluster):
    staging = bootstrap.credentials("agent-farm-staging")
    production = bootstrap.credentials("agent-farm")
    assert set(staging.values()).isdisjoint(production.values())


def test_storage_without_credentials_requires_recovery(cluster):
    cluster["pvc"] = True
    with pytest.raises(bootstrap.ProvisioningError, match="storage already exists"):
        bootstrap.credentials("agent-farm-staging")
    assert not cluster["secrets"]


def test_existing_backend_secrets_are_adopted_without_rotation(cluster):
    original = bootstrap.credentials("agent-farm-staging")
    del cluster["secrets"][("agent-farm-staging", bootstrap.SECRET_NAME)]
    cluster["secrets"].update(
        {
            ("agent-farm-staging", "postgres-hindsight"): encoded(
                {"POSTGRES_PASSWORD": original["HINDSIGHT_DB_PASSWORD"]}
            ),
            ("agent-farm-staging", "hindsight"): encoded(
                {
                    "HINDSIGHT_API_TENANT_API_KEY": original["HINDSIGHT_API_KEY"],
                    "AGENTBARN_MEMORY_SETTINGS_KEY": original["MEMORY_RUNTIME_SERVICE_KEY"],
                }
            ),
        }
    )
    assert bootstrap.credentials("agent-farm-staging") == original


def test_main_exports_only_private_credentials_and_hook_hashes(cluster, monkeypatch, tmp_path, capsys):
    destination = tmp_path / "credentials"
    destination.write_text("")
    destination.chmod(0o644)
    monkeypatch.setenv("NAMESPACE", "agent-farm-staging")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr("sys.argv", ["provision_memory.py", "--env-file", str(destination)])
    bootstrap.main()
    values = bootstrap.credentials("agent-farm-staging")
    # A previous provisioner may have persisted a key. Never export it to the runner.
    cluster["secrets"][("agent-farm-staging", bootstrap.SECRET_NAME)]["data"]["HINDSIGHT_LITELLM_API_KEY"] = (
        base64.b64encode(b"sk-obsolete-key").decode()
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
