"""Render workflow dispatch workloads and verify their cluster access contract."""

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    for secret in ("", "custom-workflow-kubeconfig"):
        result = subprocess.run(
            [
                "helm",
                "template",
                "workflow-test",
                str(ROOT / "helm/agentbarn-api"),
                "--namespace",
                "workflow-staging",
                "--set",
                "dbConnectionUrl=postgresql://test:test@postgres/test",
                "--set",
                "secretSigningKey=test",
                "--set",
                "platformAdminCredentials=test@example.com:Test1234",
                "--set",
                "agentTokenEncryptionKey=test",
                "--set",
                "environment=test",
                "--set",
                "webAppUrl=http://ui.test",
                "--set",
                "ingestBaseUrl=http://ingest.test",
                "--set",
                "organizationLlmBudgets.defaultOrganizationUsd=100",
                "--set",
                "organizationLlmBudgets.defaultAgentUsd=25",
                "--set",
                "registry.server=registry.test",
                "--set",
                "registry.username=test",
                "--set",
                "registry.password=test",
                "--set",
                "kubeconfigB64=Zml4dHVyZQ==",
                "--set",
                "worker.enabled=true",
                "--set",
                f"kubeconfigSecretName={secret}",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise RuntimeError(result.stderr)
        documents = [document for document in yaml.safe_load_all(result.stdout) if document]
        workloads = {
            document["metadata"]["name"]: document
            for document in documents
            if document["kind"] in {"Deployment", "CronJob"}
        }
        for name in ("workflow-test", "workflow-test-worker", "workflow-test-workflow-maintenance"):
            workload = workloads[name]
            spec = workload["spec"]
            if workload["kind"] == "CronJob":
                spec = spec["jobTemplate"]["spec"]
            pod = spec["template"]["spec"]
            container = pod["containers"][0]
            env = {entry["name"]: entry.get("value") for entry in container["env"]}
            assert env.get("K8S_NAMESPACE") == "workflow-staging", name
            assert env.get("K8S_KUBECONFIG_PATH") == "/etc/kubeconfig/kubeconfig", name
            mount = next(m for m in container["volumeMounts"] if m["name"] == "kubeconfig")
            assert mount["mountPath"] == "/etc/kubeconfig" and mount["readOnly"] is True, name
            volume = next(v for v in pod["volumes"] if v["name"] == "kubeconfig")
            assert volume["secret"]["secretName"] == (secret or "workflow-test-kubeconfig"), name
    print("Workflow chart cluster access checks passed")


if __name__ == "__main__":
    main()
