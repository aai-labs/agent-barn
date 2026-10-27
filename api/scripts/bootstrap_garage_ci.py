"""Initialize private Garage on an explicitly targeted cluster without logging credentials."""

import argparse
import base64
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

from api.scripts.provision_garage import cluster_init, private_file, secret_manifest


def command(args: list[str], *, data: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, input=data, capture_output=True, text=True, check=False, timeout=300)
    if check and result.returncode:
        raise RuntimeError(f"Garage bootstrap failed: {args[0]} exited {result.returncode}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--kubeconfig", required=True, type=Path)
    parser.add_argument("--storage-class", default="")
    args = parser.parse_args()
    rpc = os.environ.get("GARAGE_RPC_SECRET_INPUT", "")
    admin = os.environ.get("GARAGE_ADMIN_TOKEN_INPUT", "")
    if not re.fullmatch(r"[0-9a-f]{64}", rpc) or not re.fullmatch(r"[0-9a-f]{64}", admin) or rpc == admin:
        raise ValueError("Garage RPC and admin secrets must be distinct 64-character lowercase hexadecimal values")
    kube = ["kubectl", "--kubeconfig", str(args.kubeconfig), "--namespace", args.namespace]
    existing = command([*kube, "get", "secret", "garage-rpc", "--ignore-not-found", "-o", "json"]).stdout
    if existing.strip():
        data = json.loads(existing)["data"]
        if (
            base64.b64decode(data.get("rpc-secret", "")).decode() != rpc
            or base64.b64decode(data.get("admin-token", "")).decode() != admin
        ):
            raise ValueError("Existing Garage credentials differ; use a coordinated rotation procedure")
    else:
        pvcs = json.loads(command([*kube, "get", "pvc", "-o", "json"]).stdout)["items"]
        if any(item["metadata"]["name"] in {"data-garage-0", "metadata-garage-0"} for item in pvcs):
            raise ValueError("Garage PVCs exist without the RPC Secret; inspect retained data before bootstrap")
        command(
            [*kube, "apply", "-f", "-"],
            data=secret_manifest("garage-rpc", args.namespace, {"rpc-secret": rpc, "admin-token": admin}),
        )
    helm = [
        "helm",
        "upgrade",
        "--install",
        "garage",
        "helm/garage",
        "--namespace",
        args.namespace,
        "--kubeconfig",
        str(args.kubeconfig),
        "--wait=false",
        "--set",
        "ingress.enabled=false",
    ]
    if args.storage_class:
        helm.extend(["--set-string", "storageClass=" + args.storage_class])
    command(helm)
    with tempfile.TemporaryDirectory(prefix="garage-ci-") as temp:
        directory = Path(temp)
        private_file(
            directory / "cluster.json",
            json.dumps(
                {
                    "namespace": args.namespace,
                    "release": "garage",
                    "endpoint": "http://garage:3900",
                    "rpc_secret": rpc,
                    "admin_token": admin,
                }
            ),
        )
        cluster_init(SimpleNamespace(state_dir=directory, kubeconfig=args.kubeconfig, capacity="10GB"))
        for name in ("application-secret.json", "provisioner-secret.json"):
            command([*kube, "apply", "-f", "-"], data=(directory / name).read_text())
    print("Garage bootstrap complete")


if __name__ == "__main__":
    main()
