"""Render the restore point CronJobs and check that a stuck run cannot stall the next ones."""

import importlib.util
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONSTANTS = ROOT / "api/domains/restore_points/constants.py"


def render() -> list[dict[str, Any]]:
    result = subprocess.run(
        [
            "helm",
            "template",
            "restore-points-test",
            str(ROOT / "helm/agentbarn-api"),
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


def interval_seconds(schedule: str) -> int:
    match = re.fullmatch(r"\*/(\d+) \* \* \* \*", schedule)
    assert match, f"expected an every-N-minutes schedule, got {schedule!r}"
    return int(match.group(1)) * 60


def reconciliation_max_runtime_seconds() -> int:
    spec = importlib.util.spec_from_file_location("restore_point_constants", CONSTANTS)
    assert spec and spec.loader
    constants = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(constants)
    return constants.RESTORE_POINT_RECONCILIATION_MAX_RUNTIME_SECONDS


def main() -> None:
    cronjobs = {document["metadata"]["name"]: document for document in render() if document["kind"] == "CronJob"}
    for name in ("restore-points-test-restore-point-schedule", "restore-points-test-restore-point-reconciliation"):
        spec = cronjobs[name]["spec"]
        # Forbid alone lets one run that never finishes (a Pending pod, a hung call) skip
        # every later one, so each run must also end inside its own window.
        assert spec["concurrencyPolicy"] == "Forbid", name
        deadline = spec["jobTemplate"]["spec"].get("activeDeadlineSeconds")
        assert isinstance(deadline, int) and deadline > 0, f"{name} has no activeDeadlineSeconds"
        assert deadline < interval_seconds(spec["schedule"]), f"{name} can outlive its schedule window"
    reconciliation = cronjobs["restore-points-test-restore-point-reconciliation"]["spec"]["jobTemplate"]["spec"]
    assert reconciliation["activeDeadlineSeconds"] > reconciliation_max_runtime_seconds(), (
        "the reconciliation deadline must leave room for the run's own time budget"
    )
    print("Restore point chart checks passed")


if __name__ == "__main__":
    main()
