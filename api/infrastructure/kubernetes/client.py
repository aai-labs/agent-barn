from __future__ import annotations

import http.client
import json
import subprocess
from dataclasses import dataclass, field

from injector import inject, singleton
from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.client.exceptions import ApiException

from api.core.config import Config


@inject
@dataclass
@singleton
class KubernetesClient:
    config: Config
    _apps_v1: client.AppsV1Api = field(init=False)
    _core_v1: client.CoreV1Api = field(init=False)

    def __post_init__(self) -> None:
        if self.config.k8s_kubeconfig_path:
            k8s_config.load_kube_config(config_file=self.config.k8s_kubeconfig_path)
        else:
            try:
                k8s_config.load_incluster_config()
            except k8s_config.ConfigException:
                k8s_config.load_kube_config()
        self._apps_v1 = client.AppsV1Api()
        self._core_v1 = client.CoreV1Api()

    def _create_or_get(self, create_fn, read_fn, namespace: str, manifest):
        try:
            return create_fn(namespace, manifest)
        except ApiException as e:
            if e.status == 409:
                return read_fn(manifest.metadata.name, namespace)
            raise

    def _delete_ignoring_not_found(self, delete_fn, name: str, namespace: str) -> None:
        try:
            delete_fn(name, namespace)
        except ApiException as e:
            if e.status != 404:
                raise

    def _get_or_none(self, read_fn, name: str, namespace: str):
        try:
            return read_fn(name, namespace)
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    def create_deployment(
        self, namespace: str, manifest: client.V1Deployment
    ) -> client.V1Deployment:
        return self._create_or_get(
            self._apps_v1.create_namespaced_deployment,
            self._apps_v1.read_namespaced_deployment,
            namespace,
            manifest,
        )

    def delete_deployment(self, name: str, namespace: str) -> None:
        self._delete_ignoring_not_found(
            self._apps_v1.delete_namespaced_deployment, name, namespace
        )

    def get_deployment(self, name: str, namespace: str) -> client.V1Deployment | None:
        return self._get_or_none(
            self._apps_v1.read_namespaced_deployment, name, namespace
        )

    def list_deployments(
        self, namespace: str, label_selector: str = ""
    ) -> list[client.V1Deployment]:
        return self._apps_v1.list_namespaced_deployment(
            namespace, label_selector=label_selector
        ).items

    def create_service(
        self, namespace: str, manifest: client.V1Service
    ) -> client.V1Service:
        return self._create_or_get(
            self._core_v1.create_namespaced_service,
            self._core_v1.read_namespaced_service,
            namespace,
            manifest,
        )

    def delete_service(self, name: str, namespace: str) -> None:
        self._delete_ignoring_not_found(
            self._core_v1.delete_namespaced_service, name, namespace
        )

    def get_service(self, name: str, namespace: str) -> client.V1Service | None:
        return self._get_or_none(self._core_v1.read_namespaced_service, name, namespace)

    def list_services(
        self, namespace: str, label_selector: str = ""
    ) -> list[client.V1Service]:
        return self._core_v1.list_namespaced_service(
            namespace, label_selector=label_selector
        ).items

    def create_pvc(
        self, namespace: str, manifest: client.V1PersistentVolumeClaim
    ) -> client.V1PersistentVolumeClaim:
        return self._create_or_get(
            self._core_v1.create_namespaced_persistent_volume_claim,
            self._core_v1.read_namespaced_persistent_volume_claim,
            namespace,
            manifest,
        )

    def delete_pvc(self, name: str, namespace: str) -> None:
        self._delete_ignoring_not_found(
            self._core_v1.delete_namespaced_persistent_volume_claim, name, namespace
        )

    def get_pvc(
        self, name: str, namespace: str
    ) -> client.V1PersistentVolumeClaim | None:
        return self._get_or_none(
            self._core_v1.read_namespaced_persistent_volume_claim, name, namespace
        )

    def list_pvcs(
        self, namespace: str, label_selector: str = ""
    ) -> list[client.V1PersistentVolumeClaim]:
        return self._core_v1.list_namespaced_persistent_volume_claim(
            namespace, label_selector=label_selector
        ).items

    def create_secret(
        self, namespace: str, manifest: client.V1Secret
    ) -> client.V1Secret:
        return self._create_or_get(
            self._core_v1.create_namespaced_secret,
            self._core_v1.read_namespaced_secret,
            namespace,
            manifest,
        )

    def delete_secret(self, name: str, namespace: str) -> None:
        self._delete_ignoring_not_found(
            self._core_v1.delete_namespaced_secret, name, namespace
        )

    def get_secret(self, name: str, namespace: str) -> client.V1Secret | None:
        return self._get_or_none(self._core_v1.read_namespaced_secret, name, namespace)

    def list_secrets(
        self, namespace: str, label_selector: str = ""
    ) -> list[client.V1Secret]:
        return self._core_v1.list_namespaced_secret(
            namespace, label_selector=label_selector
        ).items

    def create_config_map(
        self, namespace: str, manifest: client.V1ConfigMap
    ) -> client.V1ConfigMap:
        return self._create_or_get(
            self._core_v1.create_namespaced_config_map,
            self._core_v1.read_namespaced_config_map,
            namespace,
            manifest,
        )

    def delete_config_map(self, name: str, namespace: str) -> None:
        self._delete_ignoring_not_found(
            self._core_v1.delete_namespaced_config_map, name, namespace
        )

    def get_config_map(self, name: str, namespace: str) -> client.V1ConfigMap | None:
        return self._get_or_none(
            self._core_v1.read_namespaced_config_map, name, namespace
        )

    def list_config_maps(
        self, namespace: str, label_selector: str = ""
    ) -> list[client.V1ConfigMap]:
        return self._core_v1.list_namespaced_config_map(
            namespace, label_selector=label_selector
        ).items

    def get_pod_name_for_deployment(
        self, deployment_name: str, namespace: str
    ) -> str | None:
        pods = self._core_v1.list_namespaced_pod(
            namespace, label_selector=f"app={deployment_name}"
        )
        for pod in pods.items:
            if pod.status.phase == "Running":
                return pod.metadata.name
        return None

    def exec_command(self, pod_name: str, namespace: str, command: list[str]) -> str:
        kubectl_args = ["kubectl", "exec", pod_name, "-n", namespace, "--"]
        if self.config.k8s_kubeconfig_path:
            kubectl_args = [
                "kubectl",
                "--kubeconfig",
                self.config.k8s_kubeconfig_path,
                "exec",
                pod_name,
                "-n",
                namespace,
                "--",
            ]
        result = subprocess.run(
            [*kubectl_args, *command],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip()
                or f"kubectl exec failed with code {result.returncode}"
            )
        return result.stdout

    def fetch_agent_healthz(self, service_name: str, namespace: str) -> dict:
        host = f"{service_name}.{namespace}"
        try:
            conn = http.client.HTTPConnection(host, 8081, timeout=5)
            conn.request("GET", "/healthz")
            response = conn.getresponse()
            return json.loads(response.read())
        except Exception as exc:
            raise RuntimeError(
                f"healthz unreachable for {service_name}: {exc}"
            ) from exc
