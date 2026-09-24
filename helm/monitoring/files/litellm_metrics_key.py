#!/usr/bin/env python3
"""Provision the read-only LiteLLM key Prometheus scrapes /metrics with.

LiteLLM only serves /metrics to proxy admins, and its metrics carry every
Organization's key aliases and spend, so the endpoint stays authenticated
and Prometheus gets a dedicated proxy_admin_viewer key (read-only: it can't
mint or change keys). The key is written to a Secret mounted into the
Prometheus server.

Idempotent: a still-valid key already in the Secret is kept, so upgrades
don't rotate it (a rotation would 401 scrapes until the kubelet refreshes
the mounted Secret).
"""
import base64
import json
import os
import ssl
import time
import urllib.error
import urllib.request

LITELLM_URL = os.environ.get("LITELLM_URL", "http://litellm:4000")
USER_ID = "prometheus-metrics"
USER_ROLE = "proxy_admin_viewer"
KEY_ALIAS = "prometheus-metrics"
SECRET_NAME = os.environ.get("SECRET_NAME", "litellm-metrics-key")
SECRET_KEY = "LITELLM_METRICS_KEY"
SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"
APISERVER = "https://kubernetes.default.svc"


def litellm(path, body=None):
    """Call LiteLLM as the master key; returns (status, parsed body)."""
    req = urllib.request.Request(
        f"{LITELLM_URL}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None


def wait_for_litellm():
    print("Waiting for LiteLLM to accept connections...", flush=True)
    for i in range(18):
        try:
            urllib.request.urlopen(f"{LITELLM_URL}/health/readiness", timeout=10).read()
            print("LiteLLM is ready", flush=True)
            return
        except Exception as e:
            print(f"  attempt {i + 1}/18: {e}", flush=True)
            time.sleep(10)
    raise SystemExit("LiteLLM did not become ready after 3 minutes")


def ensure_user():
    status, body = litellm(f"/user/info?user_id={USER_ID}")
    if status == 404:
        status, _ = litellm(
            "/user/new",
            {"user_id": USER_ID, "user_role": USER_ROLE, "auto_create_key": False},
        )
        if status != 200:
            raise SystemExit(f"Creating LiteLLM user '{USER_ID}' failed (HTTP {status})")
        print(f"Created LiteLLM user '{USER_ID}' ({USER_ROLE})", flush=True)
        return
    if status != 200:
        raise SystemExit(f"Looking up LiteLLM user '{USER_ID}' failed (HTTP {status})")
    if (body.get("user_info") or {}).get("user_role") != USER_ROLE:
        status, _ = litellm("/user/update", {"user_id": USER_ID, "user_role": USER_ROLE})
        if status != 200:
            raise SystemExit(f"Setting role on LiteLLM user '{USER_ID}' failed (HTTP {status})")
        print(f"Reset LiteLLM user '{USER_ID}' to {USER_ROLE}", flush=True)


def key_is_current(key):
    status, body = litellm(f"/key/info?key={key}")
    info = (body or {}).get("info") or {}
    return status == 200 and info.get("user_id") == USER_ID and info.get("key_alias") == KEY_ALIAS


def generate_key():
    # Aliases are unique across LiteLLM keys; clear any stale one first.
    status, _ = litellm("/key/delete", {"key_aliases": [KEY_ALIAS]})
    if status not in (200, 400, 404):
        raise SystemExit(f"Deleting stale key '{KEY_ALIAS}' failed (HTTP {status})")
    status, body = litellm(
        "/key/generate",
        {"key_alias": KEY_ALIAS, "user_id": USER_ID, "duration": None},
    )
    if status != 200 or not (body or {}).get("key"):
        raise SystemExit(f"Generating key '{KEY_ALIAS}' failed (HTTP {status})")
    print(f"Generated key '{KEY_ALIAS}'", flush=True)
    return body["key"]


class Kube:
    def __init__(self):
        with open(f"{SA_DIR}/token") as f:
            self.token = f.read().strip()
        with open(f"{SA_DIR}/namespace") as f:
            self.namespace = f.read().strip()
        self.ctx = ssl.create_default_context(cafile=f"{SA_DIR}/ca.crt")

    def _call(self, method, path, body=None):
        req = urllib.request.Request(
            f"{APISERVER}/api/v1/namespaces/{self.namespace}/secrets{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(req, context=self.ctx, timeout=10) as resp:
            return json.loads(resp.read())

    def read_key(self):
        try:
            secret = self._call("GET", f"/{SECRET_NAME}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        value = (secret.get("data") or {}).get(SECRET_KEY)
        return base64.b64decode(value).decode() if value else None

    def write_key(self, key):
        body = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": SECRET_NAME, "namespace": self.namespace},
            "type": "Opaque",
            "data": {SECRET_KEY: base64.b64encode(key.encode()).decode()},
        }
        try:
            self._call("POST", "", body)
            print(f"Secret '{SECRET_NAME}' created", flush=True)
        except urllib.error.HTTPError as e:
            if e.code != 409:
                raise
            self._call("PUT", f"/{SECRET_NAME}", body)
            print(f"Secret '{SECRET_NAME}' updated", flush=True)


def main(kube=None):
    wait_for_litellm()
    ensure_user()
    kube = kube or Kube()
    existing = kube.read_key()
    if existing and key_is_current(existing):
        print(f"Secret '{SECRET_NAME}' already holds a valid key; keeping it", flush=True)
        return
    kube.write_key(generate_key())


if __name__ == "__main__":
    main()
