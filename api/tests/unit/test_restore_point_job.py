import gzip
import io
import re
import tarfile
from pathlib import Path
from uuid import uuid4

import pytest
from hamcrest import assert_that, calling, empty, equal_to, greater_than, has_item, is_not, raises

from api.domains.agents.builders.openclaw import build_config_map
from api.domains.agents.restore_point_job import (
    ARCHIVE_NAME,
    ENV_ARCHIVE,
    ENV_BACKUP,
    ENV_MODE,
    ENV_RUNTIME,
    ENV_TARGET,
    EXIT_BACKUP_FAILED,
    EXIT_RESTORE_FAILED,
    HERMES_EXCLUDED,
    MANIFEST_NAME,
    MODE_RESTORE,
    OPENCLAW_EXCLUDED,
    ArchiveValidationError,
    capture,
    is_excluded,
    main,
    restore,
    validate_archive,
)

_HERMES = "hermes"
_OPENCLAW = "openclaw"

_AGENTS_DIR = Path(__file__).resolve().parents[2] / "domains" / "agents"
_HERMES_START = _AGENTS_DIR / "scripts" / "hermes" / "start.sh"
_OPENCLAW_START = _AGENTS_DIR / "scripts" / "openclaw" / "start.sh"
_OPENCLAW_INIT = _AGENTS_DIR / "scripts" / "openclaw" / "init-openclaw.js"
_AAI_CLI_ARTIFACTS = _AGENTS_DIR / "aai_cli_artifacts.py"
_AGENT_SERVICE = _AGENTS_DIR / "service.py"

_HERMES_WORKSPACE_COPY_LOOP = re.compile(r"^for f in (?P<files>[^;]+); do$", re.MULTILINE)

_EXCLUSION_EVIDENCE = {
    _HERMES: {
        ".config/aai-cli": (_AAI_CLI_ARTIFACTS, "/.config/aai-cli"),
        ".env": (_HERMES_START, "rm -f /opt/data/.env"),
        "SOUL.md": (_HERMES_START, "cp /app/config/SOUL.md /opt/data/SOUL.md"),
        "config.yaml": (_HERMES_START, "/opt/data/config.yaml"),
        "plugins": (_HERMES_START, "/opt/data/plugins/"),
        "agentbarn-messages.sqlite3": (_HERMES_START, "/opt/data/agentbarn-messages.sqlite3"),
        "workspace/skills": (_HERMES_START, "rm -rf /workspace/skills"),
    },
    _OPENCLAW: {
        "aai-cli": (_AGENT_SERVICE, '"/home/node/.openclaw/aai-cli"'),
        "local-plugins": (_OPENCLAW_START, "/home/node/.openclaw/local-plugins/"),
        "npm": (_OPENCLAW_START, "/home/node/.openclaw/npm/projects/"),
        "agentbarn-messages.sqlite3": (_OPENCLAW_START, "/home/node/.openclaw/agentbarn-messages.sqlite3"),
        "openclaw.json": (_OPENCLAW_INIT, "'openclaw.json'"),
        "workspace/skills": (_OPENCLAW_INIT, "path.join(WORKSPACE_DIR, 'skills')"),
    },
}


def _write(root: Path, rel: str, content: str = "x") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _hermes_volume(root: Path) -> None:
    _write(root, ".config/aai-cli/aai-secrets.enc.json", "SECRET")
    _write(root, ".config/aai-cli/key", "KEY")
    _write(root, ".config/aai-cli/config.toml")
    _write(root, ".env", "OPENAI_API_KEY=sk-live")
    _write(root, "SOUL.md")
    _write(root, "config.yaml")
    _write(root, "plugins/telemetry-push/__init__.py")
    _write(root, "agentbarn-messages.sqlite3")
    _write(root, "workspace/skills/jira/SKILL.md")
    _write(root, "workspace/AGENTS.md")
    _write(root, "workspace/IDENTITY.md")
    _write(root, "memories/USER.md", "learned profile")
    _write(root, "workspace/notes.md", "agent work")


def _openclaw_volume(root: Path) -> None:
    _write(root, "aai-cli/aai-secrets.enc.json", "SECRET")
    _write(root, "aai-cli/key", "KEY")
    _write(root, "aai-cli/microsoft.sharepoint_refresh_token.sign-in")
    _write(root, "local-plugins/telemetry-push/index.js")
    _write(root, "npm/projects/openclaw-plugin/package.json")
    _write(root, "openclaw.json")
    _write(root, "agentbarn-messages.sqlite3")
    _write(root, "workspace/skills/jira/SKILL.md")
    _write(root, "workspace/AGENTS.md")
    _write(root, "workspace/USER.md", "learned profile")
    _write(root, "workspace/notes.md", "agent work")


def _members(dest: Path) -> list[str]:
    with tarfile.open(dest / ARCHIVE_NAME, "r:gz") as tar:
        return [m.name for m in tar.getmembers() if m.isfile()]


def test_hermes_capture_excludes_the_aai_cli_credential_store(tmp_path):
    source, dest = tmp_path / "src", tmp_path / "dst"
    source.mkdir()
    dest.mkdir()
    _hermes_volume(source)

    capture(source, dest, _HERMES)

    names = _members(dest)
    assert_that([n for n in names if n.startswith(".config/aai-cli")], empty())


def test_openclaw_capture_excludes_the_aai_cli_credential_store(tmp_path):
    # OpenClaw keeps its aai-cli store on the volume (Hermes keeps its own under .config),
    # so an archive would otherwise hold every integration token and the key to read them.
    source, dest = tmp_path / "src", tmp_path / "dst"
    source.mkdir()
    dest.mkdir()
    _openclaw_volume(source)

    capture(source, dest, _OPENCLAW)

    names = _members(dest)
    assert_that([n for n in names if n.startswith("aai-cli")], empty())


def test_hermes_capture_excludes_state_the_start_script_regenerates(tmp_path):
    source, dest = tmp_path / "src", tmp_path / "dst"
    source.mkdir()
    dest.mkdir()
    _hermes_volume(source)

    capture(source, dest, _HERMES)

    names = _members(dest)
    for excluded in (
        ".env",
        "SOUL.md",
        "config.yaml",
        "plugins/telemetry-push/__init__.py",
        "workspace/skills/jira/SKILL.md",
        "workspace/AGENTS.md",
        "workspace/IDENTITY.md",
        "agentbarn-messages.sqlite3",
    ):
        assert_that(names, is_not(has_item(excluded)))


def test_hermes_capture_retains_agent_owned_memories_and_work(tmp_path):
    source, dest = tmp_path / "src", tmp_path / "dst"
    source.mkdir()
    dest.mkdir()
    _hermes_volume(source)

    capture(source, dest, _HERMES)

    names = _members(dest)
    assert_that(names, has_item("memories/USER.md"))
    assert_that(names, has_item("workspace/notes.md"))


def test_openclaw_capture_retains_workspace_user_md_but_drops_regenerated_markdown(tmp_path):
    source, dest = tmp_path / "src", tmp_path / "dst"
    source.mkdir()
    dest.mkdir()
    _openclaw_volume(source)

    capture(source, dest, _OPENCLAW)

    names = _members(dest)
    assert_that(names, has_item("workspace/USER.md"))
    assert_that(names, is_not(has_item("workspace/AGENTS.md")))


def test_openclaw_capture_retains_agent_authored_workspace_markdown(tmp_path):
    source, dest = tmp_path / "src", tmp_path / "dst"
    source.mkdir()
    dest.mkdir()
    _openclaw_volume(source)

    capture(source, dest, _OPENCLAW)

    assert_that(_members(dest), has_item("workspace/notes.md"))


def _workspace_markdown(excluded: tuple[str, ...]) -> set[str]:
    return {path for path in excluded if path.startswith("workspace/") and path.endswith(".md")}


def _openclaw_config_map_markdown() -> set[str]:
    config_map = build_config_map(
        agent_id=uuid4(),
        org_id=uuid4(),
        namespace="agent-farm",
        soul_md="x",
        identity_md="x",
        user_md="x",
        tools_md="x",
        agents_md="x",
        boot_md="x",
        bootstrap_md="x",
        heartbeat_md="x",
        openclaw_config_overlay={"agents": {}},
        aai_cli_config_toml="x",
        aai_cli_setup_sh="x",
        gog_setup_sh="x",
        skills_json="[]",
    )
    return {key for key in config_map.data if key.endswith(".md")}


@pytest.mark.parametrize(
    ("runtime", "excluded"),
    [(_HERMES, HERMES_EXCLUDED), (_OPENCLAW, OPENCLAW_EXCLUDED)],
)
def test_every_non_markdown_exclusion_has_evidence_and_no_evidence_is_stale(runtime, excluded):
    non_markdown = set(excluded) - _workspace_markdown(excluded)

    assert_that(set(_EXCLUSION_EVIDENCE[runtime]), equal_to(non_markdown))


@pytest.mark.parametrize(
    ("runtime", "path", "source", "evidence"),
    [
        (runtime, path, source, evidence)
        for runtime, rows in _EXCLUSION_EVIDENCE.items()
        for path, (source, evidence) in rows.items()
    ],
)
def test_each_exclusion_is_still_written_by_its_runtime(runtime, path, source, evidence):
    assert_that(evidence in source.read_text(encoding="utf-8"), equal_to(True))


def test_hermes_markdown_exclusions_match_the_start_script_copy_loop():
    match = _HERMES_WORKSPACE_COPY_LOOP.search(_HERMES_START.read_text(encoding="utf-8"))
    assert match is not None
    copied = {f"workspace/{name}" for name in match.group("files").split()}

    assert_that(_workspace_markdown(HERMES_EXCLUDED), equal_to(copied))


def test_openclaw_markdown_exclusions_match_what_the_config_map_regenerates():
    regenerated = {f"workspace/{name}" for name in _openclaw_config_map_markdown() - {"USER.md"}}

    assert_that(_workspace_markdown(OPENCLAW_EXCLUDED), equal_to(regenerated))


@pytest.mark.parametrize(("runtime", "path"), [(_HERMES, "memories/USER.md"), (_OPENCLAW, "workspace/USER.md")])
def test_neither_runtime_excludes_its_agent_owned_user_profile(runtime, path):
    assert_that(is_excluded(path, runtime), equal_to(False))


def test_openclaw_capture_excludes_regenerated_state_and_the_message_spool(tmp_path):
    source, dest = tmp_path / "src", tmp_path / "dst"
    source.mkdir()
    dest.mkdir()
    _openclaw_volume(source)

    capture(source, dest, _OPENCLAW)

    names = _members(dest)
    for excluded in (
        "local-plugins/telemetry-push/index.js",
        "npm/projects/openclaw-plugin/package.json",
        "openclaw.json",
        "workspace/skills/jira/SKILL.md",
        "agentbarn-messages.sqlite3",
    ):
        assert_that(names, is_not(has_item(excluded)))


def test_openclaw_capture_excludes_symlinks_that_cannot_be_safely_restored(tmp_path):
    source, dest = tmp_path / "src", tmp_path / "dst"
    source.mkdir()
    dest.mkdir()
    _openclaw_volume(source)
    (source / "workspace" / "runtime-link").symlink_to("/usr/local/lib/node_modules/openclaw")

    capture(source, dest, _OPENCLAW)

    with tarfile.open(dest / ARCHIVE_NAME, "r:gz") as tar:
        assert_that([member.name for member in tar.getmembers()], is_not(has_item("workspace/runtime-link")))
    validate_archive(dest / ARCHIVE_NAME, source)


def test_hermes_capture_keeps_relative_symlinks_inside_the_volume(tmp_path):
    source, dest = tmp_path / "src", tmp_path / "dst"
    source.mkdir()
    dest.mkdir()
    _hermes_volume(source)
    (source / "workspace" / "notes-link.md").symlink_to("notes.md")

    capture(source, dest, _HERMES)

    with tarfile.open(dest / ARCHIVE_NAME, "r:gz") as tar:
        assert_that([member.name for member in tar.getmembers()], has_item("workspace/notes-link.md"))
    validate_archive(dest / ARCHIVE_NAME, source)


def test_capture_writes_a_manifest_with_byte_size_and_file_count(tmp_path):
    source, dest = tmp_path / "src", tmp_path / "dst"
    source.mkdir()
    dest.mkdir()
    _hermes_volume(source)

    manifest = capture(source, dest, _HERMES)

    assert_that(manifest["file_count"], equal_to(len(_members(dest))))
    assert_that(manifest["bytes"], equal_to((dest / ARCHIVE_NAME).stat().st_size))
    assert_that(manifest["bytes"], greater_than(0))
    assert_that((dest / MANIFEST_NAME).exists(), equal_to(True))


def test_a_volume_holding_only_excluded_state_captures_zero_files(tmp_path):
    source, dest = tmp_path / "src", tmp_path / "dst"
    source.mkdir()
    dest.mkdir()
    _write(source, ".env")
    _write(source, "SOUL.md")
    _write(source, ".config/aai-cli/key", "KEY")

    manifest = capture(source, dest, _HERMES)

    assert_that(manifest["file_count"], equal_to(0))
    assert_that((dest / ARCHIVE_NAME).exists(), equal_to(True))


def test_restore_replaces_target_contents_from_the_archive(tmp_path):
    source, archive_dir = tmp_path / "src", tmp_path / "arc"
    source.mkdir()
    archive_dir.mkdir()
    _write(source, "memories/USER.md", "captured profile")
    _write(source, "workspace/notes.md", "captured work")
    capture(source, archive_dir, _HERMES)

    target, backup = tmp_path / "tgt", tmp_path / "bak"
    target.mkdir()
    backup.mkdir()
    _write(target, "workspace/stale.md", "should be gone")

    restore(target, backup, archive_dir, _HERMES)

    assert_that((target / "memories/USER.md").read_text(), equal_to("captured profile"))
    assert_that((target / "workspace/notes.md").read_text(), equal_to("captured work"))
    assert_that((target / "workspace/stale.md").exists(), equal_to(False))


def test_restore_captures_a_pre_restore_backup_before_wiping(tmp_path):
    source, archive_dir = tmp_path / "src", tmp_path / "arc"
    source.mkdir()
    archive_dir.mkdir()
    _write(source, "memories/USER.md", "captured profile")
    capture(source, archive_dir, _HERMES)

    target, backup = tmp_path / "tgt", tmp_path / "bak"
    target.mkdir()
    backup.mkdir()
    _write(target, "workspace/live.md", "live content")

    restore(target, backup, archive_dir, _HERMES)

    assert_that(_members(backup), has_item("workspace/live.md"))


def test_a_corrupt_archive_fails_with_the_target_untouched(tmp_path):
    archive_dir = tmp_path / "arc"
    archive_dir.mkdir()
    (archive_dir / ARCHIVE_NAME).write_bytes(b"not a gzip stream at all")

    target, backup = tmp_path / "tgt", tmp_path / "bak"
    target.mkdir()
    backup.mkdir()
    _write(target, "workspace/live.md", "live content")

    assert_that(
        calling(restore).with_args(target, backup, archive_dir, _HERMES),
        raises(ArchiveValidationError),
    )
    assert_that((target / "workspace/live.md").read_text(), equal_to("live content"))


def test_a_truncated_archive_is_rejected_before_the_wipe(tmp_path):
    source, archive_dir = tmp_path / "src", tmp_path / "arc"
    source.mkdir()
    archive_dir.mkdir()
    _write(source, "workspace/notes.md", "x" * 100_000)
    capture(source, archive_dir, _HERMES)
    archive = archive_dir / ARCHIVE_NAME
    archive.write_bytes(archive.read_bytes()[:-64])

    target, backup = tmp_path / "tgt", tmp_path / "bak"
    target.mkdir()
    backup.mkdir()
    _write(target, "workspace/live.md", "live content")

    assert_that(
        calling(restore).with_args(target, backup, archive_dir, _HERMES),
        raises(ArchiveValidationError),
    )
    assert_that((target / "workspace/live.md").read_text(), equal_to("live content"))


def _hostile_archive(path: Path, build) -> None:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        build(tar)
    path.write_bytes(gzip.compress(raw.getvalue()))


def _add_file(tar, arcname: str, mode: int = 0o644) -> None:
    payload = b"pwned"
    info = tarfile.TarInfo(name=arcname)
    info.size = len(payload)
    info.mode = mode
    tar.addfile(info, io.BytesIO(payload))


def _hostile_target(tmp_path, build):
    archive_dir = tmp_path / "arc"
    archive_dir.mkdir()
    _hostile_archive(archive_dir / ARCHIVE_NAME, build)
    target, backup = tmp_path / "tgt", tmp_path / "bak"
    target.mkdir()
    backup.mkdir()
    _write(target, "workspace/live.md", "irreplaceable")
    return target, backup, archive_dir


def _device_node(tar) -> None:
    info = tarfile.TarInfo(name="dev/bad")
    info.type = tarfile.CHRTYPE
    info.devmajor = 1
    info.devminor = 3
    tar.addfile(info)


def test_parent_directory_traversal_is_rejected_with_the_target_intact(tmp_path):
    target, backup, archive_dir = _hostile_target(tmp_path, lambda t: _add_file(t, "../escape.md"))

    assert_that(
        calling(restore).with_args(target, backup, archive_dir, _HERMES),
        raises(ArchiveValidationError),
    )
    assert_that((tmp_path / "escape.md").exists(), equal_to(False))
    assert_that((target / "workspace/live.md").read_text(), equal_to("irreplaceable"))


def test_device_nodes_are_rejected_with_the_target_intact(tmp_path):
    target, backup, archive_dir = _hostile_target(tmp_path, _device_node)

    assert_that(
        calling(restore).with_args(target, backup, archive_dir, _HERMES),
        raises(ArchiveValidationError),
    )
    assert_that((target / "workspace/live.md").read_text(), equal_to("irreplaceable"))


def test_absolute_paths_are_rejected_with_the_target_intact(tmp_path):
    target, backup, archive_dir = _hostile_target(tmp_path, lambda t: _add_file(t, "/etc/passwd"))

    assert_that(
        calling(restore).with_args(target, backup, archive_dir, _HERMES),
        raises(ArchiveValidationError),
    )
    assert_that((target / "workspace/live.md").read_text(), equal_to("irreplaceable"))


def test_setuid_bits_are_stripped_from_extracted_files(tmp_path):
    target, backup, archive_dir = _hostile_target(tmp_path, lambda t: _add_file(t, "suid.sh", mode=0o4755))

    restore(target, backup, archive_dir, _HERMES)

    mode = (target / "suid.sh").stat().st_mode
    assert_that(mode & 0o4000, equal_to(0))
    assert_that(mode & 0o2000, equal_to(0))


def _restore_env(monkeypatch, target: Path, backup: Path, archive_dir: Path) -> None:
    monkeypatch.setenv(ENV_MODE, MODE_RESTORE)
    monkeypatch.setenv(ENV_RUNTIME, _HERMES)
    monkeypatch.setenv(ENV_TARGET, str(target))
    monkeypatch.setenv(ENV_BACKUP, str(backup))
    monkeypatch.setenv(ENV_ARCHIVE, str(archive_dir))


def test_main_restores_the_archive_onto_the_target(tmp_path, monkeypatch):
    source, archive_dir = tmp_path / "src", tmp_path / "arc"
    source.mkdir()
    archive_dir.mkdir()
    _write(source, "memories/USER.md", "captured profile")
    capture(source, archive_dir, _HERMES)

    target, backup = tmp_path / "tgt", tmp_path / "bak"
    target.mkdir()
    backup.mkdir()
    _write(target, "workspace/stale.md", "should be gone")
    _restore_env(monkeypatch, target, backup, archive_dir)

    main()

    assert_that((target / "memories/USER.md").read_text(), equal_to("captured profile"))
    assert_that((target / "workspace/stale.md").exists(), equal_to(False))
    assert_that(_members(backup), has_item("workspace/stale.md"))


def test_main_reports_a_failed_pre_restore_capture_distinctly(tmp_path, monkeypatch):
    target, backup, archive_dir = tmp_path / "tgt", tmp_path / "missing", tmp_path / "arc"
    target.mkdir()
    archive_dir.mkdir()
    _write(target, "workspace/live.md", "live content")
    _restore_env(monkeypatch, target, backup, archive_dir)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert_that(exc_info.value.code, equal_to(EXIT_BACKUP_FAILED))
    assert_that((target / "workspace/live.md").read_text(), equal_to("live content"))


def test_main_reports_a_failed_extraction_distinctly_and_keeps_the_backup(tmp_path, monkeypatch):
    target, backup, archive_dir = tmp_path / "tgt", tmp_path / "bak", tmp_path / "arc"
    target.mkdir()
    backup.mkdir()
    archive_dir.mkdir()
    _write(target, "workspace/live.md", "live content")
    (archive_dir / ARCHIVE_NAME).write_bytes(b"not a gzip stream at all")
    _restore_env(monkeypatch, target, backup, archive_dir)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert_that(exc_info.value.code, equal_to(EXIT_RESTORE_FAILED))
    assert_that((target / "workspace/live.md").read_text(), equal_to("live content"))
    assert_that(_members(backup), has_item("workspace/live.md"))
