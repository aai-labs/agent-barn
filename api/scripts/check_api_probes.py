"""Render the API Deployment and check its health probes.

The API container starts three servers that each load the app, under a half-CPU
limit, so startup can take a minute or more on a busy node. A startup probe gives
it that time; liveness then takes over and still restarts a hung API quickly.
"""

import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "helm/agentbarn-api"
HEALTH = {"path": "/api/v1/health", "port": 8000}
# Kubernetes' default failureThreshold for every probe.
DEFAULT_FAILURES = 3
MIN_STARTUP_SECONDS = 120
MAX_LIVENESS_SECONDS = 60


def render() -> list[dict[str, Any]]:
    result = subprocess.run(
        [
            "helm",
            "template",
            "agentbarn-api",
            str(CHART),
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
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr)
    return [document for document in yaml.safe_load_all(result.stdout) if document]


def failure_window(probe: dict[str, Any]) -> int:
    return probe["periodSeconds"] * probe.get("failureThreshold", DEFAULT_FAILURES)


def main() -> None:
    deployment = next(
        document
        for document in render()
        if document["kind"] == "Deployment" and document["metadata"]["name"] == "agentbarn-api"
    )
    container = next(c for c in deployment["spec"]["template"]["spec"]["containers"] if c["name"] == "api")

    for name in ("startupProbe", "livenessProbe", "readinessProbe"):
        assert name in container, f"api container has no {name}"
        assert container[name]["httpGet"] == HEALTH, f"{name} does not check {HEALTH}"

    startup = container["startupProbe"]
    assert failure_window(startup) >= MIN_STARTUP_SECONDS, (
        f"startupProbe allows {failure_window(startup)}s to start, need at least {MIN_STARTUP_SECONDS}s"
    )
    liveness = container["livenessProbe"]
    assert failure_window(liveness) <= MAX_LIVENESS_SECONDS, (
        f"livenessProbe takes {failure_window(liveness)}s to restart a hung API, at most {MAX_LIVENESS_SECONDS}s"
    )
    print("API probes checked")


if __name__ == "__main__":
    main()
