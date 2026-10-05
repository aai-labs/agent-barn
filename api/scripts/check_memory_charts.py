"""Render the memory deployments with synthetic credentials and check isolation."""

import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


def render(chart: str, values: dict[str, Any]) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory() as directory:
        values_file = Path(directory) / "values.yaml"
        values_file.write_text(yaml.safe_dump(values))
        result = subprocess.run(
            ["helm", "template", chart, str(ROOT / "helm" / chart), "-f", str(values_file)],
            check=True,
            text=True,
            capture_output=True,
        )
    return [document for document in yaml.safe_load_all(result.stdout) if document]


def main() -> None:
    compose = yaml.safe_load((ROOT / "compose.yml").read_text())
    services = compose["services"]
    local = services["hindsight"]
    database = services["hindsight-db"]
    assert local["profiles"] == database["profiles"] == ["local-hindsight"]
    assert local["image"] == "ghcr.io/vectorize-io/hindsight:0.10.2"
    assert database["image"] == "pgvector/pgvector:pg18"
    assert "ports" not in local and "ports" not in database
    assert "env_file" not in local and "env_file" not in database
    assert database["networks"] == ["hindsight-storage"]
    assert compose["networks"]["hindsight-storage"]["internal"] is True
    assert database["volumes"] == ["hindsight_postgres_data:/var/lib/postgresql"]
    assert local["environment"]["AGENTBARN_MEMORY_SETTINGS_URL"] == "http://api:8004/memory/runtime/v1/model"
    assert any("memory_model.py" in mount for mount in local["volumes"])
    assert local["environment"]["HINDSIGHT_API_LLM_MODEL"] == services["api"]["environment"]["MEMORY_DEFAULT_MODEL"]
    assert local["environment"]["HINDSIGHT_ENABLE_CP"] == "false"
    assert local["environment"]["HINDSIGHT_API_TENANT_EXTENSION"].endswith(":ApiKeyTenantExtension")
    assert "env_file" not in services["memory"]
    assert "AGENT_TOKEN_ENCRYPTION_KEY" not in services["memory"]["environment"]
    for name in ("api", "worker", "communications"):
        assert services[name]["environment"]["HINDSIGHT_LITELLM_API_KEY"] == ""
        assert services[name]["environment"]["HINDSIGHT_DB_PASSWORD"] == ""
        assert services[name]["environment"]["HINDSIGHT_API_KEY"] == ""
    for name in ("worker", "cost-sync", "budget-snapshots", "communications"):
        assert services[name]["environment"]["MEMORY_RUNTIME_SERVICE_KEY"] == ""
    assert services["api"]["environment"]["MEMORY_RUNTIME_SERVICE_KEY"] == "${MEMORY_RUNTIME_SERVICE_KEY:-}"
    assert "8004:8004" not in services["api"]["ports"]
    values = {
        "dbConnectionUrl": "postgresql://test:test@postgres-app/test",
        "secretSigningKey": "test",
        "platformAdminCredentials": "admin@example.com:Test1234",
        "agentTokenEncryptionKey": "test",
        "environment": "test",
        "organizationLlmBudgets": {"defaultOrganizationUsd": 1000, "defaultAgentUsd": 100},
        "webAppUrl": "http://localhost",
        "kubeconfigB64": "dGVzdA==",
        "registry": {"server": "test.invalid", "username": "test", "password": "test"},
    }
    disabled = render("agentbarn-api", values)
    assert not any(document["metadata"]["name"] == "agentbarn-api-memory" for document in disabled)
    memory_values = {
        **values,
        "memory": {
            "enabled": True,
            "litellmKeyHashes": "f" * 64,
            "litellmActiveKeyHash": "f" * 64,
            "defaultModel": "openrouter/custom/default",
            "settingsKeyChecksum": "test-settings-key-checksum",
        },
    }
    try:
        render("agentbarn-api", {**values, "memory": {"enabled": True}})
    except subprocess.CalledProcessError as error:
        assert "memory.litellmKeyHashes is required" in error.stderr
    else:
        raise AssertionError("Memory deployment must require the cost attribution key hashes")
    enabled = render("agentbarn-api", memory_values)
    job = next(document for document in enabled if document["metadata"]["name"] == "agentbarn-api-memory-purge")
    assert job["spec"]["concurrencyPolicy"] == "Forbid"
    job_pod = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    assert job_pod["automountServiceAccountToken"] is False
    assert "volumes" not in job_pod
    job_container = job_pod["containers"][0]
    assert "envFrom" not in job_container
    assert {item["name"] for item in job_container["env"]} == {
        "DB_CONNECTION_URL",
        "HINDSIGHT_BASE_URL",
        "HINDSIGHT_API_KEY",
    }
    assert not any(document["metadata"]["name"] == "agentbarn-api-memory-purge" for document in disabled)
    shared_secret = next(
        document for document in enabled if "MEMORY_LITELLM_KEY_HASHES" in document.get("stringData", {})
    )
    assert shared_secret["stringData"]["MEMORY_LITELLM_KEY_HASHES"] == "f" * 64
    assert shared_secret["stringData"]["MEMORY_DEFAULT_MODEL"] == "openrouter/custom/default"
    assert shared_secret["stringData"]["MEMORY_LITELLM_ACTIVE_KEY_HASH"] == "f" * 64
    assert "HINDSIGHT_LITELLM_API_KEY" not in shared_secret["stringData"]
    for document in enabled:
        if document["kind"] == "Deployment":
            pod = document["spec"]["template"]["spec"]
            key_env = [
                entry
                for container in pod["containers"]
                for entry in container.get("env", [])
                if entry["name"] == "HINDSIGHT_API_KEY"
            ]
            if document["metadata"]["name"] == "agentbarn-api-memory":
                assert "envFrom" not in pod["containers"][0]
                assert {entry["name"] for entry in pod["containers"][0]["env"]} == {
                    "DB_CONNECTION_URL",
                    "SECRET_SIGNING_KEY",
                    "ENVIRONMENT",
                    "MEMORY_DEFAULT_MODEL",
                    "MEMORY_LITELLM_KEY_HASHES",
                    "ORGANIZATION_DEFAULT_LLM_BUDGET_USD",
                    "AGENT_DEFAULT_LLM_BUDGET_USD",
                    "PLATFORM_ADMIN_CREDENTIALS",
                    "HINDSIGHT_BASE_URL",
                    "HINDSIGHT_API_KEY",
                }
                assert pod["automountServiceAccountToken"] is False
                assert len(key_env) == 1
                assert key_env[0]["valueFrom"]["secretKeyRef"] == {
                    "name": "hindsight",
                    "key": "HINDSIGHT_API_TENANT_API_KEY",
                }
                assert "--no-access-log" in pod["containers"][0]["command"]
            else:
                assert not key_env
    api_deployment = next(
        document
        for document in enabled
        if document["kind"] == "Deployment" and document["metadata"]["name"] == "agentbarn-api"
    )
    assert api_deployment["spec"]["template"]["metadata"]["annotations"]["checksum/memory-settings-key"] == (
        "test-settings-key-checksum"
    )
    assert {"name": "memory-settings", "containerPort": 8004} in (
        api_deployment["spec"]["template"]["spec"]["containers"][0]["ports"]
    )
    api_settings_key = next(
        entry
        for entry in api_deployment["spec"]["template"]["spec"]["containers"][0]["env"]
        if entry["name"] == "MEMORY_RUNTIME_SERVICE_KEY"
    )
    assert api_settings_key["valueFrom"]["secretKeyRef"]["key"] == "AGENTBARN_MEMORY_SETTINGS_KEY"
    api_service = next(
        document
        for document in enabled
        if document["kind"] == "Service" and document["metadata"]["name"] == "agentbarn-api"
    )
    assert any(
        port["name"] == "memory-runtime" and port["port"] == port["targetPort"] == 8004
        for port in api_service["spec"]["ports"]
    )
    backend = render(
        "hindsight",
        {
            "databaseUrl": "postgresql://test:test@postgres-hindsight/test",
            "apiKey": "test-backend-key",
            "runtimeServiceKey": "test-memory-runtime-key",
            "llm": {"apiKey": "test-platform-key", "model": "openrouter/custom/default"},
        },
    )
    deployment = next(document for document in backend if document["kind"] == "Deployment")
    pod = deployment["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    container = pod["containers"][0]
    assert container["image"] == "ghcr.io/vectorize-io/hindsight:0.10.2"
    assert container["command"] == [
        "/app/api/.venv/bin/python",
        "/opt/agentbarn/start_hindsight.py",
        "--workers",
        "1",
    ]
    assert "checksum/attribution" in deployment["spec"]["template"]["metadata"]["annotations"]
    bridge = next(document for document in backend if document["kind"] == "ConfigMap")
    assert "start_hindsight.py" in bridge["data"]
    assert "memory_model.py" in bridge["data"]
    environment = {entry["name"]: entry["value"] for entry in container["env"]}
    assert environment["AGENTBARN_MEMORY_SETTINGS_URL"] == "http://agentbarn-api:8004/memory/runtime/v1/model"
    assert environment["HINDSIGHT_API_LLM_MODEL"] == shared_secret["stringData"]["MEMORY_DEFAULT_MODEL"]
    assert environment["HINDSIGHT_ENABLE_CP"] == "false"
    assert environment["HINDSIGHT_API_TENANT_EXTENSION"].endswith(":ApiKeyTenantExtension")
    assert "HINDSIGHT_API_TENANT_MCP_AUTH_DISABLED" not in environment
    service = next(document for document in backend if document["kind"] == "Service")
    assert service["spec"]["type"] == "ClusterIP"
    assert [port["port"] for port in service["spec"]["ports"]] == [8888]
    print("Memory chart isolation and authentication checks passed.")


if __name__ == "__main__":
    main()
