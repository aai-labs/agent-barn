import json
import os
import time
import uuid
from types import SimpleNamespace
from typing import cast

import pytest
from hamcrest import assert_that, contains_inanyorder, equal_to, has_item, has_key, none, not_none
from kubernetes.client import (
    V1ConfigMap,
    V1Container,
    V1Deployment,
    V1DeploymentSpec,
    V1Job,
    V1JobSpec,
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
from kubernetes.client.exceptions import ApiException

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
    for j in k8s.list_jobs(NS, sel):
        k8s.delete_job(j.metadata.name, NS)


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


def _job(name, run_id, *, script="true", backoff_limit=0, active_deadline_seconds=None, container="work"):
    return V1Job(
        metadata=V1ObjectMeta(name=name, labels=_labels(run_id)),
        spec=V1JobSpec(
            backoff_limit=backoff_limit,
            active_deadline_seconds=active_deadline_seconds,
            ttl_seconds_after_finished=60,
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(labels=_labels(run_id)),
                spec=V1PodSpec(
                    restart_policy="Never",
                    containers=[V1Container(name=container, image="busybox", command=["sh", "-c", script])],
                ),
            ),
        ),
    )


def _wait_for_job_finished(k8s, name, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = k8s.get_job(name, NS)
        conditions = (job.status.conditions or []) if job is not None and job.status is not None else []
        finished = [c for c in conditions if c.type in ("Complete", "Failed") and c.status == "True"]
        if finished:
            return job, finished[0]
        time.sleep(1)
    raise TimeoutError(f"job {name} did not finish within {timeout}s")


def _pods_newest_first(k8s, job_name):
    pods = k8s._core_v1.list_namespaced_pod(NS, label_selector=f"job-name={job_name}").items
    return sorted(pods, key=lambda p: p.metadata.creation_timestamp, reverse=True)


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


def test_job_crud(k8s, run_id):
    name = f"test-job-{run_id}"
    created = k8s.create_job(NS, _job(name, run_id))
    assert_that(created.metadata.name, equal_to(name))
    assert_that(k8s.get_job(name, NS), not_none())
    assert_that(
        [j.metadata.name for j in k8s.list_jobs(NS, f"test-run-id={run_id}")],
        has_item(name),
    )
    k8s.delete_job(name, NS)
    _wait_for_deletion(lambda: k8s.get_job(name, NS))
    assert_that(k8s.get_job(name, NS), none())


def test_create_job_twice_raises_conflict(k8s, run_id):
    name = f"test-job-conflict-{run_id}"
    manifest = _job(name, run_id)
    k8s.create_job(NS, manifest)
    with pytest.raises(ApiException) as exc_info:
        k8s.create_job(NS, manifest)
    assert_that(exc_info.value.status, equal_to(409))


def test_delete_nonexistent_job_is_safe(k8s):
    k8s.delete_job(f"does-not-exist-{uuid.uuid4().hex}", NS)


def test_job_exit_code_is_read_from_the_newest_pod(k8s, run_id):
    name = f"test-job-exit-{run_id}"
    script = "exit $(( $(date +%s) % 200 + 10 ))"
    k8s.create_job(NS, _job(name, run_id, script=script, backoff_limit=1))
    _wait_for_job_finished(k8s, name)

    pods = _pods_newest_first(k8s, name)
    assert_that(len(pods), equal_to(2))
    newest_exit_code = pods[0].status.container_statuses[0].state.terminated.exit_code

    assert_that(k8s.get_job_exit_code(name, NS), equal_to(newest_exit_code))


def test_a_job_killed_by_its_deadline_leaves_no_pod_exit_code_or_logs(k8s, run_id):
    name = f"test-job-deadline-{run_id}"
    script = 'echo \'{"bytes": 1, "file_count": 2}\'; sleep 60'
    k8s.create_job(NS, _job(name, run_id, script=script, active_deadline_seconds=5, container="archive"))
    _, condition = _wait_for_job_finished(k8s, name)

    assert_that(condition.type, equal_to("Failed"))
    assert_that(condition.reason, equal_to("DeadlineExceeded"))
    assert_that(k8s.get_pod_name_for_job(name, NS), none())
    assert_that(k8s.get_job_exit_code(name, NS), none())
    assert_that(k8s.read_job_logs(name, NS), none())


def test_job_logs_are_read_from_the_newest_pod(k8s, run_id):
    name = f"test-job-logs-{run_id}"
    script = 'echo "{\\"started\\": $(date +%s)}"; exit 3'
    k8s.create_job(NS, _job(name, run_id, script=script, backoff_limit=1, container="archive"))
    _wait_for_job_finished(k8s, name)

    newest = _pods_newest_first(k8s, name)[0]
    expected = k8s._core_v1.read_namespaced_pod_log(
        newest.metadata.name, NS, container="archive", _preload_content=False
    ).data.decode("utf-8")

    logs = k8s.read_job_logs(name, NS)
    assert_that(logs, equal_to(expected))
    assert_that(json.loads(logs.strip().splitlines()[-1]), has_key("started"))


def test_a_log_body_that_is_itself_valid_json_is_returned_verbatim(k8s, run_id):
    name = f"test-job-json-log-{run_id}"
    script = 'echo \'{"bytes": 4096, "file_count": 12}\''
    k8s.create_job(NS, _job(name, run_id, script=script, container="archive"))
    _wait_for_job_finished(k8s, name)

    logs = k8s.read_job_logs(name, NS)

    assert_that(json.loads(logs), equal_to({"bytes": 4096, "file_count": 12}))


def test_a_log_body_with_several_lines_is_returned_as_text_not_a_bytes_repr(k8s, run_id):
    name = f"test-job-multiline-log-{run_id}"
    script = 'echo \'{"bytes": 1, "file_count": 2}\'; echo "restore failed: boom" >&2; exit 3'
    k8s.create_job(NS, _job(name, run_id, script=script, container="archive"))
    _wait_for_job_finished(k8s, name)

    logs = k8s.read_job_logs(name, NS)

    assert_that(logs.splitlines(), contains_inanyorder('{"bytes": 1, "file_count": 2}', "restore failed: boom"))


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
