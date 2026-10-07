"""Deployment retries must preserve memory credentials and remote key identity."""

import ast
import base64
import copy
import hashlib
import json
import shlex
import stat
from pathlib import Path
from typing import Any

import pytest

from api.scripts import provision_memory as bootstrap


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """This deployment script uses Kubernetes and LiteLLM, not the product database."""
    yield


@pytest.fixture
def cluster(monkeypatch):
    state: dict[str, Any] = {
        "secrets": {},
        "keys": {},
        "issued": 0,
        "lose_response": False,
        "status": None,
        "pvc": False,
    }

    def kubectl(namespace: str, args: list[str], payload: dict[str, Any] | None = None) -> str:
        assert namespace == "agent-farm-staging"
        if args[:2] == ["get", "secret"]:
            secret = state["secrets"].get(args[2])
            return json.dumps(secret) if secret else ""
        if args[:2] == ["get", "pvc"]:
            return "persistentvolumeclaim/data-postgres-hindsight-0" if state["pvc"] else ""
        if args[0] == "create":
            assert payload is not None
            name = payload["metadata"]["name"]
            assert name not in state["secrets"]
            state["secrets"][name] = copy.deepcopy(payload)
            return "created"
        assert args[:4] == ["exec", "-i", "deploy/litellm", "--"]
        assert payload is not None
        if state["status"]:
            return json.dumps({"status": state["status"]})
        if payload["path"].startswith("/key/info?key="):
            info = state["keys"].get(payload["path"].split("=", 1)[1])
            return json.dumps({"status": 200, "body": {"info": info}} if info else {"status": 404})
        assert payload["path"] == "/key/generate"
        body = payload["body"]
        saved = bootstrap.decode_secret(state["secrets"][bootstrap.SECRET_NAME])
        # The exact candidate must already be durable when the remote API is called.
        assert body["key"] == saved["HINDSIGHT_LITELLM_API_KEY"]
        state["keys"][hashlib.sha256(body["key"].encode()).hexdigest()] = {
            **body,
            "expires": None,
            "blocked": False,
        }
        state["issued"] += 1
        if state["lose_response"]:
            state["lose_response"] = False
            raise bootstrap.ProvisioningError("Response lost after remote creation")
        return json.dumps({"status": 200, "body": {"key": body["key"]}})

    monkeypatch.setattr(bootstrap, "kubectl", kubectl)
    return state


def provision():
    return bootstrap.provision("agent-farm-staging", "openrouter/openai/gpt-4.1-mini", 5)


def test_redeployment_reuses_all_credentials_and_one_remote_key(cluster):
    first = provision()
    second = provision()
    assert second == first
    assert len(set(first.values())) == 4
    assert cluster["issued"] == 1
    info = next(iter(cluster["keys"].values()))
    assert info["models"] == ["openrouter/openai/gpt-4.1-mini"]
    assert info["team_id"] is None
    assert info["max_budget"] == 5
    assert info["budget_duration"] == "30d"


def test_lost_response_retries_the_persisted_key_without_issuing_another(cluster):
    cluster["lose_response"] = True
    with pytest.raises(bootstrap.ProvisioningError):
        provision()
    saved = bootstrap.decode_secret(cluster["secrets"][bootstrap.SECRET_NAME])
    assert provision() == saved
    assert cluster["issued"] == 1


@pytest.mark.parametrize("status", [401, 403, 500, 503])
def test_upstream_failures_preserve_credentials_without_issuing_keys(cluster, status):
    cluster["status"] = status
    with pytest.raises(bootstrap.ProvisioningError):
        provision()
    saved = copy.deepcopy(cluster["secrets"])
    with pytest.raises(bootstrap.ProvisioningError):
        provision()
    assert cluster["secrets"] == saved
    assert cluster["issued"] == 0


@pytest.mark.parametrize(
    "changes",
    [{"blocked": True}, {"team_id": "org-other"}, {"max_budget": None}, {"expires": "tomorrow"}],
)
def test_invalid_existing_key_is_never_replaced(cluster, changes):
    first = provision()
    next(iter(cluster["keys"].values())).update(changes)
    with pytest.raises(bootstrap.ProvisioningError):
        provision()
    assert bootstrap.decode_secret(cluster["secrets"][bootstrap.SECRET_NAME]) == first
    assert cluster["issued"] == 1


def test_storage_without_credentials_requires_recovery(cluster):
    cluster["pvc"] = True
    with pytest.raises(bootstrap.ProvisioningError, match="storage already exists"):
        provision()
    assert not cluster["secrets"]
    assert cluster["issued"] == 0


def test_existing_backend_secrets_are_adopted_without_rotation(cluster):
    original = provision()
    del cluster["secrets"][bootstrap.SECRET_NAME]
    cluster["secrets"].update(
        {
            "postgres-hindsight": {
                "data": {"POSTGRES_PASSWORD": base64.b64encode(original["HINDSIGHT_DB_PASSWORD"].encode()).decode()}
            },
            "hindsight": {
                "data": {
                    target: base64.b64encode(original[source].encode()).decode()
                    for source, target in (
                        ("HINDSIGHT_API_KEY", "HINDSIGHT_API_TENANT_API_KEY"),
                        ("MEMORY_RUNTIME_SERVICE_KEY", "AGENTBARN_MEMORY_SETTINGS_KEY"),
                        ("HINDSIGHT_LITELLM_API_KEY", "HINDSIGHT_API_LLM_API_KEY"),
                    )
                }
            },
        }
    )
    assert provision() == original
    assert cluster["issued"] == 1


def test_main_exports_credentials_to_private_file_without_logging_values(cluster, monkeypatch, tmp_path, capsys):
    destination = tmp_path / "credentials"
    destination.write_text("")
    destination.chmod(0o644)
    monkeypatch.setenv("NAMESPACE", "agent-farm-staging")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr("sys.argv", ["provision_memory.py", "--env-file", str(destination)])
    bootstrap.main()
    values = bootstrap.decode_secret(cluster["secrets"][bootstrap.SECRET_NAME])
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert dict(shlex.split(line)[0].split("=", 1) for line in destination.read_text().splitlines()) == values
    output = capsys.readouterr()
    assert all(value not in output.out + output.err for value in values.values())


def test_script_syntax_is_compatible_with_ci_runner_python():
    ast.parse(Path(bootstrap.__file__).read_text(), feature_version=(3, 10))


def test_budget_configuration_does_not_reset_existing_spend_policy(cluster):
    first = bootstrap.provision("agent-farm-staging", "openrouter/openai/gpt-4.1-mini", 10)
    assert provision() == first
    assert next(iter(cluster["keys"].values()))["max_budget"] == 10


def test_prepare_credentials_before_litellm_startup_then_verify_without_rotation(cluster, monkeypatch, tmp_path):
    destination = tmp_path / "credentials"
    monkeypatch.setenv("NAMESPACE", "agent-farm-staging")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr("sys.argv", ["provision_memory.py", "--credentials-only", "--env-file", str(destination)])
    bootstrap.main()
    prepared = destination.read_text()
    assert cluster["issued"] == 0
    monkeypatch.setattr("sys.argv", ["provision_memory.py", "--env-file", str(destination)])
    bootstrap.main()
    assert destination.read_text() == prepared
    assert cluster["issued"] == 1
