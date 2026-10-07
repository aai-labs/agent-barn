"""Validate supplied memory credentials and load hook-generated attribution hashes."""

import argparse
import base64
import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

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


def credentials() -> dict[str, str]:
    values = {name: os.environ.get(name, "") for name in CREDENTIAL_NAMES}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ProvisioningError("Required memory secrets are missing: " + ", ".join(missing))
    if len(set(values.values())) != len(values):
        raise ProvisioningError("Memory database, backend, and settings credentials must differ.")
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
        values = credentials()
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
        print("Agent Memory credentials prepared; supplied authentication credentials validated.")
    except ProvisioningError as error:
        raise SystemExit(str(error)) from None
    except (KeyError, ValueError, subprocess.TimeoutExpired):
        # Parsing exceptions can contain response data. Never surface their repr.
        raise SystemExit(
            "Agent Memory provisioning failed; credentials preserved and sensitive details omitted."
        ) from None


if __name__ == "__main__":
    main()
