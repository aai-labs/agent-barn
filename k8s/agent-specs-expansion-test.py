#!/usr/bin/env python3
"""Prove a StorageClass grows a mounted volume, on a disposable claim.

Agent specs grow an Agent's existing volume by raising its claim's storage request. This
does the same to a throwaway claim: it creates a 1Gi claim and a small pod that mounts it,
raises the request to 2Gi, and waits until Kubernetes reports the new capacity and the
pod's filesystem sees it. The claim and pod are always deleted afterwards (unless --keep).

    python3 k8s/agent-specs-expansion-test.py --kubeconfig ~/.kube/prod.yaml --namespace agent-farm

The StorageClass defaults to the one existing Agent volumes use. It needs permission to
create and delete claims and pods, and briefly uses 2Gi of the namespace's storage quota.
`--image` must be pullable in the cluster and have `sh`, `df` and `sleep`.
"""

import argparse
import json
import secrets
import subprocess
import sys
import time

GIB = 1024**3
_UNITS = {"Ki": 1024, "Mi": 1024**2, "Gi": GIB, "Ti": 1024**4, "k": 1000, "M": 1000**2, "G": 1000**3, "T": 1000**4}


def quantity(value: str | None) -> float:
    if not value:
        return 0
    for unit in sorted(_UNITS, key=len, reverse=True):
        if value.endswith(unit):
            return float(value[: -len(unit)]) * _UNITS[unit]
    return float(value)


class Cluster:
    def __init__(self, kubeconfig: str, namespace: str) -> None:
        self.kubeconfig = kubeconfig
        self.namespace = namespace

    def run(self, *args: str, stdin: str | None = None) -> tuple[bool, str]:
        result = subprocess.run(
            ["kubectl", "--kubeconfig", self.kubeconfig, "--namespace", self.namespace, *args],
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0, (result.stdout if result.returncode == 0 else result.stderr).strip()

    def get(self, kind: str, name: str) -> dict | None:
        ok, out = self.run("get", kind, name, "-o", "json")
        return json.loads(out) if ok else None


def agent_storage_class(cluster: Cluster) -> str | None:
    ok, out = cluster.run("get", "persistentvolumeclaims", "-o", "json")
    if not ok:
        return None
    for claim in json.loads(out)["items"]:
        name = claim["metadata"]["name"]
        if name.startswith("agent-") and not name.endswith("-addons") and claim["spec"].get("storageClassName"):
            return claim["spec"]["storageClassName"]
    return None


def manifests(name: str, storage_class: str | None, image: str) -> str:
    labels = {"app.kubernetes.io/name": "agent-specs-expansion-test"}
    claim = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {"name": name, "labels": labels},
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": "1Gi"}},
            **({"storageClassName": storage_class} if storage_class else {}),
        },
    }
    pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name, "labels": labels},
        "spec": {
            "restartPolicy": "Never",
            "terminationGracePeriodSeconds": 0,
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 65534,
                "fsGroup": 65534,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "containers": [
                {
                    "name": "probe",
                    "image": image,
                    "command": ["sh", "-c", "sleep 3600"],
                    "volumeMounts": [{"name": "data", "mountPath": "/data"}],
                    "resources": {
                        "requests": {"cpu": "50m", "memory": "64Mi"},
                        "limits": {"cpu": "100m", "memory": "64Mi"},
                    },
                    "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}},
                }
            ],
            "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": name}}],
        },
    }
    return json.dumps({"apiVersion": "v1", "kind": "List", "items": [claim, pod]})


def wait(what: str, check, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(3)
    print(f"FAIL    timed out after {timeout}s waiting for {what}")
    return False


def filesystem_bytes(cluster: Cluster, name: str) -> int | None:
    ok, out = cluster.run("exec", name, "--", "df", "-k", "/data")
    if not ok:
        return None
    lines = out.splitlines()
    fields = lines[-1].split() if lines else []
    return int(fields[1]) * 1024 if len(fields) > 1 and fields[1].isdigit() else None


def capacity(cluster: Cluster, name: str) -> tuple[str | None, list[str]]:
    claim = cluster.get("persistentvolumeclaim", name) or {}
    status = claim.get("status", {})
    conditions = [condition.get("type", "") for condition in status.get("conditions", [])]
    return status.get("capacity", {}).get("storage"), conditions


def explain(cluster: Cluster, name: str) -> None:
    ok, out = cluster.run(
        "get",
        "events",
        "--field-selector",
        f"involvedObject.name={name}",
        "-o",
        "custom-columns=TYPE:.type,REASON:.reason,MESSAGE:.message",
        "--no-headers",
    )
    if ok and out:
        print("        events:")
        for line in out.splitlines()[-8:]:
            print(f"          {line}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--namespace", default="agent-farm")
    parser.add_argument("--storage-class", help="defaults to the class existing Agent volumes use")
    parser.add_argument("--image", default="busybox:1.36")
    parser.add_argument("--timeout", type=int, default=300, help="seconds to wait for each step")
    parser.add_argument("--keep", action="store_true", help="leave the claim and pod for inspection")
    args = parser.parse_args()

    cluster = Cluster(args.kubeconfig, args.namespace)
    storage_class = args.storage_class or agent_storage_class(cluster)
    name = f"agent-specs-expansion-test-{secrets.token_hex(3)}"
    ok, context = cluster.run("config", "current-context")
    print(
        f"Context {context if ok else '?'}, namespace {args.namespace}, "
        f"StorageClass {storage_class or '(cluster default)'}, claim {name}"
    )

    # Cleanup covers a failed create too: the claim can be created when the pod is refused.
    try:
        ok, out = cluster.run("apply", "-f", "-", stdin=manifests(name, storage_class, args.image))
        if not ok:
            print(f"FAIL    could not create the test claim and pod: {out}")
            return 1
        return expand(cluster, name, args.timeout)
    finally:
        if args.keep:
            print(f"Kept claim and pod {name}; delete both when done.")
        else:
            cluster.run("delete", "pod", name, "--ignore-not-found", "--wait=true", "--timeout=120s")
            cluster.run("delete", "persistentvolumeclaim", name, "--ignore-not-found", "--wait=false")
            print(f"Deleted claim and pod {name}.")


def expand(cluster: Cluster, name: str, timeout: int) -> int:
    def running() -> bool:
        pod = cluster.get("pod", name) or {}
        return pod.get("status", {}).get("phase") == "Running"

    if not wait("the test pod to run with its claim bound", running, timeout):
        explain(cluster, name)
        return 1
    before, _ = capacity(cluster, name)
    fs_before = filesystem_bytes(cluster, name)
    if fs_before is None:
        print("FAIL    could not read the mounted filesystem's size with df")
        return 1
    print(f"OK      bound at {before}; the pod's filesystem has {fs_before / GIB:.2f}Gi")

    ok, out = cluster.run(
        "patch",
        "persistentvolumeclaim",
        name,
        "--type",
        "merge",
        "-p",
        json.dumps({"spec": {"resources": {"requests": {"storage": "2Gi"}}}}),
    )
    if not ok:
        print(f"FAIL    Kubernetes refused to grow the claim: {out}")
        return 1
    print("OK      the request to grow to 2Gi was accepted")

    def grown() -> bool:
        storage, _ = capacity(cluster, name)
        return quantity(storage) >= 2 * GIB

    if not wait("the claim's capacity to reach 2Gi", grown, timeout):
        _, conditions = capacity(cluster, name)
        print(f"        conditions: {', '.join(conditions) or 'none'}")
        explain(cluster, name)
        return 1
    after, _ = capacity(cluster, name)
    print(f"OK      capacity is now {after}")

    def filesystem_grew() -> bool:
        size = filesystem_bytes(cluster, name)
        return size is not None and size > fs_before

    if not wait("the mounted filesystem to grow", filesystem_grew, timeout):
        _, conditions = capacity(cluster, name)
        print(f"        conditions: {', '.join(conditions) or 'none'}")
        explain(cluster, name)
        return 1
    fs_after = filesystem_bytes(cluster, name) or 0
    print(f"OK      the pod's filesystem grew to {fs_after / GIB:.2f}Gi while mounted")
    print("PASS    this StorageClass grows a mounted volume; Agent specs can grow existing Agent volumes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
