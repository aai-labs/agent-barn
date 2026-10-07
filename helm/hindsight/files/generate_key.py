"""Generate the Hindsight platform key using the application's Helm hook pattern."""

import base64
import hashlib
import json
import math
import os
import ssl
import time
import urllib.error
import urllib.request


def main():
    litellm_url = "http://litellm:4000"
    litellm_headers = {
        "Authorization": "Bearer " + os.environ["LITELLM_MASTER_KEY"],
        "Content-Type": "application/json",
    }
    with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace") as namespace_file:
        namespace = namespace_file.read().strip()
    with open("/var/run/secrets/kubernetes.io/serviceaccount/token") as token_file:
        sa_token = token_file.read().strip()
    context = ssl.create_default_context(cafile="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
    kube_headers = {"Authorization": "Bearer " + sa_token, "Content-Type": "application/json"}
    secrets_url = f"https://kubernetes.default.svc/api/v1/namespaces/{namespace}/secrets"
    secret_name = os.environ["KEY_SECRET_NAME"]
    hashes_name = os.environ["HASHES_SECRET_NAME"]
    alias = "agentbarn-hindsight"
    budget = float(os.environ["KEY_BUDGET_USD"])
    if not math.isfinite(budget) or budget <= 0:
        raise SystemExit("Hindsight key budget must be a positive finite USD amount.")

    def request(url, headers, body=None, method=None, kube=False):
        req = urllib.request.Request(
            url, headers=headers, data=None if body is None else json.dumps(body).encode(), method=method
        )
        with urllib.request.urlopen(req, context=context if kube else None, timeout=10) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}

    def read_hashes():
        try:
            secret = request(secrets_url + "/" + hashes_name, kube_headers, kube=True)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            return {}
        return {name: base64.b64decode(value).decode() for name, value in secret.get("data", {}).items()}

    def save_secret(name, values):
        body = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": name, "namespace": namespace},
            "type": "Opaque",
            "data": {field: base64.b64encode(value.encode()).decode() for field, value in values.items()},
        }
        try:
            request(secrets_url, kube_headers, body, "POST", kube=True)
        except urllib.error.HTTPError as error:
            if error.code != 409:
                raise
            request(secrets_url + "/" + name, kube_headers, body, "PUT", kube=True)
        print(f"Secret '{name}' written", flush=True)

    print("Waiting for LiteLLM to accept connections...", flush=True)
    for _ in range(18):
        try:
            request(litellm_url + "/health/readiness", {})
            break
        except (urllib.error.URLError, TimeoutError):
            time.sleep(10)
    else:
        raise SystemExit("LiteLLM did not become ready after 3 minutes")

    previous = read_hashes()
    try:
        request(litellm_url + "/key/delete", litellm_headers, {"key_aliases": [alias]})
    except urllib.error.HTTPError as error:
        if error.code not in (400, 404):
            raise
    response = request(
        litellm_url + "/key/generate",
        litellm_headers,
        {
            "duration": None,
            "key_alias": alias,
            "team_id": None,
            "max_budget": budget,
            "budget_duration": "30d",
            "metadata": {"agentbarn_memory": True, "purpose": "bankless-startup"},
        },
    )
    key = response["key"]
    if not isinstance(key, str) or not key.startswith("sk-"):
        raise SystemExit("LiteLLM returned an invalid key; response details omitted.")
    active = hashlib.sha256(key.encode()).hexdigest()
    retired = previous.get("MEMORY_LITELLM_KEY_HASHES", "") + "," + os.environ.get("RETIRED_KEY_HASHES", "")
    hashes = {part.strip() for part in retired.split(",") if part.strip()}
    hashes.add(active)
    # Only Hindsight receives the plaintext key. API/gateway cost settings receive hashes.
    save_secret(secret_name, {"LITELLM_API_KEY": key})
    save_secret(
        hashes_name,
        {"MEMORY_LITELLM_ACTIVE_KEY_HASH": active, "MEMORY_LITELLM_KEY_HASHES": ",".join(sorted(hashes))},
    )
    print("Hindsight LiteLLM key generated successfully", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError):
        raise SystemExit("Hindsight key provisioning failed; credential and response details omitted.") from None
