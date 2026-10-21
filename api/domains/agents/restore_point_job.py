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
SKIPPED_LINKS_NAME = "skipped-links.json"

MODE_CAPTURE = "capture"
MODE_RESTORE = "restore"
MODE_RESET = "reset"

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

# Shared by restore and reset: the backup is on disk, so what failed is the part that
# changed the Agent volume. A restore fails while extracting, a reset while wiping.
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


class _Unarchivable(Exception):
    """A file with no tar form at all, which `tarfile.data_filter` never gets to judge."""


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
        kept_dirs = []
        for dir_name in sorted(dir_names):
            if is_excluded(prefix + dir_name, runtime):
                continue
            if (current / dir_name).is_symlink():
                # os.walk lists a link to a directory with the directories but does not enter it.
                # Left there it reaches neither the archive nor the skipped count, and a wipe would
                # remove it without a trace. It is archived as the link, and never followed.
                yield current / dir_name, prefix + dir_name
            else:
                kept_dirs.append(dir_name)
        dir_names[:] = kept_dirs
        for file_name in sorted(file_names):
            rel_path = prefix + file_name
            if not is_excluded(rel_path, runtime):
                yield current / file_name, rel_path


def capture(source: Path, dest: Path, runtime: str, lost_paths: list[str] | None = None) -> dict:
    """Archive the volume. What the archive cannot safely hold is counted and left out.

    A restore extracts with the same filter, so a member it refuses would fail the whole restore;
    dropping it here is what keeps an archive restorable. A link or a socket holds no data, so a
    skipped link is only written down, in `SKIPPED_LINKS_NAME` next to the archive. Anything else
    skipped is named in `lost_paths`: a caller that goes on to remove the volume has to look at it,
    because those files are in no archive.
    """
    archive_path = dest / ARCHIVE_NAME
    file_count = 0
    skipped = 0
    skipped_links: dict[str, str] = {}
    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            for path, rel_path in _walk_included_files(source, runtime):
                info = tar.gettarinfo(path, arcname=rel_path)
                try:
                    # A socket has no tar form: gettarinfo returns None for it.
                    if info is None:
                        raise _Unarchivable
                    tarfile.data_filter(info, "")
                except tarfile.FilterError, _Unarchivable:
                    skipped += 1
                    if path.is_symlink():
                        skipped_links[rel_path] = os.readlink(path)
                    elif lost_paths is not None and not stat.S_ISSOCK(path.lstat().st_mode):
                        lost_paths.append(rel_path)
                    continue
                if info.isreg():
                    with path.open("rb") as stream:
                        tar.addfile(info, stream)
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

    if skipped_links:
        (dest / SKIPPED_LINKS_NAME).write_text(json.dumps(skipped_links, indent=2))
        emit_note(
            f"{len(skipped_links)} link(s) point outside the volume and are not in the archive: {_sample(skipped_links)}"
        )

    manifest = {"bytes": archive_path.stat().st_size, "file_count": file_count, "skipped": skipped}
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


def _sample(paths) -> str:
    paths = list(paths)
    return ", ".join(paths[:5]) + (", ..." if len(paths) > 5 else "")


def emit_note(message: str) -> None:
    """Log a line for people reading the Job. A failure reported after it still wins."""
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def emit_failure(message: str) -> None:
    """Report a reason the API surfaces verbatim on the restore point row."""
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def _required_env(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return Path(value)


def _run_reset(target: Path, backup: Path, runtime: str) -> None:
    # Each phase fails on its own exit code: the API reads it to tell "the Agent
    # volume was never touched" from "it was emptied".
    lost_paths: list[str] = []
    try:
        manifest = capture(target, backup, runtime, lost_paths)
    except Exception as exc:
        emit_failure(f"pre-reset capture failed: {exc}")
        raise SystemExit(EXIT_BACKUP_FAILED) from exc

    if lost_paths:
        # A reset removes everything, so anything the backup could not hold would be gone for
        # good, and the row would still read as a clean success. Better to refuse. This is
        # reported as a failed backup, and no manifest is printed, so nothing reads it as a
        # backup that finished.
        emit_failure(
            f"{len(lost_paths)} file(s) cannot be saved in a backup (for example, device files or pipes), "
            f"so nothing was removed: {_sample(lost_paths)}"
        )
        raise SystemExit(EXIT_BACKUP_FAILED)
    emit_result(manifest)

    try:
        _wipe_contents(target)
    except Exception as exc:
        emit_failure(f"reset failed: {exc}")
        raise SystemExit(EXIT_RESTORE_FAILED) from exc


def main() -> None:
    mode = os.environ.get(ENV_MODE, MODE_CAPTURE)
    runtime = os.environ.get(ENV_RUNTIME, RUNTIME_HERMES)

    if mode == MODE_CAPTURE:
        emit_result(capture(_required_env(ENV_SOURCE), _required_env(ENV_DEST), runtime))
        return

    if mode == MODE_RESET:
        _run_reset(_required_env(ENV_TARGET), _required_env(ENV_BACKUP), runtime)
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
