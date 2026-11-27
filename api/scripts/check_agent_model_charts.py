"""Render the API chart and check that every workload resolves the same default Agent model.

Starts, decisions, Playbook Extractions and the LLM budget reconciliation all set an
Agent key's model list from the default model, so each workload must read the value
the API Deployment reads.
"""

import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "helm/agentbarn-api"
RELEASE = "agent-model-test"
VARIABLE = "AGENT_DEFAULT_MODEL"
DEFAULT_MODEL = "litellm/openrouter/test/default-model"
KEY_SYNC_WORKLOADS = (RELEASE, f"{RELEASE}-worker", f"{RELEASE}-llm-budget-reconciler")
SECRET_NAME = yaml.safe_load((CHART / "values.yaml").read_text())["secretName"]


def render(*values: str) -> list[dict[str, Any]]:
    arguments = [
        "dbConnectionUrl=postgresql://test:test@postgres/test",
        "secretSigningKey=test",
        "platformAdminCredentials=test@example.com:Test1234",
        "agentTokenEncryptionKey=test",
        "environment=test",
        "webAppUrl=http://ui.test",
        "ingestBaseUrl=http://ingest.test",
        "organizationLlmBudgets.defaultOrganizationUsd=100",
        "organizationLlmBudgets.defaultAgentUsd=25",
        "registry.server=registry.test",
        "registry.username=test",
        "registry.password=test",
        "kubeconfigB64=Zml4dHVyZQ==",
        "worker.enabled=true",
        *values,
    ]
    result = subprocess.run(
        ["helm", "template", RELEASE, str(CHART), *(part for value in arguments for part in ("--set", value))],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise RuntimeError(result.stderr)
    return [document for document in yaml.safe_load_all(result.stdout) if document]


def containers(document: dict[str, Any]) -> list[dict[str, Any]]:
    spec = document["spec"]
    if document["kind"] == "CronJob":
        spec = spec["jobTemplate"]["spec"]
    return spec["template"]["spec"]["containers"]


def check(documents: list[dict[str, Any]], expected: str | None) -> None:
    secret = next(d for d in documents if d["kind"] == "Secret" and d["metadata"]["name"] == SECRET_NAME)
    assert secret["stringData"].get(VARIABLE) == expected, (
        f"the shared Secret has {VARIABLE}={secret['stringData'].get(VARIABLE)!r}"
    )
    workloads = {d["metadata"]["name"]: d for d in documents if d["kind"] in {"Deployment", "CronJob", "Job"}}
    for name, workload in workloads.items():
        for container in containers(workload):
            names = {entry["name"] for entry in container.get("env", [])}
            assert VARIABLE not in names, f"{name} sets its own {VARIABLE}"
    for name in KEY_SYNC_WORKLOADS:
        for container in containers(workloads[name]):
            sources = {source.get("secretRef", {}).get("name") for source in container.get("envFrom", [])}
            assert SECRET_NAME in sources, f"{name} does not load the shared Secret"


def main() -> None:
    check(render(f"agentDefaultModel={DEFAULT_MODEL}"), DEFAULT_MODEL)
    check(render(), None)
    print("Agent default model chart checks passed")


if __name__ == "__main__":
    main()
