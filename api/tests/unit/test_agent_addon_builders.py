"""How approved Agent Add-ons reach the pod.

The contract under test:

- `install-addons` runs only for an Agent with approved add-ons, after `fix-pvc-owner` and
  before the agent container, on the runtime image, as the runtime's non-root user, with the
  Agent Size's resources;
- it sees nothing but the add-ons volume and its own plan: no Secret, no LiteLLM key, no
  integration environment, not the Agent's main ConfigMap;
- the agent container mounts the add-ons volume read-only and is told where to find them;
- the install hash moves with the runtime image and the approved set, and the set's own digest
  ignores the "why";
- the Agent's instructions name each add-on with its kind and why.
"""

import json
from uuid import UUID

import pytest
from hamcrest import (
    assert_that,
    contains_exactly,
    contains_string,
    empty,
    equal_to,
    has_entries,
    has_item,
    has_items,
    is_,
    is_not,
    none,
    not_none,
)
from kubernetes import client

from api.domains.agent_addons.models import AgentAddonKind, ApprovedAddon, addons_set_digest
from api.domains.agents.builders import addons as addons_module
from api.domains.agents.builders import build_deployment, build_hermes_deployment, container_resources
from api.domains.agents.builders.addons import (
    ADDONS_DIR,
    ADDONS_PVC_SIZE,
    HERMES_RUNTIME_UID,
    INSTALL_ADDONS_CONTAINER,
    INSTALL_ADDONS_PY,
    OPENCLAW_RUNTIME_UID,
    addons_install_hash,
    build_addons_config_map,
    build_addons_policy_md,
    build_addons_pvc,
)

_AGENT = UUID("01a1795e-0cc7-72ff-897d-4f2780e7b5b1")
_ORG = UUID("01a1795e-0cc7-72ff-897d-4f2780e7b5b2")
_NS = "agent-farm"
_IMAGE = "registry.example.com/hermes-base:0.2.10"
_RESOURCES = container_resources(
    cpu_request_millicores=100,
    cpu_limit_millicores=1000,
    memory_request_bytes=640 * 1024**2,
    memory_limit_bytes=2 * 1024**3,
)

_HUMANIZE = ApprovedAddon(
    UUID("01a1795e-0cc7-72ff-897d-4f2780e7b5c1"),
    AgentAddonKind.PIP,
    "humanize",
    {"version": "1.2.0"},
    "Formats numbers and dates in reports.",
)
_TOOL = ApprovedAddon(
    UUID("01a1795e-0cc7-72ff-897d-4f2780e7b5c2"),
    AgentAddonKind.BINARY,
    "drawtool",
    {"url": "https://example.com/drawtool", "sha256": "a" * 64},
    "Converts documents to PDF.",
)


def _hermes(addons: bool):
    return build_hermes_deployment(_AGENT, _ORG, _NS, _IMAGE, resources=_RESOURCES, addons=addons)


def _openclaw(addons: bool):
    return build_deployment(_AGENT, _ORG, _NS, _IMAGE, resources=_RESOURCES, addons=addons)


_RUNTIMES = pytest.mark.parametrize(
    ("build", "uid"),
    [(_hermes, HERMES_RUNTIME_UID), (_openclaw, OPENCLAW_RUNTIME_UID)],
    ids=["hermes", "openclaw"],
)


def _pod(deployment: client.V1Deployment) -> client.V1PodSpec:
    return deployment.spec.template.spec


def _install(deployment: client.V1Deployment) -> client.V1Container | None:
    return next((c for c in _pod(deployment).init_containers if c.name == INSTALL_ADDONS_CONTAINER), None)


def _agent(deployment: client.V1Deployment) -> client.V1Container:
    return next(c for c in _pod(deployment).containers if c.name == "agent")


@_RUNTIMES
def test_an_agent_without_add_ons_has_no_install_step_volume_or_environment(build, uid) -> None:
    deployment = build(False)

    assert_that([c.name for c in _pod(deployment).init_containers], contains_exactly("fix-pvc-owner"))
    assert_that([v.name for v in _pod(deployment).volumes], is_not(has_item("addons")))
    assert_that([m.mount_path for m in _agent(deployment).volume_mounts], is_not(has_item(ADDONS_DIR)))
    assert_that([e.name for e in _agent(deployment).env or []], is_not(has_item("PYTHONPATH")))


@_RUNTIMES
def test_install_addons_runs_between_the_owner_fix_and_the_agent(build, uid) -> None:
    deployment = build(True)

    assert_that(
        [c.name for c in _pod(deployment).init_containers], contains_exactly("fix-pvc-owner", INSTALL_ADDONS_CONTAINER)
    )


@_RUNTIMES
def test_install_addons_uses_the_runtime_image_user_and_the_agents_size(build, uid) -> None:
    install = _install(build(True))

    assert_that(install, is_(not_none()))
    assert install is not None
    assert_that(install.image, equal_to(_IMAGE))
    assert_that(install.security_context.run_as_user, equal_to(uid))
    assert_that(install.security_context.run_as_non_root, is_(True))
    assert_that(install.security_context.allow_privilege_escalation, is_(False))
    assert_that(install.resources, equal_to(_RESOURCES))
    assert_that(install.command[:3], contains_exactly("timeout", "--kill-after=10", "600"))


@_RUNTIMES
def test_install_addons_sees_only_the_add_ons_volume_and_its_plan(build, uid) -> None:
    deployment = build(True)
    install = _install(deployment)
    assert install is not None

    with_mounts = {m.name: m for m in install.volume_mounts}
    assert_that(set(with_mounts), equal_to({"addons", "addons-config"}))
    assert_that(with_mounts["addons"].mount_path, equal_to(ADDONS_DIR))
    assert_that(with_mounts["addons"].read_only, is_not(True))
    assert_that(with_mounts["addons-config"].read_only, is_(True))

    volumes = {v.name: v for v in _pod(deployment).volumes}
    assert_that(volumes["addons"].persistent_volume_claim.claim_name, equal_to(f"agent-{_AGENT}-addons"))
    # Its own ConfigMap, not the Agent's, which carries per-start credentials.
    assert_that(volumes["addons-config"].config_map.name, equal_to(f"agent-{_AGENT}-addons"))
    assert_that(volumes["config"].config_map.name, equal_to(f"agent-{_AGENT}"))


@_RUNTIMES
def test_install_addons_gets_no_secret_key_or_integration_environment(build, uid) -> None:
    install = _install(build(True))
    assert install is not None

    assert_that(install.env_from, is_(none()))
    assert_that([e.name for e in install.env], contains_exactly("ADDONS_DIR"))
    assert_that([e.value_from for e in install.env], contains_exactly(none()))


@_RUNTIMES
def test_the_agent_container_mounts_its_add_ons_read_only(build, uid) -> None:
    agent = _agent(build(True))

    mount = next(m for m in agent.volume_mounts if m.name == "addons")
    assert_that(mount.mount_path, equal_to(ADDONS_DIR))
    assert_that(mount.read_only, is_(True))


@_RUNTIMES
def test_the_agent_container_is_told_where_its_add_ons_are(build, uid) -> None:
    env = {e.name: e.value for e in _agent(build(True)).env}

    assert_that(
        env,
        has_entries(
            AGENTBARN_ADDONS_PATH=f"{ADDONS_DIR}/bin:{ADDONS_DIR}/node/bin",
            PYTHONPATH=f"{ADDONS_DIR}/python",
            NODE_PATH=f"{ADDONS_DIR}/node/lib/node_modules",
        ),
    )


def test_hermes_keeps_its_working_directory_settings_beside_the_add_ons() -> None:
    env = [e.name for e in _agent(_hermes(True)).env]

    assert_that(env, has_items("TERMINAL_CWD", "MESSAGING_CWD", "PYTHONPATH"))


@_RUNTIMES
def test_the_owner_fix_hands_the_add_ons_volume_to_the_runtime_user(build, uid) -> None:
    fix = _pod(build(True)).init_containers[0]

    assert_that(" ".join(fix.command), contains_string(ADDONS_DIR))
    assert_that([m.mount_path for m in fix.volume_mounts], has_item(ADDONS_DIR))


def test_without_add_ons_the_owner_fix_is_what_it_always_was() -> None:
    assert_that(
        _pod(_hermes(False)).init_containers[0].command,
        contains_exactly("sh", "-c", "mkdir -p /opt/data/workspace && chown -R hermes:hermes /opt/data"),
    )
    assert_that(
        _pod(_openclaw(False)).init_containers[0].command,
        contains_exactly("chown", "1000:1000", "/home/node/.openclaw"),
    )


def test_the_add_ons_volume_is_its_own_two_gibibyte_claim() -> None:
    pvc = build_addons_pvc(_AGENT, _ORG, _NS, "local-path")

    assert_that(pvc.metadata.name, equal_to(f"agent-{_AGENT}-addons"))
    assert_that(pvc.spec.resources.requests, equal_to({"storage": ADDONS_PVC_SIZE}))
    assert_that(ADDONS_PVC_SIZE, equal_to("2Gi"))
    assert_that(pvc.spec.access_modes, contains_exactly("ReadWriteOnce"))


def test_the_plan_holds_the_script_and_the_approved_steps_in_order() -> None:
    config_map = build_addons_config_map(_AGENT, _ORG, _NS, image=_IMAGE, addons=[_HUMANIZE, _TOOL])
    plan = json.loads(config_map.data["addons.json"])

    assert_that(config_map.data["install-addons.py"], equal_to(INSTALL_ADDONS_PY))
    assert_that(plan["hash"], equal_to(addons_install_hash(_IMAGE, [_HUMANIZE, _TOOL])))
    assert_that(plan["timeout_seconds"], equal_to(600))
    assert_that(
        plan["addons"],
        contains_exactly(
            {"id": str(_HUMANIZE.id), "kind": "pip", "name": "humanize", "version": "1.2.0"},
            {"id": str(_TOOL.id), "kind": "binary", "name": "drawtool", **_TOOL.spec},
        ),
    )


def test_the_install_hash_includes_the_runtime_image() -> None:
    assert_that(
        addons_install_hash("hermes-base:0.2.10", [_HUMANIZE]),
        is_not(equal_to(addons_install_hash("hermes-base:0.2.11", [_HUMANIZE]))),
    )


def test_the_install_hash_includes_the_install_script(monkeypatch) -> None:
    before = addons_install_hash(_IMAGE, [_HUMANIZE])

    monkeypatch.setattr(addons_module, "INSTALL_ADDONS_PY", INSTALL_ADDONS_PY + "\n# a new installer\n")

    assert_that(addons_install_hash(_IMAGE, [_HUMANIZE]), is_not(equal_to(before)))


def test_the_install_hash_moves_with_the_approved_set_and_its_order() -> None:
    one = addons_install_hash(_IMAGE, [_HUMANIZE])

    assert_that(addons_install_hash(_IMAGE, [_HUMANIZE, _TOOL]), is_not(equal_to(one)))
    assert_that(
        addons_install_hash(_IMAGE, [_TOOL, _HUMANIZE]),
        is_not(equal_to(addons_install_hash(_IMAGE, [_HUMANIZE, _TOOL]))),
    )


def test_the_set_digest_is_none_without_add_ons_and_ignores_the_why() -> None:
    reworded = _HUMANIZE._replace(reason="Something else entirely.")

    assert_that(addons_set_digest([]), is_(none()))
    assert_that(addons_set_digest([reworded]), equal_to(addons_set_digest([_HUMANIZE])))
    assert_that(
        addons_set_digest([_HUMANIZE._replace(spec={"version": "1.3.0"})]),
        is_not(equal_to(addons_set_digest([_HUMANIZE]))),
    )


def test_the_instructions_name_each_add_on_its_kind_and_why() -> None:
    policy = build_addons_policy_md([_HUMANIZE, _TOOL])

    assert_that(policy, contains_string("## Add-ons"))
    assert_that(policy, contains_string("**humanize** (Python package humanize==1.2.0)"))
    assert_that(policy, contains_string("Why: Formats numbers and dates in reports."))
    assert_that(policy, contains_string("**drawtool** (binary drawtool from https://example.com/drawtool)"))
    assert_that(policy, contains_string("read-only"))


def test_no_add_ons_add_no_instructions() -> None:
    assert_that(build_addons_policy_md([]), is_(empty()))
