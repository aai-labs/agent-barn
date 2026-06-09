from __future__ import annotations

import http.client
import json
import socket
import subprocess
import time
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

    _TERMINAL_WAITING_REASONS = {
        "CrashLoopBackOff",
        "ImagePullBackOff",
        "ErrImagePull",
        "CreateContainerConfigError",
        "CreateContainerError",
    }

    def get_pod_readiness(
        self, deployment_name: str, namespace: str
    ) -> tuple[str | None, str | None]:
        """Returns (status, reason). status is one of: 'ready', 'initializing', 'crashed', None."""
        pods = self._core_v1.list_namespaced_pod(
            namespace, label_selector=f"app={deployment_name}"
        )
        for pod in pods.items:
            if pod.status.phase == "Failed":
                reason = None
                for cs in pod.status.container_statuses or []:
                    if cs.state and cs.state.terminated:
                        reason = cs.state.terminated.reason or (
                            f"exit code {cs.state.terminated.exit_code}"
                            if cs.state.terminated.exit_code is not None
                            else None
                        )
                        break
                return "crashed", reason
            if pod.status.phase in ("Pending", "Running"):
                conditions = pod.status.conditions or []
                if any(c.type == "Ready" and c.status == "True" for c in conditions):
                    return "ready", None
                container_statuses = pod.status.container_statuses or []
                for cs in container_statuses:
                    if (
                        cs.state
                        and cs.state.waiting
                        and cs.state.waiting.reason in self._TERMINAL_WAITING_REASONS
                    ):
                        return "crashed", cs.state.waiting.reason
                return "initializing", None
        return None, None

    def exec_command(self, pod_name: str, namespace: str, command: list[str]) -> str:
        kubectl_args = self._kubectl_args(["exec", pod_name, "-n", namespace, "--"])
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

    def _kubectl_args(self, args: list[str]) -> list[str]:
        if self.config.k8s_kubeconfig_path:
            return [
                "kubectl",
                "--kubeconfig",
                self.config.k8s_kubeconfig_path,
                *args,
            ]
        return ["kubectl", *args]

    def fetch_agent_healthz(self, service_name: str, namespace: str) -> dict:
        host = f"{service_name}.{namespace}"
        try:
            conn = http.client.HTTPConnection(host, 8081, timeout=5)
            conn.request("GET", "/healthz")
            response = conn.getresponse()
            return json.loads(response.read())
        except Exception:
            return self._fetch_agent_healthz_via_port_forward(service_name, namespace)

    def _fetch_agent_healthz_via_port_forward(
        self, service_name: str, namespace: str
    ) -> dict:
        pod_name = self.get_pod_name_for_deployment(service_name, namespace)
        if not pod_name:
            raise RuntimeError(f"No running pod found for {service_name}")

        local_port = self._free_local_port()
        kubectl_args = self._kubectl_args(
            [
                "port-forward",
                f"pod/{pod_name}",
                "-n",
                namespace,
                f"{local_port}:8081",
            ]
        )
        process = subprocess.Popen(
            kubectl_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self._wait_for_local_port(local_port, process)
            conn = http.client.HTTPConnection("127.0.0.1", local_port, timeout=5)
            conn.request("GET", "/healthz")
            response = conn.getresponse()
            return json.loads(response.read())
        except Exception as exc:
            raise RuntimeError(
                f"healthz unreachable for {service_name}: {exc}"
            ) from exc
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def proxy_to_agent(
        self,
        service_name: str,
        namespace: str,
        port: int,
        path: str,
        method: str,
        body: bytes,
        headers: dict[str, str],
    ) -> tuple[int, bytes, dict[str, str]]:
        host = f"{service_name}.{namespace}"
        try:
            conn = http.client.HTTPConnection(host, port, timeout=30)
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            return resp.status, resp.read(), dict(resp.getheaders())
        except OSError:
            return self._proxy_to_agent_via_port_forward(
                service_name, namespace, port, path, method, body, headers
            )

    def _proxy_to_agent_via_port_forward(
        self,
        service_name: str,
        namespace: str,
        port: int,
        path: str,
        method: str,
        body: bytes,
        headers: dict[str, str],
    ) -> tuple[int, bytes, dict[str, str]]:
        pod_name = self.get_pod_name_for_deployment(service_name, namespace)
        if not pod_name:
            raise RuntimeError(f"No running pod found for {service_name}")

        local_port = self._free_local_port()
        kubectl_args = self._kubectl_args(
            [
                "port-forward",
                f"pod/{pod_name}",
                "-n",
                namespace,
                f"{local_port}:{port}",
            ]
        )
        process = subprocess.Popen(
            kubectl_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self._wait_for_local_port(local_port, process)
            conn = http.client.HTTPConnection("127.0.0.1", local_port, timeout=30)
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            return resp.status, resp.read(), dict(resp.getheaders())
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    @staticmethod
    def _free_local_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    @staticmethod
    def _wait_for_local_port(
        port: int, process: subprocess.Popen, timeout: float = 10
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise RuntimeError(
                    stderr.strip()
                    or stdout.strip()
                    or f"kubectl port-forward exited with code {process.returncode}"
                )
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.25)
                try:
                    sock.connect(("127.0.0.1", port))
                    return
                except OSError:
                    time.sleep(0.1)
        raise RuntimeError(f"kubectl port-forward did not open localhost:{port}")
