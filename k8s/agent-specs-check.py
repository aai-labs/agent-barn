#!/usr/bin/env python3
"""Check, read-only, that a cluster can run an Agent spec and grow Agent volumes.

Run it once per environment (staging, production, the public cluster) with your own
kubeconfig, and once per spec you intend to offer:

    python3 k8s/agent-specs-check.py --kubeconfig ~/.kube/prod.yaml --namespace agent-farm \\
        --cpu-request 500m --cpu-limit 2 --memory-request 1Gi --memory-limit 4Gi --storage 10Gi

`--pod-kubeconfig` is the identity the API pod uses (`POD_KUBECONFIG_B64`); its permissions
are what matter for growing volumes. Without it, the permissions shown are your kubeconfig's.

It changes nothing. Each line is OK, WARN, FAIL or UNKNOWN (the kubeconfig may not read
it: StorageClasses and Nodes are cluster-scoped). It exits 1 when anything FAILs. To prove
a StorageClass really expands a volume, run `agent-specs-expansion-test.py` as well.
"""

import argparse
import json
import subprocess
import sys

_SUFFIXES = {
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": 1024**3,
    "Ti": 1024**4,
    "k": 1000,
    "M": 1000**2,
    "G": 1000**3,
    "T": 1000**4,
    "m": 0.001,
}
GIB = 1024**3
# What a restore point's archive volume adds to the Agent's volume (RESTORE_POINT_ARCHIVE_* in
# api/domains/restore_points/constants.py): a tenth more and 512MiB, rounded up to 256MiB.
ARCHIVE_ROUNDING = 256 * 1024**2


def archive_bytes(volume: float) -> float:
    wanted = volume + volume * 10 // 100 + 512 * 1024**2
    return -(-wanted // ARCHIVE_ROUNDING) * ARCHIVE_ROUNDING


def quantity(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    for suffix in sorted(_SUFFIXES, key=len, reverse=True):
        if value.endswith(suffix):
            return float(value[: -len(suffix)]) * _SUFFIXES[suffix]
    return float(value)


def show_bytes(value: float | None) -> str:
    return "?" if value is None else f"{value / GIB:.2f}Gi"


def show_cpu(value: float | None) -> str:
    return "?" if value is None else f"{value:g} vCPU"


class Cluster:
    def __init__(self, kubeconfig: str, namespace: str) -> None:
        self.kubeconfig = kubeconfig
        self.namespace = namespace

    def run(self, *args: str, namespaced: bool = True) -> tuple[bool, str]:
        command = ["kubectl", "--kubeconfig", self.kubeconfig, *args]
        if namespaced:
            command += ["--namespace", self.namespace]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        return result.returncode == 0, (result.stdout if result.returncode == 0 else result.stderr).strip()

    def get(self, kind: str, name: str = "", *, namespaced: bool = True) -> dict | None:
        ok, out = self.run("get", kind, *([name] if name else []), "-o", "json", namespaced=namespaced)
        return json.loads(out) if ok else None

    def can(self, verb: str, resource: str) -> str:
        ok, out = self.run("auth", "can-i", verb, resource)
        return "yes" if ok and out == "yes" else ("no" if out.startswith("no") else f"unknown ({out})")


class Report:
    def __init__(self) -> None:
        self.failed = False

    def line(self, status: str, message: str) -> None:
        self.failed |= status == "FAIL"
        print(f"{status:<8}{message}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--namespace", default="agent-farm")
    parser.add_argument("--pod-kubeconfig", help="the API pod's kubeconfig, to check its permissions")
    parser.add_argument("--cpu-request", default="50m")
    parser.add_argument("--cpu-limit", default="500m")
    parser.add_argument("--memory-request", default="320Mi")
    parser.add_argument("--memory-limit", default="1Gi")
    parser.add_argument("--storage", default="1Gi")
    parser.add_argument("--agents", type=int, default=1, help="how many Agents would run on the spec")
    args = parser.parse_args()

    cluster = Cluster(args.kubeconfig, args.namespace)
    report = Report()
    spec = {
        "cpu_request": quantity(args.cpu_request),
        "cpu_limit": quantity(args.cpu_limit),
        "memory_request": quantity(args.memory_request),
        "memory_limit": quantity(args.memory_limit),
        "storage": quantity(args.storage),
    }
    ok, context = cluster.run("config", "current-context", namespaced=False)
    print(f"Context {context if ok else '?'}, namespace {args.namespace}")
    print(
        f"Spec: CPU {args.cpu_request}/{args.cpu_limit}, memory {args.memory_request}/{args.memory_limit}, "
        f"storage {args.storage}, {args.agents} Agent(s)\n"
    )

    check_volumes(cluster, report)
    check_permissions(
        Cluster(args.pod_kubeconfig, args.namespace) if args.pod_kubeconfig else cluster,
        report,
        pod=bool(args.pod_kubeconfig),
    )
    check_quota(cluster, report, spec, args.agents)
    check_limit_ranges(cluster, report, spec)
    check_nodes(cluster, report, spec)
    check_storage_capacity(cluster, report)
    return 1 if report.failed else 0


def check_volumes(cluster: Cluster, report: Report) -> None:
    print("== Agent volumes and their StorageClasses")
    claims = cluster.get("persistentvolumeclaims")
    if claims is None:
        report.line("FAIL", "cannot list PersistentVolumeClaims in the namespace")
        return
    agents = [
        claim
        for claim in claims["items"]
        if claim["metadata"]["name"].startswith("agent-")
        and not claim["metadata"]["name"].endswith("-addons")
        and claim["metadata"].get("labels", {}).get("agentbarn.io/component") != "restore-point"
    ]
    by_class: dict[str, list[dict]] = {}
    for claim in agents:
        by_class.setdefault(claim["spec"].get("storageClassName") or "", []).append(claim)
    if not agents:
        report.line("WARN", "no Agent volumes in the namespace; checking the default StorageClass only")
        by_class[""] = []
    for name, members in sorted(by_class.items()):
        sizes = [quantity(claim["status"].get("capacity", {}).get("storage")) or 0 for claim in members]
        summary = f"{len(members)} Agent volume(s), {show_bytes(sum(sizes))} in all" if members else "no volumes"
        storage_class = cluster.get("storageclass", name, namespaced=False) if name else default_class(cluster)
        label = name or "(none set: the cluster default)"
        if storage_class is None:
            report.line("UNKNOWN", f"StorageClass {label}: {summary}; cannot read it (ask a cluster administrator)")
            continue
        expands = storage_class.get("allowVolumeExpansion") is True
        report.line(
            "OK" if expands else "FAIL",
            f"StorageClass {storage_class['metadata']['name']} ({storage_class.get('provisioner')}): {summary}; "
            f"allowVolumeExpansion={'true' if expands else 'false'}",
        )
    unbound = [claim["metadata"]["name"] for claim in agents if claim["status"].get("phase") != "Bound"]
    if unbound:
        report.line("WARN", f"{len(unbound)} Agent volume(s) not Bound: {', '.join(unbound[:5])}")
    resizing = [
        claim["metadata"]["name"]
        for claim in agents
        if any(
            condition.get("type") in {"Resizing", "FileSystemResizePending"}
            for condition in claim["status"].get("conditions", [])
        )
    ]
    if resizing:
        report.line("WARN", f"volume(s) mid-resize: {', '.join(resizing[:5])}")
    print()


def default_class(cluster: Cluster) -> dict | None:
    classes = cluster.get("storageclass", namespaced=False)
    if classes is None:
        return None
    for storage_class in classes["items"]:
        annotations = storage_class["metadata"].get("annotations", {})
        if annotations.get("storageclass.kubernetes.io/is-default-class") == "true":
            return storage_class
    return {"metadata": {"name": "(no default StorageClass)"}, "provisioner": "-"}


def check_permissions(cluster: Cluster, report: Report, *, pod: bool) -> None:
    print(f"== Permissions of {'the API pod' if pod else 'your kubeconfig (pass --pod-kubeconfig for the API pod)'}")
    for verb, resource, why in (
        ("create", "persistentvolumeclaims", "create a new Agent's volume"),
        ("get", "persistentvolumeclaims", "read a volume's size and capacity"),
        ("patch", "persistentvolumeclaims", "grow an existing volume"),
        ("create", "deployments.apps", "start an Agent"),
        ("patch", "deployments.apps", "restart an Agent on a new spec"),
        ("create", "jobs.batch", "capture a restore point"),
    ):
        answer = cluster.can(verb, resource)
        status = {"yes": "OK", "no": "FAIL"}.get(answer, "UNKNOWN")
        report.line(status, f"{verb} {resource}: {answer} ({why})")
    print()


def check_quota(cluster: Cluster, report: Report, spec: dict, agents: int) -> None:
    print("== ResourceQuota headroom")
    quotas = cluster.get("resourcequota")
    if quotas is None:
        report.line("UNKNOWN", "cannot read ResourceQuotas")
        print()
        return
    if not quotas["items"]:
        report.line("OK", "no ResourceQuota in the namespace")
        print()
        return
    needed = {
        "requests.cpu": spec["cpu_request"] * agents,
        "limits.cpu": spec["cpu_limit"] * agents,
        "requests.memory": spec["memory_request"] * agents,
        "limits.memory": spec["memory_limit"] * agents,
        # The volume, and one restore point's archive volume, per Agent.
        "requests.storage": (spec["storage"] + archive_bytes(spec["storage"])) * agents,
    }
    for quota in quotas["items"]:
        hard, used = quota["status"].get("hard", {}), quota["status"].get("used", {})
        for key, want in needed.items():
            if key not in hard:
                continue
            free = (quantity(hard[key]) or 0) - (quantity(used.get(key)) or 0)
            shown = show_cpu if "cpu" in key else show_bytes
            report.line(
                "OK" if free >= want else "FAIL",
                f"{quota['metadata']['name']} {key}: {shown(free)} free of {shown(quantity(hard[key]))}, "
                f"{shown(want)} needed",
            )
    print()


def check_limit_ranges(cluster: Cluster, report: Report, spec: dict) -> None:
    print("== LimitRanges")
    ranges = cluster.get("limitrange")
    if ranges is None:
        report.line("UNKNOWN", "cannot read LimitRanges")
    elif not ranges["items"]:
        report.line("OK", "no LimitRange in the namespace")
    for limit_range in (ranges or {}).get("items", []):
        for limit in limit_range["spec"].get("limits", []):
            maximum = limit.get("max", {})
            for key, want in (
                ("cpu", spec["cpu_limit"]),
                ("memory", spec["memory_limit"]),
                ("storage", spec["storage"]),
            ):
                if key in maximum:
                    allowed = quantity(maximum[key])
                    report.line(
                        "OK" if want <= allowed else "FAIL",
                        f"{limit_range['metadata']['name']} {limit.get('type')} max {key} {maximum[key]}",
                    )
    print()


def check_nodes(cluster: Cluster, report: Report, spec: dict) -> None:
    print("== Nodes")
    nodes = cluster.get("nodes", namespaced=False)
    if nodes is None:
        report.line("UNKNOWN", "cannot read Nodes (ask a cluster administrator for allocatable CPU and memory)")
        print()
        return
    schedulable = [node for node in nodes["items"] if not node["spec"].get("unschedulable")]
    best_cpu = max((quantity(node["status"]["allocatable"]["cpu"]) or 0 for node in schedulable), default=0)
    best_memory = max((quantity(node["status"]["allocatable"]["memory"]) or 0 for node in schedulable), default=0)
    report.line(
        "OK" if spec["cpu_request"] <= best_cpu and spec["memory_request"] <= best_memory else "FAIL",
        f"{len(schedulable)} schedulable node(s); the largest allocates {show_cpu(best_cpu)} and "
        f"{show_bytes(best_memory)} (the spec requests {show_cpu(spec['cpu_request'])} and "
        f"{show_bytes(spec['memory_request'])})",
    )
    if spec["cpu_limit"] > best_cpu or spec["memory_limit"] > best_memory:
        report.line("WARN", "the spec's limit is above every node's allocatable; an Agent can never use all of it")
    print()


def check_storage_capacity(cluster: Cluster, report: Report) -> None:
    print("== Free storage")
    capacities = cluster.get("csistoragecapacities")
    items = (capacities or {}).get("items", [])
    if not items:
        report.line(
            "UNKNOWN",
            "the storage driver publishes no CSIStorageCapacity; check free space in the backend (for Ceph, `ceph df`)",
        )
    for capacity in items:
        report.line(
            "OK",
            f"{capacity.get('storageClassName')}: {show_bytes(quantity(capacity.get('capacity')))} available "
            f"({capacity['metadata']['name']})",
        )
    print()


if __name__ == "__main__":
    sys.exit(main())
