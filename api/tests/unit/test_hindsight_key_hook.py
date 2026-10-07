"""Exercise the shipped hook's generate, rotate, and Secret-update protocol."""

import base64
import io
import json
import runpy
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "helm/hindsight/files/generate_key.py"


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    yield


@pytest.fixture
def hook(monkeypatch):
    state: dict[str, Any] = {"secrets": {}, "keys": {}, "generated": 0, "operations": []}
    for name, value in {
        "LITELLM_MASTER_KEY": "test-master",
        "KEY_SECRET_NAME": "hindsight-litellm-key",
        "HASHES_SECRET_NAME": "hindsight-litellm-hashes",
        "RETIRED_KEY_HASHES": "a" * 64,
    }.items():
        monkeypatch.setenv(name, value)
    original_open = open

    def open_file(path, *args, **kwargs):
        if str(path).startswith("/var/run/secrets/kubernetes.io/serviceaccount/"):
            return io.StringIO("agent-farm-staging" if str(path).endswith("namespace") else "test-sa-token")
        return original_open(path, *args, **kwargs)

    def urlopen(request, **kwargs):
        url, method = request.full_url, request.get_method()
        body = json.loads(request.data) if request.data is not None else None
        state["operations"].append((method, url, body))
        response = {}
        if url.startswith("https://kubernetes.default.svc/"):
            assert request.get_header("Authorization") == "Bearer test-sa-token"
            name = url.rsplit("/", 1)[1]
            if method == "GET":
                if name not in state["secrets"]:
                    raise urllib.error.HTTPError(url, 404, "missing", Message(), None)
                response = state["secrets"][name]
            else:
                assert body is not None and body["metadata"]["namespace"] == "agent-farm-staging"
                name = body["metadata"]["name"]
                if method == "POST" and name in state["secrets"]:
                    raise urllib.error.HTTPError(url, 409, "exists", Message(), None)
                state["secrets"][name] = body
        elif url.endswith("/health/readiness"):
            response = {"status": "healthy"}
        else:
            assert request.get_header("Authorization") == "Bearer test-master"
            if "/key/info?key=" in url:
                response = {"info": next(iter(state["keys"].values()))}
            elif url.endswith("/key/delete"):
                assert body == {"key_aliases": ["agentbarn-hindsight"]}
                state["keys"].clear()
            else:
                assert url.endswith("/key/generate") and body is not None
                state["generated"] += 1
                response = {"key": f"sk-hook-key-{state['generated']}"}
                state["keys"][response["key"]] = body
        return io.BytesIO(json.dumps(response).encode())

    monkeypatch.setattr("builtins.open", open_file)
    monkeypatch.setattr("ssl.create_default_context", lambda **kwargs: object())
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return state


def run_hook():
    runpy.run_path(str(SCRIPT), run_name="__main__")


def decode(secret):
    return {name: base64.b64decode(value).decode() for name, value in secret["data"].items()}


def test_hook_generates_key_then_rotates_and_updates_secrets(hook, capsys):
    run_hook()
    first = decode(hook["secrets"]["hindsight-litellm-key"])
    first_hashes = decode(hook["secrets"]["hindsight-litellm-hashes"])
    run_hook()
    second = decode(hook["secrets"]["hindsight-litellm-key"])
    hashes = decode(hook["secrets"]["hindsight-litellm-hashes"])
    assert first != second and hook["generated"] == 2
    assert set(first) == {"LITELLM_API_KEY"}
    assert set(hashes) == {"MEMORY_LITELLM_ACTIVE_KEY_HASH", "MEMORY_LITELLM_KEY_HASHES"}
    assert first_hashes["MEMORY_LITELLM_ACTIVE_KEY_HASH"] in hashes["MEMORY_LITELLM_KEY_HASHES"].split(",")
    assert "a" * 64 in hashes["MEMORY_LITELLM_KEY_HASHES"].split(",")
    policy = next(iter(hook["keys"].values()))
    assert "models" not in policy  # Same configured-model access as the application key hook.
    assert policy["team_id"] is None
    assert "max_budget" not in policy and "budget_duration" not in policy
    assert any(method == "PUT" for method, _, _ in hook["operations"])
    output = capsys.readouterr()
    assert all(key not in output.out + output.err for key in [*first.values(), *second.values(), "test-master"])
