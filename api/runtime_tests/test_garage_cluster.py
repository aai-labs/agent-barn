"""Disposable three-node chart, quorum outage and PVC recovery contract; never an existing cluster."""

import argparse
import hashlib
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import boto3
import httpx
from botocore.config import Config
from hamcrest import assert_that, equal_to, has_length, is_

from api.scripts.provision_garage import ROOT, cluster_init, run
from api.tests.helpers.garage_deployment import import_garage_test_images


def exercise(kubeconfig: Path, directory: Path) -> None:
    state = json.loads((directory / "cluster.json").read_text())
    kube = ["kubectl", "--kubeconfig", str(kubeconfig), "--namespace", state["namespace"]]
    pods = json.loads(run([*kube, "get", "pods", "-l", "app.kubernetes.io/name=garage", "-o", "json"]).stdout)["items"]
    assert_that(pods, has_length(3))
    assert_that(len({pod["spec"]["nodeName"] for pod in pods}), equal_to(3))
    # Safety fence for the cordon/delete probe: never run it against installation nodes.
    assert_that(all("k3d-af415-garage-" in pod["spec"]["nodeName"] for pod in pods), is_(True))
    victim = next(pod for pod in pods if pod["metadata"]["name"] == "garage-2")
    node = victim["spec"]["nodeName"]
    old_ip = victim["status"]["podIP"]
    old_id = run([*kube, "exec", "garage-2", "--", "/garage", "node", "id"]).stdout.strip()
    client = boto3.client(
        "s3",
        endpoint_url=state["endpoint"],
        region_name="garage",
        aws_access_key_id=state["access_key"],
        aws_secret_access_key=state["secret_key"],
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            connect_timeout=5,
            read_timeout=30,
            retries={"total_max_attempts": 3, "mode": "standard"},
        ),
    )
    content = b"persistent replicated Garage byte boundary\x00\xff"
    key = "deployment-probe/" + str(uuid4())
    second = key + "-during-outage"
    try:
        client.put_object(Bucket=state["bucket"], Key=key, Body=content)
        signed = client.generate_presigned_url(
            "get_object", Params={"Bucket": state["bucket"], "Key": key}, ExpiresIn=900
        )
        assert_that(httpx.get(signed).content, equal_to(content))
        # Hold the replacement Pending, so the read/write checks really run with one replica absent.
        run([*kube, "cordon", node])
        run([*kube, "delete", "pod", "garage-2", "--wait=true", "--timeout=60s"])
        for _ in range(30):
            endpoints = json.loads(run([*kube, "get", "endpoints", "garage", "-o", "json"]).stdout)
            ready = sum(len(part.get("addresses", [])) for part in endpoints.get("subsets", []))
            if ready == 2:
                break
            time.sleep(1)
        assert_that(ready, equal_to(2), "S3 Service must retain two ready endpoints during the outage")
        assert_that(client.get_object(Bucket=state["bucket"], Key=key)["Body"].read(), equal_to(content))
        client.put_object(Bucket=state["bucket"], Key=second, Body=content)
        assert_that(client.get_object(Bucket=state["bucket"], Key=second)["Body"].read(), equal_to(content))
    finally:
        run([*kube, "uncordon", node], check=False)
    try:
        recovered = run(
            [*kube, "wait", "--for=condition=Ready", "pod/garage-2", "--timeout=120s"], timeout=130, check=False
        )
        assert_that(
            recovered.returncode, equal_to(0), run([*kube, "logs", "garage-2", "--tail=25"], check=False).stdout
        )
        restored_id = run([*kube, "exec", "garage-2", "--", "/garage", "node", "id"]).stdout.strip()
        assert_that(restored_id, equal_to(old_id))
        replacement = json.loads(run([*kube, "get", "pod", "garage-2", "-o", "json"]).stdout)
        assert_that(replacement["status"]["podIP"] != old_ip, is_(True), "Recovery must exercise a changed pod IP")
        service = json.loads(run([*kube, "get", "service", "garage-2", "-o", "json"]).stdout)
        status = json.loads(
            run(
                [
                    *kube,
                    "exec",
                    "garage-2",
                    "--",
                    "/garage",
                    "--rpc-host",
                    restored_id.partition("@")[0] + "@127.0.0.1:3901",
                    "json-api",
                    "GetClusterStatus",
                ]
            ).stdout
        )
        own = next(entry for entry in status["nodes"] if entry["id"] == restored_id.partition("@")[0])
        assert_that(own["addr"], equal_to(service["spec"]["clusterIP"] + ":3901"))
        assert_that(hashlib.sha256(httpx.get(signed).content).digest(), equal_to(hashlib.sha256(content).digest()))
    finally:
        client.delete_object(Bucket=state["bucket"], Key=key)
        client.delete_object(Bucket=state["bucket"], Key=second)


def test_replicated_garage_chart_quorum_and_pvc_recovery(tmp_path):
    name = "af415-garage-" + uuid4().hex[:8]
    kubeconfig = tmp_path / "kubeconfig.yaml"
    directory = tmp_path / "state"
    script = ROOT / "api/scripts/provision_garage.py"
    forward = None
    try:
        run(
            [
                "k3d",
                "cluster",
                "create",
                name,
                "--agents",
                "2",
                "--no-lb",
                "--image",
                "rancher/k3s:v1.31.5-k3s1",
                "--kubeconfig-update-default=false",
                "--kubeconfig-switch-context=false",
                "--wait",
                "--timeout",
                "240s",
            ],
            timeout=300,
        )
        kubeconfig.write_text(run(["k3d", "kubeconfig", "get", name]).stdout)
        kubeconfig.chmod(0o600)
        import_garage_test_images(name, tmp_path)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        run(
            [
                sys.executable,
                str(script),
                "cluster-config",
                "--state-dir",
                str(directory),
                "--namespace",
                "artifacts",
                "--endpoint",
                f"http://127.0.0.1:{port}",
                "--allow-http-local",
            ]
        )
        run(
            [
                "kubectl",
                "--kubeconfig",
                str(kubeconfig),
                "--namespace",
                "kube-system",
                "wait",
                "--for=condition=Available",
                "deployment/coredns",
                "deployment/local-path-provisioner",
                "--timeout=120s",
            ],
            timeout=130,
        )
        kube = ["kubectl", "--kubeconfig", str(kubeconfig), "--namespace", "artifacts"]
        run([*kube, "create", "namespace", "artifacts"])
        run([*kube, "apply", "--server-side", "-f", str(directory / "rpc-secret.json")])
        chart = run(
            [
                "helm",
                "template",
                "garage",
                str(ROOT / "helm/garage"),
                "--namespace",
                "artifacts",
                "--set",
                "imagePullPolicy=Never",
            ]
        ).stdout
        run([*kube, "apply", "-f", "-"], data=chart)
        bootstrap = argparse.Namespace(state_dir=directory, kubeconfig=kubeconfig, capacity="10GB")
        try:
            cluster_init(bootstrap)
        except Exception:
            print(run([*kube, "get", "pods", "-o", "wide"], check=False).stdout)
            print(run([*kube, "get", "events", "--sort-by=.lastTimestamp"], check=False).stdout)
            raise
        cluster_init(bootstrap)  # Existing layouts and keys must remain unchanged.
        with open(tmp_path / "forward.log", "w") as log:
            forward = subprocess.Popen([*kube, "port-forward", "pod/garage-0", f"{port}:3900"], stdout=log, stderr=log)
        for _ in range(30):
            try:
                httpx.get(f"http://127.0.0.1:{port}", timeout=1)
                break
            except httpx.HTTPError:
                time.sleep(0.2)
        exercise(kubeconfig, directory)
    finally:
        if forward is not None:
            forward.terminate()
            forward.wait(timeout=10)
        run(["k3d", "cluster", "delete", name], check=False)
