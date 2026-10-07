"""Provision persistent, namespace-local memory credentials before Helmfile sync."""

import argparse
import base64
import json
import os
import re
import secrets
import shlex
import subprocess
from pathlib import Path
from typing import Any

SECRET_NAME = "agentbarn-memory-bootstrap"
CREDENTIAL_NAMES = (
    "HINDSIGHT_DB_PASSWORD",
    "HINDSIGHT_API_KEY",
    "MEMORY_RUNTIME_SERVICE_KEY",
)


class ProvisioningError(Exception):
    pass


def kubectl(namespace: str, args: list[str], payload: dict[str, Any] | None = None) -> str:
    result = subprocess.run(
        ["kubectl", "--namespace", namespace, "--request-timeout=30s", *args],
        input=None if payload is None else json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if result.returncode:
        # kubectl errors can include a rejected Secret or command arguments.
        raise ProvisioningError("Kubernetes operation failed; sensitive output omitted.")
    return result.stdout


def read_secret(namespace: str, name: str) -> dict[str, Any] | None:
    raw = kubectl(namespace, ["get", "secret", name, "--ignore-not-found", "-o", "json"])
    return json.loads(raw) if raw.strip() else None


def decode_secret(secret: dict[str, Any]) -> dict[str, str]:
    return {key: base64.b64decode(value, validate=True).decode() for key, value in secret.get("data", {}).items()}


def credentials(namespace: str) -> dict[str, str]:
    saved = read_secret(namespace, SECRET_NAME)
    if saved is not None:
        values = decode_secret(saved)
        if any(not values.get(name) for name in CREDENTIAL_NAMES):
            raise ProvisioningError(
                "Memory bootstrap Secret is incomplete; restore it rather than rotating credentials."
            )
        return {name: values[name] for name in CREDENTIAL_NAMES}

    # Adopt existing deployments without rotating a database or backend key.
    database = read_secret(namespace, "postgres-hindsight")
    backend = read_secret(namespace, "hindsight")
    if bool(database) != bool(backend):
        raise ProvisioningError("Existing memory Secrets are incomplete; restore them before bootstrapping.")
    if database and backend:
        db_values, backend_values = decode_secret(database), decode_secret(backend)
        values = {
            "HINDSIGHT_DB_PASSWORD": db_values["POSTGRES_PASSWORD"],
            "HINDSIGHT_API_KEY": backend_values["HINDSIGHT_API_TENANT_API_KEY"],
            "MEMORY_RUNTIME_SERVICE_KEY": backend_values["AGENTBARN_MEMORY_SETTINGS_KEY"],
        }
    else:
        # A missing Secret must never silently rotate the password of an existing volume.
        pvc = kubectl(namespace, ["get", "pvc", "data-postgres-hindsight-0", "--ignore-not-found", "-o", "name"])
        if pvc.strip():
            raise ProvisioningError("Hindsight storage already exists; restore its credentials before bootstrapping.")
        values = {name: secrets.token_hex(32) for name in CREDENTIAL_NAMES}
    if any(not values.get(name) for name in CREDENTIAL_NAMES):
        raise ProvisioningError("Existing memory credentials are incomplete.")
    if values["MEMORY_RUNTIME_SERVICE_KEY"] == values["HINDSIGHT_API_KEY"]:
        raise ProvisioningError("Memory settings and backend authentication keys must differ.")
    kubectl(
        namespace,
        ["create", "-f", "-"],
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": SECRET_NAME, "namespace": namespace},
            "type": "Opaque",
            "data": {name: base64.b64encode(value.encode()).decode() for name, value in values.items()},
        },
    )
    return values


def key_hashes(namespace: str) -> dict[str, str]:
    saved = read_secret(namespace, "hindsight-litellm-hashes")
    if saved is None:
        raise ProvisioningError("Hindsight key hook has not created its hash Secret.")
    values = decode_secret(saved)
    active = values.get("MEMORY_LITELLM_ACTIVE_KEY_HASH", "")
    hashes = values.get("MEMORY_LITELLM_KEY_HASHES", "").split(",")
    if active not in hashes or any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes):
        raise ProvisioningError("Hindsight key hook returned invalid attribution hashes.")
    return {name: values[name] for name in ("MEMORY_LITELLM_ACTIVE_KEY_HASH", "MEMORY_LITELLM_KEY_HASHES")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument(
        "--include-key-hashes", action="store_true", help="Load attribution hashes after the Hindsight hook."
    )
    args = parser.parse_args()
    try:
        values = credentials(os.environ["NAMESPACE"])
        if values["MEMORY_RUNTIME_SERVICE_KEY"] == values["HINDSIGHT_API_KEY"]:
            raise ProvisioningError("Memory settings and backend authentication keys must differ.")
        if args.include_key_hashes:
            values.update(key_hashes(os.environ["NAMESPACE"]))
        if os.environ.get("GITHUB_ACTIONS") == "true":
            for value in values.values():
                escaped = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
                print("::add-mask::" + escaped, flush=True)
        # Keep credentials out of argv, logs, and workflow outputs. Only this
        # short-lived mode-0600 file passes them to the Helmfile subprocess.
        fd = os.open(args.env_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as output:
            for name, value in values.items():
                output.write(f"{name}={shlex.quote(value)}\n")
        print("Agent Memory credentials prepared; existing authentication credentials preserved.")
    except ProvisioningError as error:
        raise SystemExit(str(error)) from None
    except (KeyError, ValueError, subprocess.TimeoutExpired):
        # Parsing exceptions can contain response data. Never surface their repr.
        raise SystemExit(
            "Agent Memory provisioning failed; credentials preserved and sensitive details omitted."
        ) from None


if __name__ == "__main__":
    main()
