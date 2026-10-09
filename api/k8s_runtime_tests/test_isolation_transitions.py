"""Opt-in deployment-boundary contract; API authorization is covered in API tests."""

import base64
import json
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from api.domains.agents.models import SecretProvider
from api.domains.credential_gateway.aai_store import sharepoint_refresh_token
from api.domains.integrations.plugins.aai_cli_support import AaiCliIntegration
from api.domains.integrations.plugins.base import EgressMode
from api.domains.integrations.plugins.registry import INTEGRATION_PLUGINS
from api.domains.integrations.runtime import RuntimeBinding, RuntimeContext, materialize_integrations
from api.tests.helpers.integration_credentials import credential_for

FIXTURES = Path(__file__).parent / "fixtures"
RUNTIME = os.environ.get("ISOLATION_TEST_RUNTIME", "both")
RUNTIMES = ("hermes", "openclaw") if RUNTIME == "both" else (RUNTIME,)


def resource(kind: str, name: str, **fields) -> dict:
    return {"apiVersion": "v1", "kind": kind, "metadata": {"name": name}, **fields}


def pod(image: str, runtime: str, identity: tuple[int, int], *, broker: bool = False, phase: str = "") -> dict:
    name = f"broker-{runtime}" if broker else f"{runtime}-{phase}"
    home = "/opt/data" if runtime == "hermes" else "/home/node"
    store = f"{home}/.config/aai-cli" if runtime == "hermes" else "/home/node/.openclaw/aai-cli"
    container = {
        "name": "contract",
        "image": image,
        "imagePullPolicy": "Never",
        "command": ["python3", "-B", "/fixture/broker.py" if broker else "/fixture/phase.py"],
        "args": [] if broker else [phase, home, store],
        "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"memory": "512Mi"}},
        "volumeMounts": [{"name": "fixture", "mountPath": "/fixture", "readOnly": True}],
    }
    volumes = [{"name": "fixture", "configMap": {"name": "fixture"}}]
    if broker:
        container["readinessProbe"] = {"httpGet": {"path": "/observations", "port": 18080}}
    else:
        container["env"] = [{"name": "HOME", "value": home}]
        container["envFrom"] = [{"secretRef": {"name": name}}]
        container["volumeMounts"] += [
            {"name": "config", "mountPath": "/app/config", "readOnly": True},
            {"name": "data", "mountPath": "/opt/data" if runtime == "hermes" else "/home/node/.openclaw"},
        ]
        volumes += [
            {"name": "config", "configMap": {"name": name}},
            {"name": "data", "persistentVolumeClaim": {"claimName": f"data-{runtime}"}},
        ]
    return {
        "metadata": {"labels": {"contract": runtime, "app": f"broker-{runtime}" if broker else "phase"}},
        "spec": {
            "automountServiceAccountToken": False,
            "restartPolicy": "Always" if broker else "Never",
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": identity[0],
                "runAsGroup": identity[1],
                "fsGroup": identity[1],
            },
            "containers": [container],
            "volumes": volumes,
        },
    }


def install_boundary(cluster, runtime: str, image: str):
    broker_name = f"broker-{runtime}"
    template = pod(image, runtime, cluster.users[runtime], broker=True)
    cluster.apply(
        resource(
            "ConfigMap", "fixture", data={name: (FIXTURES / name).read_text() for name in ("phase.py", "broker.py")}
        ),
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": broker_name},
            "spec": {"replicas": 1, "selector": {"matchLabels": {"app": broker_name}}, "template": template},
        },
        resource(
            "Service",
            broker_name,
            spec={
                "selector": {"app": broker_name},
                "ports": [
                    {"name": "allowed", "port": 18080, "targetPort": 18080},
                    {"name": "denied", "port": 18081, "targetPort": 18081},
                ],
            },
        ),
        resource(
            "PersistentVolumeClaim",
            f"data-{runtime}",
            spec={"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "1Gi"}}},
        ),
        # k3s enforces this policy: only DNS and the fake boundary are reachable.
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": f"offline-{runtime}"},
            "spec": {
                "podSelector": {"matchLabels": {"contract": runtime}},
                "policyTypes": ["Egress"],
                "egress": [
                    {
                        "to": [{"podSelector": {"matchLabels": {"app": broker_name}}}],
                        "ports": [{"protocol": "TCP", "port": 18080}],
                    },
                    {
                        "to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}}],
                        "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}],
                    },
                ],
            },
        },
    )
    cluster.kubectl("rollout", "status", f"deployment/{broker_name}", "--timeout=120s")


def run_phase(cluster, runtime: str, image: str, phase: str):
    home = "/opt/data" if runtime == "hermes" else "/home/node"
    store = f"{home}/.config/aai-cli" if runtime == "hermes" else "/home/node/.openclaw/aai-cli"
    context = RuntimeContext(
        home_dir=home,
        gog_home_dir=home,
        store_dir=store,
        gateway_base_url=f"http://broker-{runtime}:18080/gateway/v1",
        gateway_tokens={p: f"agt_{p.value}_fixture" for p in SecretProvider},
    )
    isolated = phase in {"refused", "isolated", "reboot"}
    bindings = []
    for plugin in INTEGRATION_PLUGINS.for_tool("aai-cli"):
        content = credential_for(plugin.provider)
        if phase == "handback" and plugin.provider == SecretProvider.SHAREPOINT:
            content = content.model_copy(
                update={"refresh_token": "latest-service-grant", "store_revision": "service-revision"}
            )
        bindings.append(RuntimeBinding(plugin.provider, content, plugin.egress_mode if isolated else EgressMode.DIRECT))
    artifacts = materialize_integrations(bindings, context)
    # Direct modes still need the non-secret fixture URL for the egress check.
    artifacts.env.setdefault("AF_GATEWAY_URL", context.gateway_base_url)
    name = f"{runtime}-{phase}"
    cluster.apply(
        resource("Secret", name, type="Opaque", stringData=artifacts.env),
        resource("ConfigMap", name, data=artifacts.files),
    )
    # Read the real persisted Secret, rather than trusting the Python artifact.
    secret = json.loads(cluster.kubectl("get", "secret", name, "-o", "json"))
    values = {key: base64.b64decode(value).decode() for key, value in secret.get("data", {}).items()}
    if isolated:
        assert not any(key.startswith("AAI_SECRET_") for key in values), (
            "Isolated Secret contains direct credential environment"
        )
        configmap = json.loads(cluster.kubectl("get", "configmap", name, "-o", "json"))
        payloads = [*values.values(), *configmap.get("data", {}).values()]
        for plugin in INTEGRATION_PLUGINS.for_tool("aai-cli"):
            assert isinstance(plugin, AaiCliIntegration)
            for _, attr in plugin.aai_cli_secret_entries:
                credential = getattr(credential_for(plugin.provider), attr)
                assert not any(credential in payload for payload in payloads), (
                    "Isolated pod Secret or ConfigMap contains a renewable credential"
                )
    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 120,
            "template": pod(image, runtime, cluster.users[runtime], phase=phase),
        },
    }
    cluster.apply(job)
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        state = json.loads(cluster.kubectl("get", "job", name, "-o", "json"))
        if state.get("status", {}).get("failed"):
            logs = cluster.kubectl("logs", f"job/{name}", "--tail=20")
            pytest.fail(f"{runtime} {phase} contract failed:\n{logs}")
        if state.get("status", {}).get("succeeded"):
            break
        time.sleep(1)
    else:
        pytest.fail(f"{runtime} {phase} contract exceeded the Job deadline")
    observed = json.loads(cluster.kubectl("logs", f"job/{name}").strip())
    assert observed["phase"] == phase and observed["status"] == "ok" and observed["uid"] != 0
    # Remove the old pod and Secret before the next mode can start on its PVC.
    cluster.kubectl("delete", "job", name, "--cascade=foreground", "--wait=true", "--timeout=60s")
    pods = json.loads(cluster.kubectl("get", "pods", "-l", f"job-name={name}", "-o", "json"))
    assert not pods["items"], "Previous mode's pod still exists"
    cluster.kubectl("delete", "secret", name)


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_direct_isolated_direct_on_persistent_storage(cluster, runtime, tmp_path):
    image = os.environ[f"{runtime.upper()}_TEST_IMAGE"]
    install_boundary(cluster, runtime, image)
    # Allocate a random local port; kubectl reports the selected port in stdout.
    with (tmp_path / "port-forward.log").open("w+") as log:
        forward = subprocess.Popen(
            [
                "kubectl",
                "--kubeconfig",
                str(cluster.kubeconfig),
                "--namespace",
                cluster.namespace,
                "port-forward",
                f"service/broker-{runtime}",
                ":18080",
                "--address=127.0.0.1",
            ],
            stdout=log,
            stderr=log,
        )
        try:
            deadline = time.monotonic() + 20
            port = None
            while time.monotonic() < deadline:
                log.seek(0)
                text = log.read()
                if "Forwarding from 127.0.0.1:" in text:
                    port = int(text.split("Forwarding from 127.0.0.1:")[1].split()[0])
                    break
                if forward.poll() is not None:
                    pytest.fail("Fixture broker port-forward exited")
                time.sleep(0.2)
            assert port is not None, "Fixture broker port-forward did not start"
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as broker:
                run_phase(cluster, runtime, image, "direct")
                run_phase(cluster, runtime, image, "refused")
                broker.post("/control", json={"refuse_handoff": False}).raise_for_status()
                run_phase(cluster, runtime, image, "isolated")
                first_boot = broker.get("/observations").json()
                assert first_boot["tokens"] == 1 and first_boot["proxy_calls"] == 1
                run_phase(cluster, runtime, image, "reboot")
                observed = broker.get("/observations").json()
                assert observed["tokens"] == 2 and observed["proxy_calls"] == 2
                handoffs = observed["handoffs"]
                assert len(handoffs) == 3, "Expected refused, successful and repeated-boot handoffs"
                for handoff in handoffs[:2]:
                    assert sharepoint_refresh_token(handoff["store"], handoff["key"]) == "rotated-pvc-grant"
                repeated = handoffs[2]
                assert not repeated["marker"], "Repeated isolated boot recreated a direct sign-in marker"
                with pytest.raises(ValueError, match="SharePoint refresh token missing"):
                    sharepoint_refresh_token(repeated["store"], repeated["key"])
                run_phase(cluster, runtime, image, "handback")
                handback = broker.get("/observations").json()["handback"]
                assert sharepoint_refresh_token(handback["store"], handback["key"]) == "latest-service-grant"
        finally:
            forward.terminate()
            forward.wait(timeout=10)
