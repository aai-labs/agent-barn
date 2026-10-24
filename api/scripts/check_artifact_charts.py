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
    rendered = subprocess.run(
        [
            "helm",
            "template",
            "garage",
            str(ROOT / "helm/garage"),
            "--namespace",
            "artifact-fixture",
            "--set",
            "ingress.enabled=true",
            "--set",
            "ingress.host=files.example.invalid",
            "--set",
            "ingress.clusterIssuer=fixture-issuer",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    garage = [item for item in yaml.safe_load_all(rendered.stdout) if item]
    stateful = next(item for item in garage if item["kind"] == "StatefulSet")
    assert stateful["spec"]["replicas"] == 3
    pod = stateful["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsNonRoot"] is True
    dns_wait = pod["initContainers"][0]
    assert dns_wait["name"] == "wait-for-rpc-dns"
    assert "nslookup" in dns_wait["args"][0] and "svc.cluster.local" in dns_wait["args"][0]
    assert dns_wait["securityContext"]["readOnlyRootFilesystem"] is True
    assert all("secretKeyRef" not in entry.get("valueFrom", {}) for entry in dns_wait["env"])
    assert pod["affinity"]["podAntiAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]
    assert len(stateful["spec"]["volumeClaimTemplates"]) == 2
    assert pod["containers"][0]["env"][0]["valueFrom"]["secretKeyRef"]["name"] == "garage-rpc"
    assert not any(item["kind"] in {"Secret", "ClusterRole", "CustomResourceDefinition"} for item in garage)
    config = next(item for item in garage if item["kind"] == "ConfigMap")
    assert len(config["data"]) == 3
    assert all(
        "replication_factor = 3" in value
        and "rpc_timeout_msec = 20000" in value
        and "rpc_ping_timeout_msec = 3000" in value
        and "s3_web" not in value
        and "[admin]" not in value
        for value in config["data"].values()
    )
    for index in range(3):
        rpc = next(
            item for item in garage if item["kind"] == "Service" and item["metadata"]["name"] == f"garage-{index}"
        )
        assert rpc["spec"]["selector"]["statefulset.kubernetes.io/pod-name"] == f"garage-{index}"
        assert rpc["spec"]["publishNotReadyAddresses"] is True
        assert f"garage-{index}.artifact-fixture.svc.cluster.local:3901" in config["data"][f"garage-{index}.toml"]
    ingress = next(item for item in garage if item["kind"] == "Ingress")
    assert ingress["spec"]["tls"][0]["hosts"] == ["files.example.invalid"]
    assert ingress["spec"]["ingressClassName"] == "traefik"
    assert ingress["metadata"]["annotations"]["traefik.ingress.kubernetes.io/router.entrypoints"] == "websecure"
    assert ingress["metadata"]["annotations"]["cert-manager.io/cluster-issuer"] == "fixture-issuer"
    policy = next(item for item in garage if item["kind"] == "NetworkPolicy")
    sources = policy["spec"]["ingress"][1]["from"]
    assert sources[1]["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"] == "kube-system"
    assert sources[1]["podSelector"]["matchLabels"]["app.kubernetes.io/name"] == "traefik"
    assert sources[0]["podSelector"]["matchExpressions"][0]["values"] == ["api", "artifact-purge"]
    single = subprocess.run(
        [
            "helm",
            "template",
            "garage",
            str(ROOT / "helm/garage"),
            "--set",
            "replicas=1",
            "--set",
            "replicationFactor=1",
            "--set",
            "clusterDomain=fixture.local",
            "--set",
            "ingress.enabled=true",
            "--set",
            "ingress.host=files.example.invalid",
            "--set",
            "ingress.clusterIssuer=fixture-issuer",
            "--set-json",
            "ingress.annotations=null",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    single_items = [item for item in yaml.safe_load_all(single.stdout) if item]
    assert not any(item["kind"] == "PodDisruptionBudget" for item in single_items)
    single_config = next(item for item in single_items if item["kind"] == "ConfigMap")
    assert all(".svc.fixture.local:3901" in value for value in single_config["data"].values())
    single_ingress = next(item for item in single_items if item["kind"] == "Ingress")
    assert single_ingress["metadata"]["annotations"]["cert-manager.io/cluster-issuer"] == "fixture-issuer"
    for invalid in ("rpcTimeoutMilliseconds=20s", "rpcPingTimeoutMilliseconds=0"):
        rejected = subprocess.run(
            ["helm", "template", "garage", str(ROOT / "helm/garage"), "--set", invalid],
            capture_output=True,
            text=True,
            check=False,
        )
        assert rejected.returncode != 0 and invalid.split("=", 1)[0] in rejected.stderr
    print("Artifact chart credentials and purge checks passed")


if __name__ == "__main__":
    main()
