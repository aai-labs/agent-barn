import errno
import json
import ntpath
import os
import posixpath
import shutil
import stat
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

HERMES_EXCLUDED = (
    ".cache",
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

OPENCLAW_EXCLUDED = (
    # aai-cli's encrypted secret store and its key live here (Hermes keeps them under
    # .config/aai-cli); the boot script rewrites both from the agent's credentials.
    "aai-cli",
    "local-plugins",
    "openclaw.json",
    "agentbarn-messages.sqlite3",
    "workspace/skills",
    "workspace/AGENTS.md",
    "workspace/BOOT.md",
    "workspace/BOOTSTRAP.md",
    "workspace/HEARTBEAT.md",
    "workspace/IDENTITY.md",
    "workspace/SOUL.md",
    "workspace/TOOLS.md",
)


class ArchiveValidationError(Exception):
    pass


class DestinationFullError(Exception):
    pass


def _matches_prefix(rel_path: str, prefixes: tuple[str, ...]) -> bool:
    return any(rel_path == prefix or rel_path.startswith(prefix + "/") for prefix in prefixes)


def is_excluded(rel_path: str, runtime: str) -> bool:
    excluded = HERMES_EXCLUDED if runtime == RUNTIME_HERMES else OPENCLAW_EXCLUDED
    return _matches_prefix(rel_path, excluded)


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


class _ExactSizeReader:
    """Reads exactly `size` bytes from a file the running Agent may still be writing.

    The tar header has already promised `size` bytes by the time the data is read, so a
    file that shrank is padded with zeros instead of leaving a short member that breaks
    the whole archive. A file that grew is cut at `size`.
    """

    def __init__(self, stream, size: int) -> None:
        self.stream = stream
        self.remaining = size
        self.shrank = False

    def read(self, size: int = -1) -> bytes:
        wanted = self.remaining if size < 0 else min(size, self.remaining)
        data = self.stream.read(wanted)
        if len(data) < wanted:
            self.shrank = True
            data += b"\0" * (wanted - len(data))
        self.remaining -= wanted
        return data


def _open_regular_file(path: Path):
    """Open a file found by the walk, or None if it is gone or no longer a regular file."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return None
        raise
    stream = os.fdopen(fd, "rb")
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        stream.close()
        return None
    return stream


def capture(source: Path, dest: Path, runtime: str) -> dict:
    archive_path = dest / ARCHIVE_NAME
    file_count = 0
    skipped = 0
    changed = 0
    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            for path, rel_path in _walk_included_files(source, runtime):
                try:
                    info = tar.gettarinfo(path, arcname=rel_path)
                except FileNotFoundError:
                    skipped += 1
                    continue
                try:
                    tarfile.data_filter(info, "")
                except tarfile.FilterError:
                    skipped += 1
                    continue
                if info.isreg():
                    stream = _open_regular_file(path)
                    if stream is None:
                        skipped += 1
                        continue
                    with stream:
                        info.size = os.fstat(stream.fileno()).st_size
                        reader = _ExactSizeReader(stream, info.size)
                        tar.addfile(info, reader)
                    changed += reader.shrank
                else:
                    tar.addfile(info)
                file_count += 1
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            archive_path.unlink(missing_ok=True)
            raise DestinationFullError(
                f"The restore point volume ran out of space while archiving. Raise {SIZE_SETTING_NAME}."
            ) from exc
        raise

    manifest = {
        "bytes": archive_path.stat().st_size,
        "file_count": file_count,
        "skipped": skipped,
        "changed": changed,
    }
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
    if not hasattr(os, "lchown"):
        return
    os.lchown(target, uid, gid)
    for dir_path, dir_names, file_names in os.walk(target, followlinks=False):
        for name in list(dir_names) + list(file_names):
            os.lchown(Path(dir_path) / name, uid, gid)


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


def emit_result(manifest: dict) -> None:
    """Return the manifest to the API, which cannot read the destination volume."""
    sys.stdout.write(json.dumps(manifest) + "\n")
    sys.stdout.flush()


def emit_failure(message: str) -> None:
    """Report a reason the API surfaces verbatim on the restore point row."""
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def _required_env(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return Path(value)


def main() -> None:
    mode = os.environ.get(ENV_MODE, MODE_CAPTURE)
    runtime = os.environ.get(ENV_RUNTIME, RUNTIME_HERMES)

    if mode == MODE_CAPTURE:
        emit_result(capture(_required_env(ENV_SOURCE), _required_env(ENV_DEST), runtime))
        return

    if mode != MODE_RESTORE:
        raise SystemExit(f"Unknown {ENV_MODE}: {mode}")

    target = _required_env(ENV_TARGET)
    backup = os.environ.get(ENV_BACKUP)
    archive_dir = _required_env(ENV_ARCHIVE)

    if backup:
        try:
            emit_result(capture(target, Path(backup), runtime))
        except Exception as exc:
            emit_failure(f"pre-restore capture failed: {exc}")
            raise SystemExit(EXIT_BACKUP_FAILED) from exc

    try:
        apply_archive(target, archive_dir)
    except Exception as exc:
        emit_failure(f"restore failed: {exc}")
        raise SystemExit(EXIT_RESTORE_FAILED) from exc
