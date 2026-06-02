from uuid import UUID

from kubernetes import client


def _resource_name(agent_id: UUID) -> str:
    return f"agent-{agent_id}"


def _labels(agent_id: UUID, org_id: UUID) -> dict[str, str]:
    return {"app": _resource_name(agent_id), "org-id": str(org_id)}


def build_pvc(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
) -> client.V1PersistentVolumeClaim:
    return client.V1PersistentVolumeClaim(
        metadata=client.V1ObjectMeta(
            name=_resource_name(agent_id),
            namespace=namespace,
            labels=_labels(agent_id, org_id),
        ),
        spec=client.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
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
            labels=_labels(agent_id, org_id),
        ),
        spec=client.V1ServiceSpec(
            selector={"app": _resource_name(agent_id)},
            ports=ports,
        ),
    )
