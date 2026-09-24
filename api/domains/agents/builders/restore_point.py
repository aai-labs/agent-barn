import secrets
from uuid import UUID

from kubernetes import client

from api.domains.agents.restore_point_job import (
    ENV_ARCHIVE,
    ENV_BACKUP,
    ENV_DEST,
    ENV_MODE,
    ENV_RUNTIME,
    ENV_SOURCE,
    ENV_TARGET,
    MODE_CAPTURE,
    MODE_RESTORE,
)

COMPONENT_LABEL = "restore-point"
COMPONENT_LABEL_KEY = "agentbarn.io/component"
AGENT_ID_LABEL_KEY = "agentbarn.io/agent-id"
RESTORE_POINT_ID_LABEL_KEY = "agentbarn.io/restore-point-id"

PVC_NAME_PREFIX = "restore-point-"
CAPTURE_JOB_NAME_PREFIX = "rp-cap-"
RESTORE_JOB_NAME_PREFIX = "rp-res-"
_UUID_LENGTH = 36

SOURCE_MOUNT_PATH = "/source"
DEST_MOUNT_PATH = "/dest"
TARGET_MOUNT_PATH = "/target"
BACKUP_MOUNT_PATH = "/backup"
ARCHIVE_MOUNT_PATH = "/archive"

_ENTRYPOINT = ["python", "-c", "from api.domains.agents.restore_point_job import main; main()"]

_TTL_SECONDS_AFTER_FINISHED = 3600
_CAPTURE_BACKOFF_LIMIT = 1
_RESTORE_BACKOFF_LIMIT = 0

_JOB_RESOURCES = client.V1ResourceRequirements(
    requests={"memory": "128Mi", "cpu": "50m"},
    limits={"memory": "512Mi", "cpu": "500m"},
)


def restore_point_resource_name(restore_point_id: UUID) -> str:
    return f"{PVC_NAME_PREFIX}{restore_point_id}"


def capture_job_name(restore_point_id: UUID) -> str:
    return f"{CAPTURE_JOB_NAME_PREFIX}{restore_point_id}"


def restore_job_name(restore_point_id: UUID) -> str:
    return f"{RESTORE_JOB_NAME_PREFIX}{restore_point_id}-{secrets.token_hex(3)}"


def restore_point_id_from_name(name: str) -> UUID | None:
    """The restore point a resource belongs to, read back out of its own name.

    Reclamation prefers the id label, but resources created before that label
    existed carry only a name. These names are generated here, so parsing one is
    a second exact identifier rather than a guess; anything that does not match
    a prefix this module produces still resolves to None and is left alone.
    """
    for prefix in (PVC_NAME_PREFIX, CAPTURE_JOB_NAME_PREFIX, RESTORE_JOB_NAME_PREFIX):
        if not name.startswith(prefix):
            continue
        try:
            return UUID(name[len(prefix) :][:_UUID_LENGTH])
        except ValueError:
            return None
    return None


def _labels(restore_point_id: UUID, agent_id: UUID, org_id: UUID) -> dict[str, str]:
    return {
        "org-id": str(org_id),
        COMPONENT_LABEL_KEY: COMPONENT_LABEL,
        AGENT_ID_LABEL_KEY: str(agent_id),
        RESTORE_POINT_ID_LABEL_KEY: str(restore_point_id),
    }


def build_restore_point_pvc(
    restore_point_id: UUID,
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    size: str,
    storage_class: str | None = None,
) -> client.V1PersistentVolumeClaim:
    return client.V1PersistentVolumeClaim(
        metadata=client.V1ObjectMeta(
            name=restore_point_resource_name(restore_point_id),
            namespace=namespace,
            labels=_labels(restore_point_id, agent_id, org_id),
        ),
        spec=client.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            storage_class_name=storage_class or None,
            resources=client.V1ResourceRequirements(requests={"storage": size}),
        ),
    )


def _volume(name: str, claim_name: str) -> client.V1Volume:
    return client.V1Volume(
        name=name,
        persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(claim_name=claim_name),
    )


def _build_job(
    *,
    job_name: str,
    restore_point_id: UUID,
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    image: str,
    env: dict[str, str],
    volumes: list[tuple[str, str, str, bool]],
    timeout_seconds: int,
    backoff_limit: int,
    image_pull_secret: str | None,
) -> client.V1Job:
    labels = _labels(restore_point_id, agent_id, org_id)
    return client.V1Job(
        metadata=client.V1ObjectMeta(name=job_name, namespace=namespace, labels=labels),
        spec=client.V1JobSpec(
            backoff_limit=backoff_limit,
            active_deadline_seconds=timeout_seconds,
            ttl_seconds_after_finished=_TTL_SECONDS_AFTER_FINISHED,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=labels),
                spec=client.V1PodSpec(
                    restart_policy="Never",
                    image_pull_secrets=(
                        [client.V1LocalObjectReference(name=image_pull_secret)] if image_pull_secret else None
                    ),
                    containers=[
                        client.V1Container(
                            name="archive",
                            image=image,
                            command=list(_ENTRYPOINT),
                            security_context=client.V1SecurityContext(run_as_user=0),
                            env=[client.V1EnvVar(name=key, value=value) for key, value in env.items()],
                            resources=_JOB_RESOURCES,
                            volume_mounts=[
                                client.V1VolumeMount(name=name, mount_path=mount_path, read_only=read_only)
                                for name, _, mount_path, read_only in volumes
                            ],
                        )
                    ],
                    volumes=[_volume(name, claim_name) for name, claim_name, _, _ in volumes],
                ),
            ),
        ),
    )


def build_capture_job(
    *,
    job_name: str,
    restore_point_id: UUID,
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    image: str,
    runtime: str,
    agent_pvc: str,
    dest_pvc: str,
    timeout_seconds: int,
    image_pull_secret: str | None = None,
) -> client.V1Job:
    return _build_job(
        job_name=job_name,
        restore_point_id=restore_point_id,
        agent_id=agent_id,
        org_id=org_id,
        namespace=namespace,
        image=image,
        env={
            ENV_MODE: MODE_CAPTURE,
            ENV_RUNTIME: runtime,
            ENV_SOURCE: SOURCE_MOUNT_PATH,
            ENV_DEST: DEST_MOUNT_PATH,
        },
        volumes=[
            ("source", agent_pvc, SOURCE_MOUNT_PATH, True),
            ("dest", dest_pvc, DEST_MOUNT_PATH, False),
        ],
        timeout_seconds=timeout_seconds,
        backoff_limit=_CAPTURE_BACKOFF_LIMIT,
        image_pull_secret=image_pull_secret,
    )


def build_restore_job(
    *,
    job_name: str,
    restore_point_id: UUID,
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    image: str,
    runtime: str,
    agent_pvc: str,
    backup_pvc: str,
    archive_pvc: str,
    timeout_seconds: int,
    image_pull_secret: str | None = None,
) -> client.V1Job:
    return _build_job(
        job_name=job_name,
        restore_point_id=restore_point_id,
        agent_id=agent_id,
        org_id=org_id,
        namespace=namespace,
        image=image,
        env={
            ENV_MODE: MODE_RESTORE,
            ENV_RUNTIME: runtime,
            ENV_TARGET: TARGET_MOUNT_PATH,
            ENV_BACKUP: BACKUP_MOUNT_PATH,
            ENV_ARCHIVE: ARCHIVE_MOUNT_PATH,
        },
        volumes=[
            ("target", agent_pvc, TARGET_MOUNT_PATH, False),
            ("backup", backup_pvc, BACKUP_MOUNT_PATH, False),
            ("archive", archive_pvc, ARCHIVE_MOUNT_PATH, True),
        ],
        timeout_seconds=timeout_seconds,
        backoff_limit=_RESTORE_BACKOFF_LIMIT,
        image_pull_secret=image_pull_secret,
    )
