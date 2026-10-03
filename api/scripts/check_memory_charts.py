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
    values = {
        "dbConnectionUrl": "postgresql://test:test@postgres-app/test",
        "secretSigningKey": "test",
        "platformAdminCredentials": "admin@example.com:Test1234",
        "agentTokenEncryptionKey": "test",
        "environment": "test",
        "webAppUrl": "http://localhost",
        "kubeconfigB64": "dGVzdA==",
        "registry": {"server": "test.invalid", "username": "test", "password": "test"},
    }
    disabled = render("agentbarn-api", values)
    assert not any(document["metadata"]["name"] == "agentbarn-api-memory" for document in disabled)
    memory_values = {**values, "memory": {"enabled": True, "litellmKeyHashes": "f" * 64}}
    try:
        render("agentbarn-api", {**values, "memory": {"enabled": True}})
    except subprocess.CalledProcessError as error:
        assert "memory.litellmKeyHashes is required" in error.stderr
    else:
        raise AssertionError("Memory deployment must require the cost attribution key hashes")
    enabled = render("agentbarn-api", memory_values)
    shared_secret = next(
        document for document in enabled if "MEMORY_LITELLM_KEY_HASHES" in document.get("stringData", {})
    )
    assert shared_secret["stringData"]["MEMORY_LITELLM_KEY_HASHES"] == "f" * 64
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
                assert pod["automountServiceAccountToken"] is False
                assert len(key_env) == 1
                assert key_env[0]["valueFrom"]["secretKeyRef"] == {
                    "name": "hindsight",
                    "key": "HINDSIGHT_API_TENANT_API_KEY",
                }
                assert "--no-access-log" in pod["containers"][0]["command"]
            else:
                assert not key_env
    backend = render(
        "hindsight",
        {
            "databaseUrl": "postgresql://test:test@postgres-hindsight/test",
            "apiKey": "test-backend-key",
            "llm": {"apiKey": "test-platform-key"},
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
    environment = {entry["name"]: entry["value"] for entry in container["env"]}
    assert environment["HINDSIGHT_ENABLE_CP"] == "false"
    assert environment["HINDSIGHT_API_TENANT_EXTENSION"].endswith(":ApiKeyTenantExtension")
    assert "HINDSIGHT_API_TENANT_MCP_AUTH_DISABLED" not in environment
    service = next(document for document in backend if document["kind"] == "Service")
    assert service["spec"]["type"] == "ClusterIP"
    assert [port["port"] for port in service["spec"]["ports"]] == [8888]
    print("Memory chart isolation and authentication checks passed.")


if __name__ == "__main__":
    main()
