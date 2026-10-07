"""Provision persistent, namespace-local memory credentials before Helmfile sync."""

import argparse
import base64
import hashlib
import json
import math
import os
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
    "HINDSIGHT_LITELLM_API_KEY",
)
# Run inside LiteLLM: its master credential never leaves the pod. Only captured
# JSON crosses kubectl's stdout; errors omit backend bodies and credentials.
LITELLM_REQUEST = """
import json, os, urllib.request, urllib.error
request = json.load(__import__('sys').stdin)
body = request.get('body')
req = urllib.request.Request(
    'http://127.0.0.1:4000' + request['path'],
    data=None if body is None else json.dumps(body).encode(),
    headers={'Authorization': 'Bearer ' + os.environ['LITELLM_MASTER_KEY'],
             'Content-Type': 'application/json'},
)
try:
    with urllib.request.urlopen(req, timeout=30) as response:
        print(json.dumps({'status': response.status, 'body': json.load(response)}))
except urllib.error.HTTPError as error:
    print(json.dumps({'status': error.code}))
except Exception:
    raise SystemExit('LiteLLM request failed; credential and response details omitted.')
"""


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
            "HINDSIGHT_LITELLM_API_KEY": backend_values["HINDSIGHT_API_LLM_API_KEY"],
        }
    else:
        # A missing Secret must never silently rotate the password of an existing volume.
        pvc = kubectl(namespace, ["get", "pvc", "data-postgres-hindsight-0", "--ignore-not-found", "-o", "name"])
        if pvc.strip():
            raise ProvisioningError("Hindsight storage already exists; restore its credentials before bootstrapping.")
        values = {name: secrets.token_hex(32) for name in CREDENTIAL_NAMES}
        values["HINDSIGHT_LITELLM_API_KEY"] = "sk-" + values["HINDSIGHT_LITELLM_API_KEY"]
    if any(not values.get(name) for name in CREDENTIAL_NAMES):
        raise ProvisioningError("Existing memory credentials are incomplete.")
    if values["MEMORY_RUNTIME_SERVICE_KEY"] == values["HINDSIGHT_API_KEY"]:
        raise ProvisioningError("Memory settings and backend authentication keys must differ.")
    # Persist the candidate key BEFORE its remote creation. After a lost response,
    # the next deployment looks up the same hash instead of issuing another key.
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


def litellm_request(namespace: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    return json.loads(
        kubectl(
            namespace,
            ["exec", "-i", "deploy/litellm", "--", "python", "-c", LITELLM_REQUEST],
            {"path": path, "body": body},
        )
    )


def ensure_key(namespace: str, key: str, model: str, budget: float) -> None:
    path = "/key/info?key=" + hashlib.sha256(key.encode()).hexdigest()
    response = litellm_request(namespace, path)
    if response["status"] == 404:
        created = litellm_request(
            namespace,
            "/key/generate",
            {
                "key": key,
                "key_alias": "agentbarn-hindsight-startup",
                "models": [model],
                "max_budget": budget,
                "budget_duration": "30d",
                "duration": None,
                "team_id": None,
                "metadata": {"agentbarn_memory": True, "purpose": "bankless-startup"},
            },
        )
        if created["status"] != 200 or created.get("body", {}).get("key") != key:
            raise ProvisioningError("LiteLLM memory key creation failed; retry reuses the persisted candidate key.")
        response = litellm_request(namespace, path)
    if response["status"] != 200:
        raise ProvisioningError("LiteLLM memory key validation failed; credentials were preserved.")
    info = response.get("body", {}).get("info", {})
    max_budget = info.get("max_budget")
    if (
        info.get("team_id") is not None
        or info.get("blocked")
        or info.get("expires") is not None
        or info.get("models") != [model]
        or not isinstance(max_budget, (int, float))
        or not math.isfinite(max_budget)
        or max_budget <= 0
        or info.get("budget_duration") != "30d"
    ):
        raise ProvisioningError("Memory key must be unblocked, non-expiring, model-restricted, budgeted, and teamless.")


def provision(namespace: str, model: str, budget: float) -> dict[str, str]:
    if not math.isfinite(budget) or budget <= 0:
        raise ProvisioningError("Memory startup key budget must be a positive finite USD amount.")
    values = credentials(namespace)
    if values["MEMORY_RUNTIME_SERVICE_KEY"] == values["HINDSIGHT_API_KEY"]:
        raise ProvisioningError("Memory settings and backend authentication keys must differ.")
    ensure_key(namespace, values["HINDSIGHT_LITELLM_API_KEY"], model, budget)
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument(
        "--credentials-only",
        action="store_true",
        help="Persist credentials before starting LiteLLM; verify afterwards.",
    )
    args = parser.parse_args()
    try:
        if args.credentials_only:
            values = credentials(os.environ["NAMESPACE"])
        else:
            values = provision(
                os.environ["NAMESPACE"],
                os.environ.get("MEMORY_DEFAULT_MODEL") or "openrouter/openai/gpt-4.1-mini",
                float(os.environ.get("MEMORY_STARTUP_KEY_BUDGET_USD") or "5"),
            )
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
        status = "prepared" if args.credentials_only else "provisioned and verified"
        print(f"Agent Memory credentials {status}; existing credentials preserved.")
    except ProvisioningError as error:
        raise SystemExit(str(error)) from None
    except (KeyError, ValueError, subprocess.TimeoutExpired):
        # Parsing exceptions can contain response data. Never surface their repr.
        raise SystemExit(
            "Agent Memory provisioning failed; credentials preserved and sensitive details omitted."
        ) from None


if __name__ == "__main__":
    main()
