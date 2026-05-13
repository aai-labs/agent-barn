from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from hamcrest import assert_that, calling, equal_to, none, not_none, raises
from kubernetes.client import V1Deployment, V1ObjectMeta, V1Service
from kubernetes.client.exceptions import ApiException

from api.core.config import Config
from api.infrastructure.kubernetes.client import KubernetesClient


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
    def __init__(self, resource=None):
        self._resource = resource

    def list_namespaced_service(self, *_, label_selector=""):
        return SimpleNamespace(items=[self._resource] if self._resource else [])


def _make_client(apps_api=None, core_api=None) -> KubernetesClient:
    config = SimpleNamespace(k8s_kubeconfig_path=None, k8s_namespace="agent-farm")
    with patch("kubernetes.config.load_incluster_config"), \
         patch("kubernetes.config.load_kube_config"), \
         patch("kubernetes.client.AppsV1Api"), \
         patch("kubernetes.client.CoreV1Api"):
        c = KubernetesClient(cast(Config, config))
    c._apps_v1 = apps_api or _FakeAppsApi()
    c._core_v1 = core_api or _FakeCoreApi()
    return c


def test_create_deployment_returns_created_resource():
    manifest = V1Deployment(metadata=V1ObjectMeta(name="dep"))
    k8s = _make_client(apps_api=_FakeAppsApi())
    result = k8s.create_deployment("agent-farm", manifest)
    assert_that(result.metadata.name, equal_to("dep"))


def test_create_deployment_returns_existing_on_conflict():
    existing = V1Deployment(metadata=V1ObjectMeta(name="dep"))
    api = _FakeAppsApi(resource=existing, raises_on={"create": ApiException(status=409)})
    k8s = _make_client(apps_api=api)
    result = k8s.create_deployment("agent-farm", V1Deployment(metadata=V1ObjectMeta(name="dep")))
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
