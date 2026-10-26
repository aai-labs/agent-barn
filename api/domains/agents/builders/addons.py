"""How approved Agent Add-ons reach the pod.

The `install-addons` init container installs them into the Agent's own add-ons volume
(`agent-<id>-addons`, mounted at /opt/addons), and the agent container mounts that volume
read-only. The install container gets the runtime image, the runtime's own non-root user and
the Agent Size's resources, and nothing else: no Secret, no LiteLLM key, no integration
environment, and not the Agent's main ConfigMap, which carries per-start credentials. Its only
inputs are the add-ons volume and a ConfigMap of its own that holds the install script and
the approved steps. See docs/features/agent-addons.md.
"""

import hashlib
import json
from pathlib import Path
from uuid import UUID

from kubernetes import client

from api.domains.agent_addons.models import AgentAddonKind, ApprovedAddon, addon_summary

from .common import _labels, _resource_name

ADDONS_DIR = "/opt/addons"
ADDONS_CONFIG_DIR = "/opt/agentbarn-addons"
ADDONS_PVC_SIZE = "2Gi"
# The whole install, every add-on together; the script stops itself a little sooner.
ADDONS_INSTALL_TIMEOUT_SECONDS = 600
INSTALL_ADDONS_CONTAINER = "install-addons"

# The runtime images' own non-root users. Numeric, because `runAsNonRoot` can only verify a
# numeric user, and both images name theirs (hermes, node). The runtime contract tests check
# these still match the images.
HERMES_RUNTIME_UID = 10000
OPENCLAW_RUNTIME_UID = 1000

INSTALL_ADDONS_PY: str = (Path(__file__).parent.parent / "scripts" / "install-addons.py").read_text()

# Where each kind lands, for the agent container's environment.
ADDONS_PATH = f"{ADDONS_DIR}/bin:{ADDONS_DIR}/node/bin"
ADDONS_PYTHONPATH = f"{ADDONS_DIR}/python"
ADDONS_NODE_PATH = f"{ADDONS_DIR}/node/lib/node_modules"


def addons_resource_name(agent_id: UUID) -> str:
    return f"{_resource_name(agent_id)}-addons"


def addon_install_steps(addons: list[ApprovedAddon]) -> list[dict[str, str]]:
    """The approved add-ons as the install script reads them, in install order."""
    return [{"id": str(a.id), "kind": a.kind.value, "name": a.name, **a.spec} for a in addons]


def addons_install_hash(image: str, addons: list[ApprovedAddon]) -> str:
    """What the install script compares with the marker it left last time.

    The runtime image is part of it, so a new image reinstalls everything against its own
    Python and Node, as a newly approved or revoked add-on does. So is the install script, so
    a change to how add-ons are installed reaches every volume at its next start.
    """
    canonical = {
        "image": image,
        "addons": addon_install_steps(addons),
        "script": hashlib.sha256(INSTALL_ADDONS_PY.encode()).hexdigest(),
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_addons_pvc(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    storage_class: str | None = None,
) -> client.V1PersistentVolumeClaim:
    """The Agent's add-ons volume: apart from its data volume, which the Agent can write
    through HOME, so the agent can neither change what was installed nor spend its own 1Gi on
    it, and restore points never carry it."""
    return client.V1PersistentVolumeClaim(
        metadata=client.V1ObjectMeta(
            name=addons_resource_name(agent_id),
            namespace=namespace,
            labels={**_labels(agent_id, org_id), "agentbarn.io/volume": "addons"},
        ),
        spec=client.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            storage_class_name=storage_class or None,
            resources=client.V1ResourceRequirements(requests={"storage": ADDONS_PVC_SIZE}),
        ),
    )


def build_addons_config_map(
    agent_id: UUID,
    org_id: UUID,
    namespace: str,
    *,
    image: str,
    addons: list[ApprovedAddon],
) -> client.V1ConfigMap:
    """The install container's only configuration: the script and the approved steps."""
    plan = {
        "hash": addons_install_hash(image, addons),
        "timeout_seconds": ADDONS_INSTALL_TIMEOUT_SECONDS,
        "addons": addon_install_steps(addons),
    }
    return client.V1ConfigMap(
        metadata=client.V1ObjectMeta(
            name=addons_resource_name(agent_id),
            namespace=namespace,
            labels=_labels(agent_id, org_id),
        ),
        data={"install-addons.py": INSTALL_ADDONS_PY, "addons.json": json.dumps(plan, indent=2, sort_keys=True)},
    )


def install_addons_container(
    agent_id: UUID,
    image: str,
    *,
    run_as_user: int,
    resources: client.V1ResourceRequirements,
) -> client.V1Container:
    """The `install-addons` init container. Deliberately given no env_from, no Secret and no
    mount but its own two: an add-on's install code runs here, and whatever it is, it must
    find no credential to take."""
    return client.V1Container(
        name=INSTALL_ADDONS_CONTAINER,
        image=image,
        # `timeout` is the backstop; the script keeps its own, shorter deadline so it can name
        # the add-on that ran out of time.
        command=[
            "timeout",
            "--kill-after=10",
            str(ADDONS_INSTALL_TIMEOUT_SECONDS),
            "python3",
            f"{ADDONS_CONFIG_DIR}/install-addons.py",
        ],
        env=[client.V1EnvVar(name="ADDONS_DIR", value=ADDONS_DIR)],
        resources=resources,
        security_context=client.V1SecurityContext(
            run_as_user=run_as_user,
            run_as_group=run_as_user,
            run_as_non_root=True,
            allow_privilege_escalation=False,
        ),
        volume_mounts=[
            client.V1VolumeMount(name="addons", mount_path=ADDONS_DIR),
            client.V1VolumeMount(name="addons-config", mount_path=ADDONS_CONFIG_DIR, read_only=True),
        ],
    )


def addons_volumes(agent_id: UUID) -> list[client.V1Volume]:
    name = addons_resource_name(agent_id)
    return [
        client.V1Volume(
            name="addons",
            persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(claim_name=name),
        ),
        client.V1Volume(name="addons-config", config_map=client.V1ConfigMapVolumeSource(name=name)),
    ]


def addons_agent_mount() -> client.V1VolumeMount:
    """The add-ons volume in the agent container: read-only, so the Agent can use what was
    installed and cannot change it."""
    return client.V1VolumeMount(name="addons", mount_path=ADDONS_DIR, read_only=True)


def addons_agent_env() -> list[client.V1EnvVar]:
    """Where the agent finds its add-ons. PATH cannot be set here without replacing the
    image's own, so start.sh prepends `AGENTBARN_ADDONS_PATH` to it."""
    return [
        client.V1EnvVar(name="AGENTBARN_ADDONS_PATH", value=ADDONS_PATH),
        client.V1EnvVar(name="PYTHONPATH", value=ADDONS_PYTHONPATH),
        client.V1EnvVar(name="NODE_PATH", value=ADDONS_NODE_PATH),
    ]


def _addon_line(addon: ApprovedAddon) -> str:
    where = {
        AgentAddonKind.PIP: (
            f"import it from `python3` (installed in `{ADDONS_PYTHONPATH}`; its import name can differ from "
            "the package name)"
        ),
        AgentAddonKind.NPM: "its commands are on PATH and `node` can `require()` it",
        AgentAddonKind.GIT: f"checked out in `{ADDONS_DIR}/src/{addon.name}`",
        AgentAddonKind.BINARY: f"on PATH as `{addon.name}` (`{ADDONS_DIR}/bin/{addon.name}`)",
        AgentAddonKind.COMMAND: f"set up by a reviewed install command under `{ADDONS_DIR}`",
    }[addon.kind]
    why = " ".join(addon.reason.split())
    return f"- **{addon.name}** ({addon_summary(addon.kind, addon.name, addon.spec)}): {where}. Why: {why}\n"


def build_addons_policy_md(addons: list[ApprovedAddon]) -> str:
    """The AGENTS.md block that tells the model which add-ons it has. Empty without any."""
    if not addons:
        return ""
    return (
        "\n\n## Add-ons\n\n"
        "These add-ons were requested by your organization and approved by the platform. They are "
        f"installed in `{ADDONS_DIR}`, which is read-only: use them, but do not try to install, upgrade "
        "or remove them, and do not install other packages in their place. If you need a different "
        "version or another tool, tell the person you are working with that an Organization Owner or "
        "Admin can request it as an add-on.\n\n" + "".join(_addon_line(addon) for addon in addons)
    )
