import re
from uuid import UUID

from kubernetes import client

_NON_LABEL_CHARS = re.compile(r"[^a-z0-9]+")


def _resource_name(agent_id: UUID) -> str:
    return f"agent-{agent_id}"


def _name_slug_label(name: str, fallback_id: UUID) -> str:
    """Slugify a display name into a valid k8s label value (63 chars, alnum
    edges); falls back to the given id so the label is never empty."""
    slug = _NON_LABEL_CHARS.sub("-", name.lower()).strip("-")[:63].strip("-")
    return slug or str(fallback_id)


def _labels(agent_id: UUID, org_id: UUID) -> dict[str, str]:
    # agentfarm.io/component is the stable selector shared by every agent's
    # resources (Deployment/Service selectors keep matching on "app" only);
    # the monitoring stack discovers all agent Services through it.
    return {
        "app": _resource_name(agent_id),
        "org-id": str(org_id),
        "agentfarm.io/component": "agent",
    }


def build_pvc(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    storage_class: str | None = None,
) -> client.V1PersistentVolumeClaim:
    return client.V1PersistentVolumeClaim(
        metadata=client.V1ObjectMeta(
            name=_resource_name(agent_id),
            namespace=namespace,
            labels=_labels(agent_id, org_id),
        ),
        spec=client.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            # None omits the field so the cluster default StorageClass applies.
            storage_class_name=storage_class or None,
            resources=client.V1ResourceRequirements(
                requests={"storage": "1Gi"},
            ),
        ),
    )


def build_service(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    include_webhook_port: bool = False,
    org_name: str = "",
    agent_name: str = "",
) -> client.V1Service:
    ports = [
        client.V1ServicePort(port=80, target_port=8080, name="gateway"),
        client.V1ServicePort(port=8081, target_port=8081, name="healthz"),
    ]
    if include_webhook_port:
        ports.append(client.V1ServicePort(port=3978, target_port=3978, name="webhook"))
    return client.V1Service(
        metadata=client.V1ObjectMeta(
            name=_resource_name(agent_id),
            namespace=namespace,
            # The Service carries the org-name and agent-name slugs because
            # Prometheus copies target labels from the Service (ServiceMonitor
            # targetLabels) — they give every pod generation of an agent a
            # stable, human-readable identity on dashboards.
            labels={
                **_labels(agent_id, org_id),
                "org-name": _name_slug_label(org_name, org_id),
                "agent-name": _name_slug_label(agent_name, agent_id),
            },
        ),
        spec=client.V1ServiceSpec(
            selector={"app": _resource_name(agent_id)},
            ports=ports,
        ),
    )
