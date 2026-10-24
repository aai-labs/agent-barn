"""Operator-owned persistent Garage bootstrap. Secrets are written privately, never logged."""

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[2]


def run(
    command: list[str], *, check: bool = True, data: str | None = None, timeout: int | None = 120
) -> subprocess.CompletedProcess:
    result = subprocess.run(command, input=data, capture_output=True, text=True, check=False, timeout=timeout)
    if check and result.returncode:
        # CLI errors may repeat secret arguments. Never print command, stdout or stderr.
        raise RuntimeError(f"Garage operation failed ({Path(command[0]).name}, exit {result.returncode})")
    return result


def private_file(path: Path, text: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as target:
        os.fchmod(target.fileno(), 0o600)
        target.write(text)


def read_env(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if line and not line.startswith("#"))


def endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Supply an HTTP(S) S3 origin without credentials, query or path")
    return value.rstrip("/")


def default_endpoint(port: int) -> str:
    # Linux host address reachable by browsers, Compose and k3d Agent pods.
    network = json.loads(run(["docker", "network", "inspect", "bridge"]).stdout)[0]
    return "http://" + network["IPAM"]["Config"][0]["Gateway"] + f":{port}"


def main_project() -> str:
    configured = os.environ.get("COMPOSE_PROJECT_NAME") or dotenv_values(ROOT / ".env").get("COMPOSE_PROJECT_NAME")
    return str(configured or re.sub(r"[^a-z0-9_-]", "", ROOT.name.lower()).lstrip("_-"))


def local_setup(directory: Path, port: int | None, public_endpoint: str | None) -> dict:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    state_file = directory / "state.json"
    if state_file.exists():
        state = json.loads(state_file.read_text())
        # Adopt stores created before the initialized marker was introduced conservatively.
        state.setdefault("initialized", True)
        if state["initialized"]:
            if (port is not None and port != state["port"]) or (
                public_endpoint and endpoint(public_endpoint) != state["endpoint"]
            ):
                raise ValueError("Existing Garage endpoint/port is immutable; restore or migrate it explicitly")
            require_volumes(state)
        else:
            if port is not None:
                state["port"] = port
            if public_endpoint:
                state["endpoint"] = endpoint(public_endpoint)
                state["endpoint_derived"] = False
            elif state.get("endpoint_derived", False):
                state["endpoint"] = default_endpoint(state["port"])
            write_local_state(directory, state)
        if directory == ROOT / ".garage" and state["project"] != main_project():
            # Adopt the former standalone container into the main Compose project.
            # Keep the exact named volumes, keys, node identity and published origin.
            write_local_state(directory, state)
            old_compose = local_compose(directory, state)
            run([*old_compose, "stop", "garage"])
            run([*old_compose, "rm", "-f", "garage"])
            state.setdefault("volume_project", state["project"])
            state["project"] = main_project()
        write_local_state(directory, state)
        return state
    port = port or 3900
    project = (
        main_project()
        if directory == ROOT / ".garage"
        else "agentbarn-garage-" + hashlib.sha256(str(directory).encode()).hexdigest()[:12]
    )
    existing = any(
        run(["docker", "volume", "inspect", project + "_" + suffix], check=False).returncode == 0
        for suffix in ("metadata", "data")
    )
    if existing or any(directory.iterdir()):
        raise ValueError("Restore the existing private Garage configuration before reinitializing retained storage")
    state = {
        "project": project,
        "initialized": False,
        "port": port,
        "endpoint": endpoint(public_endpoint) if public_endpoint else default_endpoint(port),
        "endpoint_derived": public_endpoint is None,
        "bucket": "agent-artifacts",
        "access_key": "GK" + secrets.token_hex(16),
        "secret_key": secrets.token_hex(32),
    }
    private_file(directory / "rpc-secret", secrets.token_hex(32))
    private_file(
        directory / "server.env",
        f"GARAGE_DEFAULT_ACCESS_KEY=GK{secrets.token_hex(16)}\nGARAGE_DEFAULT_SECRET_KEY={secrets.token_hex(32)}\nGARAGE_DEFAULT_BUCKET={state['bucket']}\n",
    )
    private_file(directory / "garage.toml", (ROOT / "docker/garage/garage.toml").read_text())
    write_local_state(directory, state)
    return state


def write_local_state(directory: Path, state: dict) -> None:
    private_file(
        directory / "compose.env",
        f"GARAGE_SAVED_STATE_DIR={directory}\nGARAGE_SAVED_S3_PORT={state['port']}\n"
        f"GARAGE_SAVED_VOLUME_PREFIX={state.get('volume_project', state['project'])}\n",
    )
    private_file(directory / "state.json", json.dumps(state))
    if directory == ROOT / ".garage" and (ROOT / ".env").is_file():
        # Only public Compose settings go in .env. Keys remain in private files.
        for name, value in read_env(directory / "compose.env").items():
            set_key((ROOT / ".env").resolve(), name, value, quote_mode="always")


def require_volumes(state: dict) -> None:
    for suffix in ("metadata", "data"):
        if run(
            ["docker", "volume", "inspect", state.get("volume_project", state["project"]) + "_" + suffix], check=False
        ).returncode:
            raise ValueError(
                "Initialized Garage volumes are missing; restore a consistent backup into a fresh directory"
            )


def local_compose(directory: Path, state: dict) -> list[str]:
    # Compose otherwise lets inherited shell values override its saved --env-file.
    return [
        "env",
        "-u",
        "GARAGE_SAVED_S3_PORT",
        "-u",
        "GARAGE_SAVED_STATE_DIR",
        "-u",
        "GARAGE_SAVED_VOLUME_PREFIX",
        "docker",
        "compose",
        "--project-name",
        state["project"],
        "--env-file",
        str(directory / "compose.env"),
        "-f",
        str(ROOT / "docker/garage/compose.yml"),
    ]


def provision_bucket(cli, bucket: str, access_key: str, secret_key: str) -> None:
    if cli(["bucket", "info", bucket], check=False).returncode:
        cli(["bucket", "create", bucket])
    if cli(["key", "info", access_key], check=False).returncode:
        cli(
            ["json-api", "ImportKey", "-"],
            data=json.dumps({"accessKeyId": access_key, "secretAccessKey": secret_key, "name": "agentbarn-artifacts"}),
        )
    # No owner or global bucket-creation grant reaches the application.
    cli(["bucket", "allow", bucket, "--key", access_key, "--read", "--write"])


def application_env(state: dict) -> str:
    return "".join(
        f"{key}={value}\n"
        for key, value in {
            "ARTIFACT_S3_BUCKET": state["bucket"],
            "ARTIFACT_S3_ENDPOINT_URL": state["endpoint"],
            "ARTIFACT_S3_REGION": "garage",
            "ARTIFACT_S3_ACCESS_KEY": state["access_key"],
            "ARTIFACT_S3_SECRET_KEY": state["secret_key"],
        }.items()
    )


def local(args) -> None:
    directory = args.state_dir.resolve()
    if args.action == "restore":
        restore_local(args)
        return
    if args.action == "up":
        state = local_setup(directory, args.port, args.endpoint)
    else:
        state = json.loads((directory / "state.json").read_text())
        # Storage-only status/backup/stop also work before first adoption on upgrade.
        write_local_state(directory, state)
    compose = local_compose(directory, state)
    if args.action == "down":
        run([*compose, "stop", "garage"])
        print("Garage stopped; named volumes and private configuration preserved")
        return
    if args.action == "status":
        result = run([*compose, "ps", "--format", "json", "garage"])
        print(result.stdout)
        return
    if args.action == "backup":
        if args.backup_dir is None:
            raise ValueError("backup requires --backup-dir")
        destination = args.backup_dir.resolve()
        if not args.backup_dir.is_absolute() or destination.is_relative_to(ROOT):
            raise ValueError("Backup destination must be absolute and outside the repository (it contains credentials)")
        if destination.is_relative_to(directory) or destination.exists():
            raise ValueError("Backup destination must be a new directory outside the Garage configuration")
        if not run([*compose, "ps", "-q", "garage"]).stdout.strip():
            raise ValueError("Start Garage before taking a consistent backup")
        running = bool(run([*compose, "ps", "--status", "running", "-q", "garage"]).stdout.strip())
        destination.mkdir(mode=0o700, parents=True)
        try:
            run([*compose, "stop", "garage"])
            shutil.copytree(directory, destination / "configuration")
            run([*compose, "cp", "garage:/var/lib/garage/meta", str(destination / "metadata")], timeout=None)
            run([*compose, "cp", "garage:/var/lib/garage/data", str(destination / "data")], timeout=None)
            private_file(destination / "complete", "Garage stopped consistently before metadata/data copy\n")
        finally:
            if running:
                run([*compose, "start", "garage"])
        print(f"Private consistent Garage backup saved to {destination}")
        return

    def cli(arguments, **kwargs):
        return run([*compose, "exec", "-T", "garage", "/garage", *arguments], **kwargs)

    try:
        run([*compose, "up", "-d", "--wait", "--wait-timeout", "90"], timeout=300)
        node_id = cli(["node", "id"]).stdout.strip()
        if state.get("node_id") and state["node_id"] != node_id:
            raise ValueError("Garage node identity changed; stop and restore the original metadata and data")
        provision_bucket(cli, state["bucket"], state["access_key"], state["secret_key"])
        state.update(initialized=True, node_id=node_id)
        write_local_state(directory, state)
        private_file(directory / "application.env", application_env(state))
    except Exception:
        if not state["initialized"]:
            # Only an unpublished first attempt may discard its own newly created volumes.
            cleanup = remove_unpublished_storage(compose, state)
            if cleanup.returncode:
                print("Initial Garage cleanup failed; resolve Docker health before retrying", file=sys.stderr)
        raise
    print(f"Persistent Garage ready at {state['endpoint']}; application configuration: {directory / 'application.env'}")


def remove_unpublished_storage(compose: list[str], state: dict) -> subprocess.CompletedProcess:
    # Never run project-wide down: this project also owns the application database.
    run([*compose, "stop", "garage"], check=False)
    run([*compose, "rm", "-f", "garage"], check=False)
    prefix = state.get("volume_project", state["project"])
    return run(["docker", "volume", "rm", prefix + "_metadata", prefix + "_data"], check=False)


def restore_local(args) -> None:
    directory = args.state_dir.resolve()
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Restore requires an empty target configuration directory")
    if args.backup_dir is None or not (args.backup_dir / "complete").is_file():
        raise ValueError("Restore requires a complete consistent --backup-dir")
    state = json.loads((args.backup_dir / "configuration/state.json").read_text())
    state["project"] = "agentbarn-garage-" + hashlib.sha256(str(directory).encode()).hexdigest()[:12]
    state.pop("volume_project", None)
    if run(
        ["docker", "volume", "ls", "--filter", f"label=com.docker.compose.project={state['project']}", "-q"]
    ).stdout.strip():
        raise ValueError("Restore refuses to overwrite existing Garage volumes")
    if args.port:
        if args.port != state["port"] and not args.endpoint:
            raise ValueError("Changing the restore port also requires --endpoint")
        state["port"] = args.port
    if args.endpoint:
        state["endpoint"] = endpoint(args.endpoint)
        state["endpoint_derived"] = False
    compose = local_compose(directory, state)
    try:
        shutil.copytree(args.backup_dir / "configuration", directory, dirs_exist_ok=True)
        directory.chmod(0o700)
        # A restored store already owns bytes and must never enter first-up cleanup.
        state["initialized"] = True
        write_local_state(directory, state)
        run([*compose, "create", "garage"], timeout=300)
        run([*compose, "cp", str(args.backup_dir / "metadata") + "/.", "garage:/var/lib/garage/meta"], timeout=None)
        run([*compose, "cp", str(args.backup_dir / "data") + "/.", "garage:/var/lib/garage/data"], timeout=None)
        private_file(directory / "application.env", application_env(state))
    except Exception:
        # The target was empty and the project had no volumes before this restore.
        remove_unpublished_storage(compose, state)
        shutil.rmtree(directory, ignore_errors=True)
        raise
    print("Garage restored into fresh stopped volumes; verify metadata and start with the same state directory")


def secret_manifest(name: str, namespace: str, data: dict) -> str:
    return json.dumps(
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": name, "namespace": namespace},
            "type": "Opaque",
            "stringData": data,
        }
    )


def cluster_config(args) -> None:
    directory = args.state_dir.resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    state_file = directory / "cluster.json"
    origin = endpoint(args.endpoint or "")
    if not origin.startswith("https://") and not args.allow_http_local:
        raise ValueError("Cluster downloads require an HTTPS origin")
    if state_file.exists():
        state = json.loads(state_file.read_text())
        if any(
            state[key] != value
            for key, value in {"namespace": args.namespace, "release": args.release, "endpoint": origin}.items()
        ):
            raise ValueError("Preserve the existing cluster identity/endpoint or migrate it explicitly")
    else:
        state = {
            "namespace": args.namespace,
            "release": args.release,
            "endpoint": origin,
            "bucket": "agent-artifacts",
            "access_key": "GK" + secrets.token_hex(16),
            "secret_key": secrets.token_hex(32),
            "rpc_secret": secrets.token_hex(32),
        }
        private_file(state_file, json.dumps(state))
    private_file(
        directory / "rpc-secret.json",
        secret_manifest(args.release + "-rpc", args.namespace, {"rpc-secret": state["rpc_secret"]}),
    )
    print(
        f"Private cluster RPC Secret prepared: {directory / 'rpc-secret.json'}; apply only to the authorized target cluster"
    )


def cluster_init(args) -> None:
    state = json.loads((args.state_dir / "cluster.json").read_text())
    kube = ["kubectl", "--kubeconfig", str(args.kubeconfig.resolve()), "--namespace", state["namespace"]]
    release = state["release"]
    spec = json.loads(run([*kube, "get", "statefulset", release, "-o", "json"]).stdout)
    replicas = spec["spec"]["replicas"]

    def cli(arguments, **kwargs):
        return run([*kube, "exec", "-i", release + "-0", "--", "/garage", *arguments], **kwargs)

    nodes = []
    for index in range(replicas):
        for retry in range(180):
            result = run([*kube, "exec", f"{release}-{index}", "--", "/garage", "node", "id"], check=False)
            if result.returncode == 0:
                node = result.stdout.strip()
                service = json.loads(run([*kube, "get", "service", f"{release}-{index}", "-o", "json"]).stdout)
                address = service["spec"]["clusterIP"]
                expected = f"[{address}]:3901" if ":" in address else f"{address}:3901"
                # node id prints configured DNS text, not the daemon's resolved address.
                status = run(
                    [
                        *kube,
                        "exec",
                        f"{release}-{index}",
                        "--",
                        "/garage",
                        "--rpc-host",
                        node.partition("@")[0] + "@127.0.0.1:3901",
                        "json-api",
                        "GetClusterStatus",
                    ],
                    check=False,
                )
                if status.returncode == 0:
                    own = next(
                        entry for entry in json.loads(status.stdout)["nodes"] if entry["id"] == node.partition("@")[0]
                    )
                    if own["addr"] != expected:
                        raise RuntimeError(
                            "Garage RPC address does not match its stable Service; verify cluster DNS/domain and restart the affected pod before bootstrap"
                        )
                    nodes.append(node)
                    break
            time.sleep(1)
        else:
            raise RuntimeError("Garage pods did not start within the bootstrap deadline")
    for node in nodes[1:]:
        cli(["node", "connect", node])
    layout = json.loads(cli(["json-api", "GetClusterLayout"]).stdout)
    if layout["version"] == 0:
        for index, node in enumerate(nodes):
            cli(["layout", "assign", "--zone", f"node-{index}", "--capacity", args.capacity, node.split("@", 1)[0]])
        cli(["layout", "apply", "--version", "1"])
    else:
        known = {role["id"] for role in layout["roles"]}
        if not {node.split("@", 1)[0] for node in nodes}.issubset(known):
            raise ValueError("Existing Garage layout differs; use the documented node-repair procedure")
    for retry in range(180):
        if cli(["health"], check=False).returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("Garage layout did not become available")
    provision_bucket(cli, state["bucket"], state["access_key"], state["secret_key"])
    values = read_env_text(application_env(state))
    private_file(
        args.state_dir / "application-secret.json",
        secret_manifest(release + "-artifact-storage", state["namespace"], values),
    )
    print(f"Garage initialized; private application Secret: {args.state_dir / 'application-secret.json'}")


def read_env_text(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["up", "down", "status", "backup", "restore", "cluster-config", "cluster-init"]
    )
    parser.add_argument("--state-dir", type=Path, default=ROOT / ".garage")
    parser.add_argument("--port", type=int)
    parser.add_argument("--endpoint")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--namespace", default="agent-farm")
    parser.add_argument("--release", default="garage")
    parser.add_argument("--capacity", default="10GB")
    parser.add_argument("--kubeconfig", type=Path)
    parser.add_argument(
        "--allow-http-local", action="store_true", help="Only for disposable local cluster verification"
    )
    args = parser.parse_args()
    if args.action == "cluster-init" and not args.kubeconfig:
        parser.error("cluster-init requires an explicit --kubeconfig")
    try:
        state_dir = args.state_dir.resolve()
        if state_dir.is_relative_to(ROOT) and not state_dir.is_relative_to(ROOT / ".garage"):
            raise ValueError("Private Garage state must be inside ignored .garage or outside the repository")
        if args.action == "up":
            state_file = state_dir / "state.json"
            initialized = state_file.exists() and json.loads(state_file.read_text()).get("initialized", True)
            if not initialized:
                defaults = dotenv_values(ROOT / ".env", interpolate=False)
                raw_port = os.environ.get("GARAGE_S3_PORT") or defaults.get("GARAGE_S3_PORT")
                if args.port is None and raw_port:
                    try:
                        args.port = int(raw_port)
                    except ValueError:
                        raise ValueError("GARAGE_S3_PORT must be an integer") from None
                args.endpoint = (
                    args.endpoint
                    or os.environ.get("GARAGE_PUBLIC_ENDPOINT")
                    or defaults.get("GARAGE_PUBLIC_ENDPOINT")
                    or None
                )
        if args.port is not None and not 1 <= args.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if args.action == "cluster-config":
            cluster_config(args)
        elif args.action == "cluster-init":
            cluster_init(args)
        else:
            local(args)
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except OSError, subprocess.TimeoutExpired:
        print(
            "Garage setup failed; inspect local configuration and Docker health without disclosing credentials",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
