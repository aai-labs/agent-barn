from uuid import UUID

from hamcrest import assert_that, empty, equal_to, has_entries, is_not, none

from api.domains.agents.builders.restore_point import (
    ARCHIVE_MOUNT_PATH,
    BACKUP_MOUNT_PATH,
    DEST_MOUNT_PATH,
    SOURCE_MOUNT_PATH,
    TARGET_MOUNT_PATH,
    build_capture_job,
    build_restore_job,
    build_restore_point_pvc,
    restore_point_resource_name,
)
from api.domains.agents.restore_point_job import ARCHIVE_NAME, capture, main

_RESTORE_POINT_ID = UUID("11111111-1111-1111-1111-111111111111")
_AGENT_ID = UUID("22222222-2222-2222-2222-222222222222")
_ORG_ID = UUID("33333333-3333-3333-3333-333333333333")
_NS = "agent-farm"
_IMAGE = "registry.example.com/agentbarn-api:1.2.3"
_AGENT_PVC = "agent-22222222-2222-2222-2222-222222222222"
_JOB = "rp-cap-11111111-1111-1111-1111-111111111111"


def _env(job) -> dict[str, str]:
    container = job.spec.template.spec.containers[0]
    return {e.name: e.value for e in container.env}


def _mounts(job) -> dict[str, tuple[str, bool]]:
    container = job.spec.template.spec.containers[0]
    claims = {v.name: v.persistent_volume_claim.claim_name for v in job.spec.template.spec.volumes}
    return {m.mount_path: (claims[m.name], bool(m.read_only)) for m in container.volume_mounts}


def _capture_job(**overrides):
    kwargs = {
        "job_name": _JOB,
        "agent_id": _AGENT_ID,
        "org_id": _ORG_ID,
        "namespace": _NS,
        "image": _IMAGE,
        "runtime": "hermes",
        "agent_pvc": _AGENT_PVC,
        "dest_pvc": restore_point_resource_name(_RESTORE_POINT_ID),
        "timeout_seconds": 900,
    }
    kwargs.update(overrides)
    return build_capture_job(**kwargs)


def _restore_job(**overrides):
    kwargs = {
        "job_name": "rp-res-11111111-1111-1111-1111-111111111111-abc123",
        "agent_id": _AGENT_ID,
        "org_id": _ORG_ID,
        "namespace": _NS,
        "image": _IMAGE,
        "runtime": "openclaw",
        "agent_pvc": _AGENT_PVC,
        "backup_pvc": "restore-point-44444444-4444-4444-4444-444444444444",
        "archive_pvc": restore_point_resource_name(_RESTORE_POINT_ID),
        "timeout_seconds": 1800,
    }
    kwargs.update(overrides)
    return build_restore_job(**kwargs)


def test_restore_point_pvc_is_named_and_labelled_for_reclamation():
    pvc = build_restore_point_pvc(_RESTORE_POINT_ID, _AGENT_ID, _ORG_ID, _NS, "1Gi")

    assert_that(pvc.metadata.name, equal_to(f"restore-point-{_RESTORE_POINT_ID}"))
    assert_that(
        pvc.metadata.labels,
        has_entries(
            {
                "agentbarn.io/component": "restore-point",
                "agentbarn.io/agent-id": str(_AGENT_ID),
                "org-id": str(_ORG_ID),
            }
        ),
    )


def test_restore_point_pvc_requests_the_configured_size_as_read_write_once():
    pvc = build_restore_point_pvc(_RESTORE_POINT_ID, _AGENT_ID, _ORG_ID, _NS, "5Gi")

    assert_that(pvc.spec.access_modes, equal_to(["ReadWriteOnce"]))
    assert_that(pvc.spec.resources.requests["storage"], equal_to("5Gi"))


def test_restore_point_pvc_omits_storage_class_when_not_configured():
    assert_that(
        build_restore_point_pvc(_RESTORE_POINT_ID, _AGENT_ID, _ORG_ID, _NS, "1Gi").spec.storage_class_name, none()
    )
    assert_that(
        build_restore_point_pvc(_RESTORE_POINT_ID, _AGENT_ID, _ORG_ID, _NS, "1Gi", "").spec.storage_class_name, none()
    )
    assert_that(
        build_restore_point_pvc(
            _RESTORE_POINT_ID, _AGENT_ID, _ORG_ID, _NS, "1Gi", "local-path"
        ).spec.storage_class_name,
        equal_to("local-path"),
    )


def test_capture_job_runs_the_api_image_entrypoint_as_root():
    job = _capture_job()
    container = job.spec.template.spec.containers[0]

    assert_that(job.metadata.name, equal_to(_JOB))
    assert_that(container.image, equal_to(_IMAGE))
    assert_that(container.security_context.run_as_user, equal_to(0))
    assert_that(
        container.command,
        equal_to(["python", "-c", "from api.domains.agents.restore_point_job import main; main()"]),
    )


def test_capture_job_does_not_restart_or_retry_indefinitely():
    job = _capture_job()

    assert_that(job.spec.template.spec.restart_policy, equal_to("Never"))
    assert_that(job.spec.backoff_limit, equal_to(1))
    assert_that(job.spec.active_deadline_seconds, equal_to(900))
    assert_that(job.spec.ttl_seconds_after_finished, is_not(none()))


def test_capture_job_mounts_the_agent_volume_read_only():
    mounts = _mounts(_capture_job())

    assert_that(mounts[SOURCE_MOUNT_PATH], equal_to((_AGENT_PVC, True)))
    assert_that(mounts[DEST_MOUNT_PATH], equal_to((f"restore-point-{_RESTORE_POINT_ID}", False)))


def test_capture_job_passes_the_runtime_and_paths_to_the_entrypoint():
    env = _env(_capture_job())

    assert_that(
        env,
        has_entries(
            {
                "RESTORE_POINT_MODE": "capture",
                "RESTORE_POINT_RUNTIME": "hermes",
                "RESTORE_POINT_SOURCE": SOURCE_MOUNT_PATH,
                "RESTORE_POINT_DEST": DEST_MOUNT_PATH,
            }
        ),
    )


def test_restore_job_mounts_the_target_writable_and_the_archive_read_only():
    mounts = _mounts(_restore_job())

    assert_that(mounts[TARGET_MOUNT_PATH], equal_to((_AGENT_PVC, False)))
    assert_that(mounts[BACKUP_MOUNT_PATH][1], equal_to(False))
    assert_that(mounts[ARCHIVE_MOUNT_PATH], equal_to((f"restore-point-{_RESTORE_POINT_ID}", True)))


def test_restore_job_passes_all_three_paths_to_the_entrypoint():
    env = _env(_restore_job())

    assert_that(
        env,
        has_entries(
            {
                "RESTORE_POINT_MODE": "restore",
                "RESTORE_POINT_RUNTIME": "openclaw",
                "RESTORE_POINT_TARGET": TARGET_MOUNT_PATH,
                "RESTORE_POINT_BACKUP": BACKUP_MOUNT_PATH,
                "RESTORE_POINT_ARCHIVE": ARCHIVE_MOUNT_PATH,
            }
        ),
    )


def test_jobs_carry_the_reclamation_labels():
    for job in (_capture_job(), _restore_job()):
        assert_that(
            job.metadata.labels,
            has_entries(
                {
                    "agentbarn.io/component": "restore-point",
                    "agentbarn.io/agent-id": str(_AGENT_ID),
                }
            ),
        )


def test_image_pull_secret_is_applied_only_when_configured():
    assert_that(_capture_job().spec.template.spec.image_pull_secrets, none())
    with_secret = _capture_job(image_pull_secret="regcred")
    assert_that([s.name for s in with_secret.spec.template.spec.image_pull_secrets], equal_to(["regcred"]))


def test_jobs_declare_bounded_resources():
    container = _capture_job().spec.template.spec.containers[0]

    assert_that(container.resources.requests, is_not(empty()))
    assert_that(container.resources.limits, is_not(empty()))


def _apply_job_env(monkeypatch, job, path_overrides: dict[str, object]) -> None:
    for name, value in _env(job).items():
        monkeypatch.setenv(name, str(path_overrides.get(value, value)))


def test_capture_job_env_drives_the_entrypoint(tmp_path, monkeypatch):
    source, dest = tmp_path / "source", tmp_path / "dest"
    source.mkdir()
    dest.mkdir()
    (source / "memories").mkdir()
    (source / "memories" / "USER.md").write_text("profile")

    _apply_job_env(monkeypatch, _capture_job(), {SOURCE_MOUNT_PATH: source, DEST_MOUNT_PATH: dest})
    main()

    assert_that((dest / ARCHIVE_NAME).exists(), equal_to(True))


def test_restore_job_env_drives_the_entrypoint(tmp_path, monkeypatch):
    seed, archive_dir = tmp_path / "seed", tmp_path / "archive"
    seed.mkdir()
    archive_dir.mkdir()
    (seed / "memories").mkdir()
    (seed / "memories" / "USER.md").write_text("captured profile")
    capture(seed, archive_dir, "hermes")

    target, backup = tmp_path / "target", tmp_path / "backup"
    target.mkdir()
    backup.mkdir()
    (target / "stale.md").write_text("replaced")

    _apply_job_env(
        monkeypatch,
        _restore_job(),
        {TARGET_MOUNT_PATH: target, BACKUP_MOUNT_PATH: backup, ARCHIVE_MOUNT_PATH: archive_dir},
    )
    main()

    assert_that((target / "memories" / "USER.md").read_text(), equal_to("captured profile"))
    assert_that((target / "stale.md").exists(), equal_to(False))
    assert_that((backup / ARCHIVE_NAME).exists(), equal_to(True))
