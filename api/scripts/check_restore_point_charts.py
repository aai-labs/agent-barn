"""Render the restore point CronJobs and check that a stuck run cannot stall the next ones."""

import importlib.util
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONSTANTS = ROOT / "api/domains/restore_points/constants.py"
RESTORE_POINT_VARIABLES = (
    "RESTORE_POINT_SIZE",
    "RESTORE_POINT_MAX_PER_AGENT",
    "RESTORE_POINT_SCHEDULE_INTERVAL_MINUTES",
    "RESTORE_POINT_SCHEDULED_MAX_PER_AGENT",
    "RESTORE_POINT_SCHEDULE_MAX_CONCURRENT",
)
# Each deploy reads its own environment's GitHub Variables. An unset variable
# arrives empty and Helmfile's default applies, so none of them is required.
DEPLOY_WORKFLOWS = {
    ".github/workflows/deploy.yml": "${{{{ vars[format('{{0}}{name}', github.ref_name == 'staging' && 'STAGING_' || '')] }}}}",
    ".github/workflows/deploy-public.yml": "${{{{ vars.PUBLIC_{name} }}}}",
}


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


def helmfile_sync_env(workflow: str) -> dict[str, str]:
    document = yaml.safe_load((ROOT / workflow).read_text())
    for job in document["jobs"].values():
        for step in job.get("steps", []):
            if step.get("name") == "Helmfile sync":
                return step.get("env", {})
    raise AssertionError(f"{workflow} has no Helmfile sync step")


def check_deploy_passthrough() -> None:
    for workflow, expected in DEPLOY_WORKFLOWS.items():
        env = helmfile_sync_env(workflow)
        for name in RESTORE_POINT_VARIABLES:
            assert env.get(name) == expected.format(name=name), f"{workflow} does not pass {name} through"


def main() -> None:
    check_deploy_passthrough()
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
