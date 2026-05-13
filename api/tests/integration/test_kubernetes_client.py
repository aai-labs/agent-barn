import os
import time
import uuid
from types import SimpleNamespace
from typing import cast

import pytest
from hamcrest import assert_that, equal_to, has_item, none, not_none
from kubernetes.client import (
    V1ConfigMap,
    V1Container,
    V1Deployment,
    V1DeploymentSpec,
    V1LabelSelector,
    V1ObjectMeta,
    V1PersistentVolumeClaim,
    V1PersistentVolumeClaimSpec,
    V1PodSpec,
    V1PodTemplateSpec,
    V1ResourceRequirements,
    V1Secret,
    V1Service,
    V1ServicePort,
    V1ServiceSpec,
)

from api.core.config import Config
from api.infrastructure.kubernetes.client import KubernetesClient

NS = os.environ.get("K8S_NAMESPACE", "agent-farm")


@pytest.fixture(scope="session")
def k8s() -> KubernetesClient:
    config = SimpleNamespace(
        k8s_kubeconfig_path=os.environ.get("K8S_KUBECONFIG_PATH"),
        k8s_namespace=NS,
    )
    return KubernetesClient(cast(Config, config))


@pytest.fixture(scope="session")
def run_id() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture(scope="session", autouse=True)
def cleanup(k8s, run_id):
    yield
    sel = f"test-run-id={run_id}"
    for d in k8s.list_deployments(NS, sel):
        k8s.delete_deployment(d.metadata.name, NS)
    for s in k8s.list_services(NS, sel):
        k8s.delete_service(s.metadata.name, NS)
    for p in k8s.list_pvcs(NS, sel):
        k8s.delete_pvc(p.metadata.name, NS)
    for sec in k8s.list_secrets(NS, sel):
        k8s.delete_secret(sec.metadata.name, NS)
    for cm in k8s.list_config_maps(NS, sel):
        k8s.delete_config_map(cm.metadata.name, NS)


def _wait_for_deletion(get_fn, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if get_fn() is None:
            return
        time.sleep(0.5)
    raise TimeoutError("resource not deleted within timeout")


def _labels(run_id):
    return {"test-run-id": run_id}


def _deployment(name, run_id):
    return V1Deployment(
        metadata=V1ObjectMeta(name=name, labels=_labels(run_id)),
        spec=V1DeploymentSpec(
            selector=V1LabelSelector(match_labels={"app": name}),
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(labels={"app": name}),
                spec=V1PodSpec(containers=[V1Container(name="app", image="nginx:alpine")]),
            ),
        ),
    )


def _service(name, run_id):
    return V1Service(
        metadata=V1ObjectMeta(name=name, labels=_labels(run_id)),
        spec=V1ServiceSpec(selector={"app": name}, ports=[V1ServicePort(port=80)]),
    )


def _pvc(name, run_id):
    return V1PersistentVolumeClaim(
        metadata=V1ObjectMeta(name=name, labels=_labels(run_id)),
        spec=V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            resources=V1ResourceRequirements(requests={"storage": "1Gi"}),
        ),
    )


def _secret(name, run_id):
    return V1Secret(
        metadata=V1ObjectMeta(name=name, labels=_labels(run_id)),
        type="Opaque",
        string_data={"key": "value"},
    )


def _config_map(name, run_id):
    return V1ConfigMap(
        metadata=V1ObjectMeta(name=name, labels=_labels(run_id)),
        data={"key": "value"},
    )


def test_deployment_crud(k8s, run_id):
    name = f"test-dep-{run_id}"
    created = k8s.create_deployment(NS, _deployment(name, run_id))
    assert_that(created.metadata.name, equal_to(name))
    assert_that(k8s.get_deployment(name, NS), not_none())
    assert_that(
        [d.metadata.name for d in k8s.list_deployments(NS, f"test-run-id={run_id}")],
        has_item(name),
    )
    k8s.delete_deployment(name, NS)
    assert_that(k8s.get_deployment(name, NS), none())


def test_service_crud(k8s, run_id):
    name = f"test-svc-{run_id}"
    created = k8s.create_service(NS, _service(name, run_id))
    assert_that(created.metadata.name, equal_to(name))
    assert_that(k8s.get_service(name, NS), not_none())
    k8s.delete_service(name, NS)
    assert_that(k8s.get_service(name, NS), none())


def test_pvc_crud(k8s, run_id):
    name = f"test-pvc-{run_id}"
    created = k8s.create_pvc(NS, _pvc(name, run_id))
    assert_that(created.metadata.name, equal_to(name))
    assert_that(k8s.get_pvc(name, NS), not_none())
    k8s.delete_pvc(name, NS)
    _wait_for_deletion(lambda: k8s.get_pvc(name, NS))
    assert_that(k8s.get_pvc(name, NS), none())


def test_secret_crud(k8s, run_id):
    name = f"test-sec-{run_id}"
    created = k8s.create_secret(NS, _secret(name, run_id))
    assert_that(created.metadata.name, equal_to(name))
    assert_that(k8s.get_secret(name, NS), not_none())
    k8s.delete_secret(name, NS)
    assert_that(k8s.get_secret(name, NS), none())


def test_config_map_crud(k8s, run_id):
    name = f"test-cm-{run_id}"
    created = k8s.create_config_map(NS, _config_map(name, run_id))
    assert_that(created.metadata.name, equal_to(name))
    assert_that(k8s.get_config_map(name, NS), not_none())
    k8s.delete_config_map(name, NS)
    assert_that(k8s.get_config_map(name, NS), none())


def test_create_twice_is_safe(k8s, run_id):
    name = f"test-dep-idem-{run_id}"
    manifest = _deployment(name, run_id)
    k8s.create_deployment(NS, manifest)
    result = k8s.create_deployment(NS, manifest)
    assert_that(result, not_none())


def test_delete_nonexistent_deployment_is_safe(k8s):
    k8s.delete_deployment(f"does-not-exist-{uuid.uuid4().hex}", NS)


def test_delete_nonexistent_service_is_safe(k8s):
    k8s.delete_service(f"does-not-exist-{uuid.uuid4().hex}", NS)


def test_delete_nonexistent_pvc_is_safe(k8s):
    k8s.delete_pvc(f"does-not-exist-{uuid.uuid4().hex}", NS)


def test_delete_nonexistent_secret_is_safe(k8s):
    k8s.delete_secret(f"does-not-exist-{uuid.uuid4().hex}", NS)


def test_delete_nonexistent_config_map_is_safe(k8s):
    k8s.delete_config_map(f"does-not-exist-{uuid.uuid4().hex}", NS)
