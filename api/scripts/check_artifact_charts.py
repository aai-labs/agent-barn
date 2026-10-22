"""Render-only contract for private storage credentials and scheduled cleanup."""

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    for enabled in (False, True):
        result = subprocess.run(
            [
                "helm",
                "template",
                "artifact-test",
                str(ROOT / "helm/agentbarn-api"),
                "--namespace",
                "artifact-fixture",
                "-f",
                str(ROOT / "api/tests/fixtures/artifacts/chart-values.yaml"),
                "--set",
                "worker.enabled=true",
                "--set",
                f"artifacts.purgeEnabled={str(enabled).lower()}",
                "--set",
                "artifacts.existingSecret=private-artifact-storage",
                "--set",
                "artifacts.retentionDays=31",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise RuntimeError(result.stderr)
        items = [item for item in yaml.safe_load_all(result.stdout) if item]
        jobs = [item for item in items if item["metadata"]["name"] == "artifact-test-artifact-purge"]
        assert len(jobs) == int(enabled)
        for item in items:
            if item["kind"] not in {"Deployment", "CronJob"}:
                continue
            spec = item["spec"]
            if item["kind"] == "CronJob":
                spec = spec["jobTemplate"]["spec"]
            pod = spec["template"]["spec"]
            for container in pod["containers"]:
                names = [ref["secretRef"]["name"] for ref in container.get("envFrom", []) if "secretRef" in ref]
                expected = item["metadata"]["name"] in {"artifact-test", "artifact-test-artifact-purge"}
                assert ("private-artifact-storage" in names) == expected, item["metadata"]["name"]
            if item["metadata"]["name"] == "artifact-test-artifact-purge":
                assert pod["automountServiceAccountToken"] is False
                assert pod["containers"][0]["command"] == ["python", "-m", "api.domains.artifacts.maintenance"]
        config = next(
            item
            for item in items
            if item["kind"] == "Secret" and "ARTIFACT_RETENTION_DAYS" in item.get("stringData", {})
        )
        assert config["stringData"]["ARTIFACT_RETENTION_DAYS"] == "31"
        assert config["stringData"]["ARTIFACT_RUNTIME_BASE_URL"] == "http://artifact-test:8000/artifact-runtime/v1"
        assert not any(key.startswith("ARTIFACT_S3_") for key in config["stringData"])
    print("Artifact chart credentials and purge checks passed")


if __name__ == "__main__":
    main()
