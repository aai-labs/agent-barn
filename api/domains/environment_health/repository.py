from dataclasses import dataclass
from datetime import datetime

from injector import inject, singleton
from kubernetes.client import (
    CoreV1Event,
    V1Deployment,
    V1PersistentVolumeClaim,
    V1Pod,
    V1ResourceQuota,
    V1Service,
    V1StatefulSet,
)

from api.core.config import Config
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.prometheus.client import PrometheusClient, PrometheusSample

# The monitoring chart's own alert rules, as Prometheus exposes those that are firing.
_FIRING_ALERTS = 'ALERTS{alertstate="firing"}'
# Each Agent's healthz gauges: whether its runtime works now, and whether it ever did.
_RUNTIME_HEALTH = '{job="agent", __name__=~"agent_healthz_ok|agent_healthz_ever_connected"}'
_KSM = 'job="kube-state-metrics"'


def restart_history_query(window_days: int) -> str:
    """Each pod's restarts over the window, and whether any container in it was OOM-killed.

    Two halves tagged by `signal` so `or` keeps both for the same pod. The restart counter
    survives a container's restarts but not the pod, so a pod replaced in the window starts
    again from zero; that is the pod the page lists, so its own count is the right one.
    """
    window = f"{window_days}d"
    restarts = f"sum by (pod) (increase(kube_pod_container_status_restarts_total{{{_KSM}}}[{window}])) > 0"
    oom = (
        "max by (pod) (max_over_time("
        f'kube_pod_container_status_last_terminated_reason{{{_KSM}, reason="OOMKilled"}}[{window}])) > 0'
    )
    return (
        f'label_replace({restarts}, "signal", "restarts", "", "")'
        f' or label_replace({oom}, "signal", "oom_killed", "", "")'
    )


@inject
@singleton
@dataclass
class EnvironmentHealthRepository:
    """Read-only access to the Agent namespace and its Prometheus, for the environment health page.

    Every read is of the one namespace the API manages (`K8S_NAMESPACE`), where the platform's
    own services and the Agents both run. Nothing here creates, changes or deletes anything.
    Each method raises what its client raised, so the service can tell a refusal from an outage.
    """

    k8s: KubernetesClient
    prometheus: PrometheusClient
    config: Config

    @property
    def namespace(self) -> str:
        return self.config.k8s_namespace

    @property
    def prometheus_configured(self) -> bool:
        return self.prometheus.is_configured

    def pods(self) -> list[V1Pod]:
        return self.k8s.list_pods(self.namespace)

    def deployments(self) -> list[V1Deployment]:
        return self.k8s.list_deployments(self.namespace)

    def stateful_sets(self) -> list[V1StatefulSet]:
        return self.k8s.list_stateful_sets(self.namespace)

    def volume_claims(self) -> list[V1PersistentVolumeClaim]:
        return self.k8s.list_pvcs(self.namespace)

    def services(self) -> list[V1Service]:
        return self.k8s.list_services(self.namespace)

    def resource_quotas(self) -> list[V1ResourceQuota]:
        return self.k8s.list_resource_quotas(self.namespace)

    def warning_events(self) -> list[CoreV1Event]:
        return self.k8s.list_warning_events(self.namespace)

    def firing_alerts(self, *, at: datetime) -> list[PrometheusSample]:
        return self.prometheus.query(_FIRING_ALERTS, at)

    def runtime_health(self, *, at: datetime) -> list[PrometheusSample]:
        return self.prometheus.query(_RUNTIME_HEALTH, at)

    def restart_history(self, *, at: datetime, window_days: int) -> list[PrometheusSample]:
        return self.prometheus.query(restart_history_query(window_days), at)
