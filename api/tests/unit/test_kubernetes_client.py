from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import yaml
from hamcrest import assert_that, calling, equal_to, none, not_none, raises
from kubernetes.client import (
    AppsV1Api,
    CoreV1Api,
    V1Deployment,
    V1ObjectMeta,
    V1Service,
)
from kubernetes.client.exceptions import ApiException

from api.core.config import Config
from api.infrastructure.kubernetes import client as k8s_client_module
from api.infrastructure.kubernetes.client import KubernetesClient
from api.tests.core.givenpy import then, when


def _running_pod(name="agent-pod-abc"):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, deletion_timestamp=None),
        status=SimpleNamespace(phase="Running"),
    )


class _FakeAppsApi:
    def __init__(self, resource=None, raises_on: dict | None = None):
        self._resource = resource
        self._raises_on = raises_on or {}

    def _maybe_raise(self, key):
        if key in self._raises_on:
            raise self._raises_on[key]

    def create_namespaced_deployment(self, _, body):
        self._maybe_raise("create")
        return body

    def read_namespaced_deployment(self, *_):
        self._maybe_raise("read")
        return self._resource

    def delete_namespaced_deployment(self, *_):
        self._maybe_raise("delete")

    def list_namespaced_deployment(self, *_, label_selector=""):
        return SimpleNamespace(items=[self._resource] if self._resource else [])


class _FakeCoreApi:
    def __init__(self, resource=None, pods=None, log_text=None, raises_on=None):
        self._resource = resource
        self._pods = pods or []
        self._log_text = log_text
        self._raises_on = raises_on or {}

    def _maybe_raise(self, key):
        if key in self._raises_on:
            raise self._raises_on[key]

    def list_namespaced_service(self, *_, label_selector=""):
        return SimpleNamespace(items=[self._resource] if self._resource else [])

    def create_namespaced_service(self, _, body):
        self._maybe_raise("create")
        return body

    def read_namespaced_service(self, *_):
        self._maybe_raise("read")
        return self._resource

    def patch_namespaced_service(self, name, namespace, body):
        self._maybe_raise("patch")
        self.patched_service = (name, namespace, body)
        return self._resource

    def list_namespaced_pod(self, namespace, label_selector=""):
        return SimpleNamespace(items=self._pods)

    def read_namespaced_pod_log(self, pod_name, namespace, **kwargs):
        if "read_log" in self._raises_on:
            raise self._raises_on["read_log"]
        if kwargs.get("follow") and not kwargs.get("_preload_content", True):
            return _FakeStreamResponse(self._log_text or "")
        return self._log_text or ""


class _FakeStreamResponse:
    def __init__(self, text: str):
        self._lines = [line.encode() for line in text.splitlines(keepends=True)]

    def __iter__(self):
        return iter(self._lines)

    def close(self):
        pass

    def release_conn(self):
        pass


def _make_client(apps_api=None, core_api=None) -> KubernetesClient:
    config = SimpleNamespace(k8s_kubeconfig_path=None, k8s_namespace="agent-farm")
    with (
        patch("kubernetes.config.load_incluster_config"),
        patch("kubernetes.config.load_kube_config"),
        patch("kubernetes.client.AppsV1Api"),
        patch("kubernetes.client.CoreV1Api"),
    ):
        c = KubernetesClient(cast(Config, config))
    c._apps_v1 = cast(AppsV1Api, apps_api or _FakeAppsApi())
    c._core_v1 = cast(CoreV1Api, core_api or _FakeCoreApi())
    return c


def test_create_deployment_returns_created_resource():
    manifest = V1Deployment(metadata=V1ObjectMeta(name="dep"))
    k8s = _make_client(apps_api=_FakeAppsApi())
    result = k8s.create_deployment("agent-farm", manifest)
    assert_that(result.metadata.name, equal_to("dep"))


def test_create_deployment_returns_existing_on_conflict():
    existing = V1Deployment(metadata=V1ObjectMeta(name="dep"))
    api = _FakeAppsApi(
        resource=existing, raises_on={"create": ApiException(status=409)}
    )
    k8s = _make_client(apps_api=api)
    result = k8s.create_deployment(
        "agent-farm", V1Deployment(metadata=V1ObjectMeta(name="dep"))
    )
    assert_that(result, equal_to(existing))


def test_create_deployment_propagates_non_conflict_errors():
    api = _FakeAppsApi(raises_on={"create": ApiException(status=500)})
    k8s = _make_client(apps_api=api)
    assert_that(
        calling(k8s.create_deployment).with_args(
            "agent-farm", V1Deployment(metadata=V1ObjectMeta(name="dep"))
        ),
        raises(ApiException),
    )


def test_delete_deployment_succeeds():
    k8s = _make_client(apps_api=_FakeAppsApi())
    k8s.delete_deployment("dep", "agent-farm")


def test_delete_deployment_ignores_not_found():
    api = _FakeAppsApi(raises_on={"delete": ApiException(status=404)})
    k8s = _make_client(apps_api=api)
    k8s.delete_deployment("dep", "agent-farm")


def test_get_deployment_returns_resource_when_found():
    dep = V1Deployment(metadata=V1ObjectMeta(name="dep"))
    k8s = _make_client(apps_api=_FakeAppsApi(resource=dep))
    assert_that(k8s.get_deployment("dep", "agent-farm"), not_none())


def test_get_deployment_returns_none_when_not_found():
    api = _FakeAppsApi(raises_on={"read": ApiException(status=404)})
    k8s = _make_client(apps_api=api)
    assert_that(k8s.get_deployment("dep", "agent-farm"), none())


def test_list_services_returns_items():
    svc = V1Service(metadata=V1ObjectMeta(name="svc"))
    k8s = _make_client(core_api=_FakeCoreApi(resource=svc))
    items = k8s.list_services("agent-farm", label_selector="agent-id=123")
    assert_that(len(items), equal_to(1))
    assert_that(items[0].metadata.name, equal_to("svc"))


def test_incluster_apiserver_none_off_cluster(monkeypatch):
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    assert_that(KubernetesClient._incluster_apiserver(), none())


def test_incluster_apiserver_requires_token_file(monkeypatch, tmp_path):
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    monkeypatch.setattr(
        k8s_client_module, "_SERVICE_ACCOUNT_TOKEN_PATH", str(tmp_path / "missing")
    )
    assert_that(KubernetesClient._incluster_apiserver(), none())


def test_incluster_apiserver_builds_url(monkeypatch, tmp_path):
    token = tmp_path / "token"
    token.write_text("x")
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    monkeypatch.setenv("KUBERNETES_SERVICE_PORT_HTTPS", "443")
    monkeypatch.setattr(k8s_client_module, "_SERVICE_ACCOUNT_TOKEN_PATH", str(token))
    assert_that(
        KubernetesClient._incluster_apiserver(), equal_to("https://10.0.0.1:443")
    )


def test_resolve_kubeconfig_unchanged_off_cluster(monkeypatch, tmp_path):
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text(
        yaml.safe_dump(
            {"clusters": [{"cluster": {"server": "https://127.0.0.1:6443"}}]}
        )
    )
    assert_that(
        KubernetesClient._resolve_kubeconfig(str(kubeconfig)), equal_to(str(kubeconfig))
    )


def test_resolve_kubeconfig_rewrites_server_in_cluster(monkeypatch, tmp_path):
    token = tmp_path / "token"
    token.write_text("x")
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    monkeypatch.setenv("KUBERNETES_SERVICE_PORT", "443")
    monkeypatch.setattr(k8s_client_module, "_SERVICE_ACCOUNT_TOKEN_PATH", str(token))
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text(
        yaml.safe_dump(
            {
                "clusters": [
                    {"name": "k3s", "cluster": {"server": "https://127.0.0.1:6443"}}
                ]
            }
        )
    )

    out = KubernetesClient._resolve_kubeconfig(str(kubeconfig))

    assert out != str(kubeconfig)
    with open(out) as f:
        patched = yaml.safe_load(f)
    assert_that(
        patched["clusters"][0]["cluster"]["server"], equal_to("https://10.0.0.1:443")
    )


# --- read_pod_logs ---


def test_read_pod_logs_returns_text_when_pod_exists():
    pod = _running_pod()
    core = _FakeCoreApi(pods=[pod], log_text="line1\nline2\n")
    k8s = _make_client(core_api=core)

    with when("I read pod logs for an existing deployment"):
        result = k8s.read_pod_logs("agent-abc", "agent-farm")

        with then("the log text is returned"):
            assert_that(result, equal_to("line1\nline2\n"))


def test_read_pod_logs_returns_none_when_no_pod():
    core = _FakeCoreApi(pods=[])
    k8s = _make_client(core_api=core)

    with when("I read pod logs for a deployment with no running pod"):
        result = k8s.read_pod_logs("agent-abc", "agent-farm")

        with then("None is returned"):
            assert_that(result, none())


def test_read_pod_logs_returns_none_on_404():
    pod = _running_pod()
    core = _FakeCoreApi(pods=[pod], raises_on={"read_log": ApiException(status=404)})
    k8s = _make_client(core_api=core)

    with when("the pod disappears between lookup and log read"):
        result = k8s.read_pod_logs("agent-abc", "agent-farm")

        with then("None is returned instead of raising"):
            assert_that(result, none())


# --- stream_pod_logs ---


def test_stream_pod_logs_yields_lines():
    pod = _running_pod()
    core = _FakeCoreApi(pods=[pod], log_text="alpha\nbeta\ngamma\n")
    k8s = _make_client(core_api=core)

    with when("I stream pod logs for a running deployment"):
        lines = list(k8s.stream_pod_logs("agent-abc", "agent-farm"))

        with then("each log line is yielded"):
            assert_that(lines, equal_to(["alpha", "beta", "gamma"]))


def test_stream_pod_logs_returns_empty_when_no_pod():
    core = _FakeCoreApi(pods=[])
    k8s = _make_client(core_api=core)

    with when("I stream pod logs for a deployment with no running pod"):
        lines = list(k8s.stream_pod_logs("agent-abc", "agent-farm"))

        with then("no lines are yielded"):
            assert_that(lines, equal_to([]))


def test_create_service_returns_created_resource():
    from kubernetes.client import V1Service

    manifest = V1Service(metadata=V1ObjectMeta(name="agent-x"))
    k8s = _make_client(core_api=_FakeCoreApi())
    result = k8s.create_service("agent-farm", manifest)
    assert_that(result.metadata.name, equal_to("agent-x"))


def test_create_service_refreshes_labels_on_conflict():
    """A restart must propagate new monitoring labels (org-name, component)
    onto the pre-existing Service instead of silently keeping stale ones."""
    from kubernetes.client import V1Service

    existing = V1Service(
        metadata=V1ObjectMeta(name="agent-x", labels={"app": "agent-x"})
    )
    core = _FakeCoreApi(
        resource=existing, raises_on={"create": ApiException(status=409)}
    )
    k8s = _make_client(core_api=core)
    desired_labels = {"app": "agent-x", "org-name": "acme", "org-id": "o1"}
    manifest = V1Service(metadata=V1ObjectMeta(name="agent-x", labels=desired_labels))

    result = k8s.create_service("agent-farm", manifest)

    name, namespace, body = core.patched_service
    assert_that(name, equal_to("agent-x"))
    assert_that(namespace, equal_to("agent-farm"))
    assert_that(body["metadata"]["labels"], equal_to(desired_labels))
    assert_that(result, equal_to(existing))


def test_create_service_propagates_non_conflict_errors():
    from kubernetes.client import V1Service

    core = _FakeCoreApi(raises_on={"create": ApiException(status=500)})
    k8s = _make_client(core_api=core)
    assert_that(
        calling(k8s.create_service).with_args(
            "agent-farm", V1Service(metadata=V1ObjectMeta(name="agent-x"))
        ),
        raises(ApiException),
    )
