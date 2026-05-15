from uuid import UUID

from kubernetes import client


def _resource_name(agent_id: UUID) -> str:
    return f"agent-{agent_id}"


def _labels(agent_id: UUID, org_id: UUID) -> dict[str, str]:
    return {"app": _resource_name(agent_id), "org-id": str(org_id)}


def build_config_map(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    soul_md: str,
    identity_md: str,
    user_md: str,
    tools_md: str,
    agents_md: str,
    boot_md: str,
    bootstrap_md: str,
    heartbeat_md: str,
) -> client.V1ConfigMap:
    return client.V1ConfigMap(
        metadata=client.V1ObjectMeta(
            name=_resource_name(agent_id),
            namespace=namespace,
            labels=_labels(agent_id, org_id),
        ),
        data={
            "SOUL.md": soul_md,
            "IDENTITY.md": identity_md,
            "USER.md": user_md,
            "TOOLS.md": tools_md,
            "AGENTS.md": agents_md,
            "BOOT.md": boot_md,
            "BOOTSTRAP.md": bootstrap_md,
            "HEARTBEAT.md": heartbeat_md,
        },
    )


def build_secret(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    slack_bot_token: str,
    slack_app_token: str,
    litellm_api_key: str,
    litellm_base_url: str,
) -> client.V1Secret:
    return client.V1Secret(
        metadata=client.V1ObjectMeta(
            name=_resource_name(agent_id),
            namespace=namespace,
            labels=_labels(agent_id, org_id),
        ),
        string_data={
            "SLACK_BOT_TOKEN": slack_bot_token,
            "SLACK_APP_TOKEN": slack_app_token,
            "LITELLM_API_KEY": litellm_api_key,
            "OPENAI_API_KEY": litellm_api_key,
            "OPENAI_BASE_URL": litellm_base_url,
        },
    )


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
) -> client.V1Service:
    return client.V1Service(
        metadata=client.V1ObjectMeta(
            name=_resource_name(agent_id),
            namespace=namespace,
            labels=_labels(agent_id, org_id),
        ),
        spec=client.V1ServiceSpec(
            selector={"app": _resource_name(agent_id)},
            ports=[client.V1ServicePort(port=80, target_port=8080)],
        ),
    )


def build_deployment(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    image: str,
    image_pull_secret: str = "",
) -> client.V1Deployment:
    name = _resource_name(agent_id)
    labels = _labels(agent_id, org_id)

    return client.V1Deployment(
        metadata=client.V1ObjectMeta(
            name=name,
            namespace=namespace,
            labels=labels,
        ),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(match_labels={"app": name}),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=labels),
                spec=client.V1PodSpec(
                    image_pull_secrets=(
                        [client.V1LocalObjectReference(name=image_pull_secret)]
                        if image_pull_secret
                        else None
                    ),
                    containers=[
                        client.V1Container(
                            name="agent",
                            image=image,
                            command=["openclaw", "gateway", "--allow-unconfigured"],
                            env_from=[
                                client.V1EnvFromSource(
                                    secret_ref=client.V1SecretEnvSource(name=name)
                                )
                            ],
                            volume_mounts=[
                                client.V1VolumeMount(
                                    name="config",
                                    mount_path="/app/config",
                                ),
                                client.V1VolumeMount(
                                    name="data",
                                    mount_path="/home/node/.openclaw",
                                ),
                            ],
                        )
                    ],
                    volumes=[
                        client.V1Volume(
                            name="config",
                            config_map=client.V1ConfigMapVolumeSource(name=name),
                        ),
                        client.V1Volume(
                            name="data",
                            persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                                claim_name=name
                            ),
                        ),
                    ],
                ),
            ),
        ),
    )
