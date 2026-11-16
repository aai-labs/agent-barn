"""Render SSH deployment with and without signing; creates no cluster resources."""

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def render(enabled: bool) -> list[dict]:
    values = {
        "dbConnectionUrl": "postgresql://test:test@postgres/test",
        "secretSigningKey": "fixture",
        "platformAdminCredentials": "test@example.com:Test1234",
        "agentTokenEncryptionKey": "fixture",
        "environment": "test",
        "webAppUrl": "https://ui.test",
        "ingestBaseUrl": "http://ingest.test",
        "organizationLlmBudgets.defaultOrganizationUsd": "100",
        "organizationLlmBudgets.defaultAgentUsd": "25",
        "registry.server": "registry.test",
        "registry.username": "test",
        "registry.password": "test",
        "kubeconfigB64": "Zml4dHVyZQ==",
        "ssh.enabled": str(enabled).lower(),
        "ssh.signerUrl": "wss://api.test/ssh/v1/agent",
    }
    args = ["helm", "template", "ssh-test", str(ROOT / "helm/agentbarn-api"), "--namespace", "ssh-test"]
    for key, value in values.items():
        args += ["--set", key + "=" + value]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return [document for document in yaml.safe_load_all(result.stdout) if document]


def main() -> None:
    sys.path.insert(0, str(ROOT))
    from api.core.config import Config

    for enabled in (False, True):
        docs = render(enabled)
        workloads = [doc for doc in docs if doc["kind"] == "Deployment" and doc["metadata"]["name"] == "ssh-test-ssh"]
        assert len(workloads) == int(enabled)
        if not enabled:
            continue
        pod = workloads[0]["spec"]["template"]["spec"]
        assert pod["automountServiceAccountToken"] is False
        assert pod["securityContext"]["runAsNonRoot"] is True
        container = pod["containers"][0]
        assert "envFrom" not in container
        assert container["securityContext"]["readOnlyRootFilesystem"] is True
        assert container["securityContext"]["allowPrivilegeEscalation"] is False
        references = {env["valueFrom"]["secretKeyRef"]["key"] for env in container["env"] if "valueFrom" in env}
        assert references == {"DB_CONNECTION_URL", "AGENT_TOKEN_ENCRYPTION_KEY"}
        required = {name for name, field in Config.model_fields.items() if field.is_required()}
        assert required <= {env["name"].lower() for env in container["env"]}, "Missing required signer configuration"
        assert pod["volumes"] == [{"name": "sockets", "emptyDir": {"medium": "Memory", "sizeLimit": "32Mi"}}]
        policies = [doc for doc in docs if doc["kind"] == "NetworkPolicy" and doc["metadata"]["name"] == "ssh-test-ssh"]
        assert len(policies) == 1
        assert policies[0]["spec"]["policyTypes"] == ["Ingress", "Egress"]
        ports = {port["port"] for rule in policies[0]["spec"]["egress"] for port in rule["ports"]}
        assert ports == {53, 5432}
        ingresses = [doc for doc in docs if doc["kind"] == "Ingress"]
        for ingress in ingresses:
            for rule in ingress["spec"]["rules"]:
                route = next(route for route in rule["http"]["paths"] if route["path"] == "/ssh/v1/agent")
                assert route["pathType"] == "Exact"
                assert route["backend"]["service"]["name"] == "ssh-test-ssh"
    print("SSH chart isolation and routing checks passed")


if __name__ == "__main__":
    main()
