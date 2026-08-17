"""add_skill_version_and_skill_file_tables

Replaces the single ``skill.zip_content`` blob with an append-only
``skill_version`` / ``skill_file`` pair. Existing skills are backfilled as
version 1 by unzipping their archive into text rows.

``skill.zip_content`` is left in place (made nullable) so rolling this deploy
back still finds content to serve; a follow-up migration drops it once the
file-based path has been verified in production.

Revision ID: c7d1e9f4a2b8
Revises: a3d7f5e91c62
Create Date: 2026-08-12 10:12:04.118233

"""

import datetime
import io
import logging
import re
import uuid
import zipfile
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d1e9f4a2b8"
down_revision: str | None = "a3d7f5e91c62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

_NON_SLUG_CHARS = re.compile(r"[^a-z0-9]+")
_JUNK_PREFIXES = ("__MACOSX/", "._")

# Path-validation constants — must match api.domains.skills.files. The migration
# cannot import application code (the code at HEAD may not match the schema being
# migrated), so these are inlined and drift-tested in the unit suite.
_MAX_FILES = 200
_MAX_FILE_BYTES = 1 * 1024 * 1024  # 1 MB per file
_MAX_TOTAL_BYTES = 5 * 1024 * 1024  # 5 MB per version
_MAX_PATH_LENGTH = 512
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _normalize_path(raw: str) -> str:
    """Validate a POSIX path relative to the skill root.

    Mirrors ``api.domains.skills.files.normalize_path``. Raises ``ValueError``
    when the path is unsafe; the caller skips the entry and counts it.
    """
    path = raw.strip().replace("\\", "/")
    path = path.removeprefix("./")
    while "//" in path:
        path = path.replace("//", "/")

    if not path:
        raise ValueError("empty")
    if len(path) > _MAX_PATH_LENGTH:
        raise ValueError("too long")
    if path.startswith("/"):
        raise ValueError("absolute")
    if path.endswith("/"):
        raise ValueError("directory")
    segments = path.split("/")
    for segment in segments:
        if segment in ("", ".", ".."):
            raise ValueError("invalid segment")
        if not _SEGMENT_RE.match(segment):
            raise ValueError("bad characters")
        if segment.startswith("._"):
            raise ValueError("junk")
    if path.startswith(_JUNK_PREFIXES):
        raise ValueError("junk")
    return path


def _slugify(name: str) -> str:
    return _NON_SLUG_CHARS.sub("-", name.lower()).strip("-")[:64].strip("-")


def _readable_entries(blob: bytes) -> tuple[list[tuple[str, str]], int]:
    """Return validated (path, content) pairs from a skill zip, plus a count of
    skipped entries.

    Each surviving entry is normalized through the path contract (traversal,
    absolute paths, disallowed characters, junk metadata) and the set is
    checked for case-insensitive duplicates, per-file size, total size, and
    file-count limits — the same rules that apply at the API boundary.
    Entries that fail are skipped and counted so an invalid legacy archive
    never creates unsafe or unmountable data.
    """
    raw: list[tuple[str, str]] = []
    skipped = 0
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for name in zf.namelist():
            if name.endswith("/") or name.startswith(_JUNK_PREFIXES) or "/._" in name:
                continue
            try:
                raw.append((name.replace("\\", "/"), zf.read(name).decode()))
            except UnicodeDecodeError:
                # Binary content has never been usable: the manifest builder always
                # decoded as UTF-8, so such an entry would already crash agent start.
                skipped += 1

    if len(raw) > _MAX_FILES:
        skipped += len(raw) - _MAX_FILES
        logger.warning("Skill zip has %d entries; keeping the first %d", len(raw), _MAX_FILES)
        raw = raw[:_MAX_FILES]

    seen: dict[str, str] = {}
    total = 0
    entries: list[tuple[str, str]] = []
    for raw_path, content in raw:
        try:
            path = _normalize_path(raw_path)
        except ValueError:
            skipped += 1
            continue
        lowered = path.lower()
        if lowered in seen:
            skipped += 1
            continue
        size = len(content.encode())
        if size > _MAX_FILE_BYTES:
            skipped += 1
            continue
        total += size
        if total > _MAX_TOTAL_BYTES:
            skipped += 1
            break
        seen[lowered] = path
        entries.append((path, content))
    return entries, skipped


def _split_root(entries: list[tuple[str, str]], fallback_root: str) -> tuple[str, list[tuple[str, str]]]:
    """Peel the shared top-level directory off a zip's paths.

    Today's archives already carry their mount directory as the first segment
    (``aai-cli/jira_skill.md``), and root_dir now supplies it at mount time. When
    the archive has no single shared root, keep the full paths under the skill's
    own slug so nothing moves on disk.
    """
    roots = {path.split("/")[0] for path, _ in entries}
    if len(roots) == 1 and all("/" in path for path, _ in entries):
        root = roots.pop()
        return root, [(path.split("/", 1)[1], content) for path, content in entries]
    return fallback_root, entries


def _pick_entry_path(paths: list[str]) -> str:
    if "SKILL.md" in paths:
        return "SKILL.md"
    markdown = [p for p in paths if p.lower().endswith(".md")]
    return min(markdown) if markdown else min(paths)


def upgrade() -> None:
    op.create_table(
        "skill_version",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_id", "version", name="uq_skill_version_skill_version"),
    )
    op.create_index("ix_skill_version_skill_id", "skill_version", ["skill_id"], unique=False)

    op.create_table(
        "skill_file",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("skill_version_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["skill_version_id"], ["skill_version.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_version_id", "path", name="uq_skill_file_version_path"),
    )
    op.create_index("ix_skill_file_version_id", "skill_file", ["skill_version_id"], unique=False)

    op.add_column("skill", sa.Column("slug", sa.String(length=255), nullable=True))
    op.add_column("skill", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("skill", sa.Column("root_dir", sa.String(length=255), nullable=True))
    op.add_column("skill", sa.Column("entry_path", sa.String(length=512), nullable=True))
    op.alter_column("skill", "zip_content", existing_type=sa.LargeBinary(), nullable=True)

    _backfill()

    op.alter_column("skill", "slug", existing_type=sa.String(length=255), nullable=False)
    op.alter_column("skill", "root_dir", existing_type=sa.String(length=255), nullable=False)
    op.alter_column("skill", "entry_path", existing_type=sa.String(length=512), nullable=False)
    op.create_unique_constraint("uq_skill_organization_slug", "skill", ["organization_id", "slug"])


def _backfill() -> None:
    bind = op.get_bind()
    now = datetime.datetime.now(datetime.UTC)
    rows = bind.execute(
        sa.text("SELECT id, organization_id, name, zip_content FROM skill ORDER BY created_at")
    ).fetchall()

    used_slugs: dict[tuple[str, str], int] = {}
    total_skipped = 0
    empty_skills: list[str] = []

    for skill_id, organization_id, name, zip_content in rows:
        base_slug = _slugify(name) or "skill"
        org_key = str(organization_id)
        # Slug is unique per organization; name already is, but slugification can
        # collapse two distinct names ("My Tool" and "my-tool") onto one slug.
        count = used_slugs.get((org_key, base_slug), 0)
        used_slugs[(org_key, base_slug)] = count + 1
        slug = base_slug if count == 0 else f"{base_slug}-{count + 1}"

        entries: list[tuple[str, str]] = []
        skipped = 0
        if zip_content:
            try:
                entries, skipped = _readable_entries(bytes(zip_content))
            except zipfile.BadZipFile:
                logger.warning("Skill %s (%r) has an unreadable archive; backfilled with no files", skill_id, name)
        total_skipped += skipped

        if entries:
            root_dir, files = _split_root(entries, slug)
            entry_path = _pick_entry_path([path for path, _ in files])
        else:
            # Nothing recoverable: leave the lineage with an empty version rather
            # than failing the upgrade, and report it at the end.
            root_dir, files, entry_path = slug, [], "SKILL.md"
            empty_skills.append(f"{name} ({skill_id})")

        bind.execute(
            sa.text("UPDATE skill SET slug = :slug, root_dir = :root_dir, entry_path = :entry_path WHERE id = :id"),
            {"slug": slug, "root_dir": root_dir, "entry_path": entry_path, "id": skill_id},
        )

        version_id = uuid.uuid7()
        bind.execute(
            sa.text(
                "INSERT INTO skill_version (id, created_at, updated_at, skill_id, version) "
                "VALUES (:id, :now, :now, :skill_id, 1)"
            ),
            {"id": version_id, "now": now, "skill_id": skill_id},
        )
        for path, content in files:
            bind.execute(
                sa.text(
                    "INSERT INTO skill_file (id, created_at, updated_at, skill_version_id, path, content) "
                    "VALUES (:id, :now, :now, :version_id, :path, :content)"
                ),
                {
                    "id": uuid.uuid7(),
                    "now": now,
                    "version_id": version_id,
                    "path": path,
                    "content": content,
                },
            )

    # Custom skills only ever held an auto-generated pointer ("You can use ... in
    # the ./skills folder") that had to be rewritten on every rename. It is now
    # derived from the skill's name, description and entry path, so clear the
    # stored copies and let the column mean "curated override" (built-ins only).
    bind.execute(sa.text("UPDATE skill SET tools_pointer = NULL WHERE source = 'custom'"))

    logger.warning("Backfilled %d skill(s) to version 1", len(rows))
    if total_skipped:
        logger.warning("Skipped %d non-UTF-8 skill file(s); they were never mountable", total_skipped)
    if empty_skills:
        logger.warning("Skills backfilled with no files (re-upload content): %s", ", ".join(empty_skills))


def downgrade() -> None:
    op.drop_constraint("uq_skill_organization_slug", "skill", type_="unique")
    op.drop_column("skill", "entry_path")
    op.drop_column("skill", "root_dir")
    op.drop_column("skill", "description")
    op.drop_column("skill", "slug")
    op.drop_index("ix_skill_file_version_id", table_name="skill_file")
    op.drop_table("skill_file")
    op.drop_index("ix_skill_version_skill_id", table_name="skill_version")
    op.drop_table("skill_version")
    # zip_content is intentionally left nullable: rows created after this migration
    # have no archive, so restoring NOT NULL would fail.
