import errno
import json
import ntpath
import os
import posixpath
import shutil
import sys
import tarfile
from pathlib import Path

ARCHIVE_NAME = "archive.tar.gz"
MANIFEST_NAME = "manifest.json"

MODE_CAPTURE = "capture"
MODE_RESTORE = "restore"

RUNTIME_HERMES = "hermes"
RUNTIME_OPENCLAW = "openclaw"

ENV_MODE = "RESTORE_POINT_MODE"
ENV_RUNTIME = "RESTORE_POINT_RUNTIME"
ENV_SOURCE = "RESTORE_POINT_SOURCE"
ENV_DEST = "RESTORE_POINT_DEST"
ENV_TARGET = "RESTORE_POINT_TARGET"
ENV_BACKUP = "RESTORE_POINT_BACKUP"
ENV_ARCHIVE = "RESTORE_POINT_ARCHIVE"

SIZE_SETTING_NAME = "RESTORE_POINT_SIZE"

EXIT_BACKUP_FAILED = 2
EXIT_RESTORE_FAILED = 3

_READ_CHUNK_BYTES = 1024 * 1024

_HERMES_EXCLUDED = (
    ".config/aai-cli",
    ".env",
    "SOUL.md",
    "config.yaml",
    "plugins",
    "agentbarn-messages.sqlite3",
    "workspace/skills",
    "workspace/IDENTITY.md",
    "workspace/AGENTS.md",
    "workspace/TOOLS.md",
    "workspace/BOOT.md",
    "workspace/HEARTBEAT.md",
)

_OPENCLAW_EXCLUDED = (
    "local-plugins",
    "openclaw.json",
    "agentbarn-messages.sqlite3",
    "workspace/skills",
)

_OPENCLAW_AGENT_OWNED = ("workspace/USER.md",)


class ArchiveValidationError(Exception):
    pass


class DestinationFullError(Exception):
    pass


def _matches_prefix(rel_path: str, prefixes: tuple[str, ...]) -> bool:
    return any(rel_path == prefix or rel_path.startswith(prefix + "/") for prefix in prefixes)


def _is_regenerated_openclaw_markdown(rel_path: str) -> bool:
    parent, _, name = rel_path.rpartition("/")
    if parent != "workspace" or not name.endswith(".md"):
        return False
    return rel_path not in _OPENCLAW_AGENT_OWNED


def is_excluded(rel_path: str, runtime: str) -> bool:
    if runtime == RUNTIME_HERMES:
        return _matches_prefix(rel_path, _HERMES_EXCLUDED)
    if _matches_prefix(rel_path, _OPENCLAW_EXCLUDED):
        return True
    return _is_regenerated_openclaw_markdown(rel_path)


def _walk_included_files(root: Path, runtime: str):
    for dir_path, dir_names, file_names in os.walk(root, followlinks=False):
        current = Path(dir_path)
        rel_dir = current.relative_to(root).as_posix()
        prefix = "" if rel_dir == "." else rel_dir + "/"
        dir_names[:] = sorted(d for d in dir_names if not is_excluded(prefix + d, runtime))
        for file_name in sorted(file_names):
            rel_path = prefix + file_name
            if not is_excluded(rel_path, runtime):
                yield current / file_name, rel_path


def capture(source: Path, dest: Path, runtime: str) -> dict:
    archive_path = dest / ARCHIVE_NAME
    file_count = 0
    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            for path, rel_path in _walk_included_files(source, runtime):
                tar.add(path, arcname=rel_path, recursive=False)
                file_count += 1
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            archive_path.unlink(missing_ok=True)
            raise DestinationFullError(
                f"The restore point volume ran out of space while archiving. Raise {SIZE_SETTING_NAME}."
            ) from exc
        raise

    manifest = {"bytes": archive_path.stat().st_size, "file_count": file_count}
    (dest / MANIFEST_NAME).write_text(json.dumps(manifest))
    return manifest


def _assert_member_is_safe(member: tarfile.TarInfo, target: Path) -> None:
    if posixpath.isabs(member.name) or ntpath.isabs(member.name):
        raise ArchiveValidationError(f"{member.name!r} is an absolute path")
    try:
        tarfile.data_filter(member, str(target))
    except tarfile.FilterError as exc:
        raise ArchiveValidationError(f"{member.name!r} is not safe to extract: {exc}") from exc


def validate_archive(archive_path: Path, target: Path) -> None:
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            for member in tar:
                _assert_member_is_safe(member, target)
                if not member.isfile():
                    continue
                stream = tar.extractfile(member)
                if stream is None:
                    continue
                while stream.read(_READ_CHUNK_BYTES):
                    pass
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise ArchiveValidationError(f"The archive could not be read: {exc}") from exc


def _wipe_contents(target: Path) -> None:
    for entry in target.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def _apply_ownership(target: Path, uid: int, gid: int) -> None:
    if not hasattr(os, "chown"):
        return
    os.chown(target, uid, gid)
    for dir_path, dir_names, file_names in os.walk(target, followlinks=False):
        for name in list(dir_names) + list(file_names):
            os.chown(Path(dir_path) / name, uid, gid)


def apply_archive(target: Path, archive_dir: Path) -> None:
    archive_path = archive_dir / ARCHIVE_NAME
    validate_archive(archive_path, target)

    target_stat = target.stat()
    _wipe_contents(target)

    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(target, filter="data")

    _apply_ownership(target, target_stat.st_uid, target_stat.st_gid)


def restore(target: Path, backup: Path, archive_dir: Path, runtime: str) -> None:
    capture(target, backup, runtime)
    apply_archive(target, archive_dir)


def _required_env(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return Path(value)


def main() -> None:
    mode = os.environ.get(ENV_MODE, MODE_CAPTURE)
    runtime = os.environ.get(ENV_RUNTIME, RUNTIME_HERMES)

    if mode == MODE_CAPTURE:
        manifest = capture(_required_env(ENV_SOURCE), _required_env(ENV_DEST), runtime)
        print(json.dumps(manifest))
        return

    if mode != MODE_RESTORE:
        raise SystemExit(f"Unknown {ENV_MODE}: {mode}")

    target = _required_env(ENV_TARGET)
    backup = _required_env(ENV_BACKUP)
    archive_dir = _required_env(ENV_ARCHIVE)

    try:
        capture(target, backup, runtime)
    except Exception as exc:
        print(f"pre-restore capture failed: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_BACKUP_FAILED) from exc

    try:
        apply_archive(target, archive_dir)
    except Exception as exc:
        print(f"restore failed: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_RESTORE_FAILED) from exc
