import base64
import json
import subprocess
import sys

import pytest

from api.scripts import bootstrap_garage_ci as bootstrap


@pytest.mark.parametrize("existing", [False, True])
def test_bootstrap_reuses_credentials_and_initializes_layout(monkeypatch, tmp_path, existing):
    rpc, admin = "a" * 64, "b" * 64
    monkeypatch.setenv("GARAGE_RPC_SECRET_INPUT", rpc)
    monkeypatch.setenv("GARAGE_ADMIN_TOKEN_INPUT", admin)
    monkeypatch.setattr(sys, "argv", ["bootstrap", "--namespace", "fixture", "--kubeconfig", str(tmp_path / "kube")])
    calls = []

    def command(args, *, data=None, check=True):
        calls.append((args, data))
        if "garage-rpc" in args and "get" in args:
            value = {
                "data": {
                    "rpc-secret": base64.b64encode(rpc.encode()).decode(),
                    "admin-token": base64.b64encode(admin.encode()).decode(),
                }
            }
            return subprocess.CompletedProcess(args, 0, json.dumps(value) if existing else "", "")
        if "pvc" in args:
            return subprocess.CompletedProcess(args, 0, '{"items": []}', "")
        return subprocess.CompletedProcess(args, 0, "", "")

    def init(args):
        for name in ("application-secret.json", "provisioner-secret.json"):
            (args.state_dir / name).write_text("{}")

    monkeypatch.setattr(bootstrap, "command", command)
    monkeypatch.setattr(bootstrap, "cluster_init", init)
    bootstrap.main()
    assert any(args[0] == "helm" and "--wait=false" in args for args, _ in calls)
    assert sum(data is not None and "garage-rpc" in data for _, data in calls) == (0 if existing else 1)
    assert sum(data == "{}" for _, data in calls) == 2


def test_refuses_changed_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("GARAGE_RPC_SECRET_INPUT", "a" * 64)
    monkeypatch.setenv("GARAGE_ADMIN_TOKEN_INPUT", "b" * 64)
    monkeypatch.setattr(sys, "argv", ["bootstrap", "--namespace", "fixture", "--kubeconfig", str(tmp_path / "kube")])
    monkeypatch.setattr(
        bootstrap,
        "command",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args,
            0,
            json.dumps(
                {
                    "data": {
                        "rpc-secret": base64.b64encode(b"x" * 64).decode(),
                        "admin-token": base64.b64encode(b"b" * 64).decode(),
                    }
                }
            ),
            "",
        ),
    )
    with pytest.raises(ValueError, match="credentials differ"):
        bootstrap.main()


def test_refuses_to_replace_missing_credentials_for_retained_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("GARAGE_RPC_SECRET_INPUT", "a" * 64)
    monkeypatch.setenv("GARAGE_ADMIN_TOKEN_INPUT", "b" * 64)
    monkeypatch.setattr(sys, "argv", ["bootstrap", "--namespace", "fixture", "--kubeconfig", str(tmp_path / "kube")])
    calls = []

    def command(args, **kwargs):
        calls.append(args)
        output = '{"items": [{"metadata": {"name": "data-garage-0"}}]}' if "pvc" in args else ""
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(bootstrap, "command", command)
    with pytest.raises(ValueError, match="PVCs exist"):
        bootstrap.main()
    assert not any(args[0] == "helm" or "apply" in args for args in calls)
