"""complete the scoped, versioned Skill library model

The earlier Skills v2 migrations introduced database-backed SkillVersion and
SkillFile rows but intentionally kept the legacy ZIP column and only modeled
Platform/Organization ownership. This migration completes the durable contract:
Agent-owned lineages, immutable version metadata/source provenance, versioned
Template requirements, normalized SKILL.md paths, and no ZIP storage.

Revision ID: b6c7d8e9f0a1
Revises: f39d7aa422be
Create Date: 2026-08-25 10:00:00.000000

"""

from __future__ import annotations

import datetime
import io
import re
import uuid
import zipfile
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6c7d8e9f0a1"
down_revision: str | None = "f39d7aa422be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MAX_PATH_LENGTH = 512
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_ENTRY_PATH = "SKILL.md"
_TEMPLATE_TEXT_COLUMNS = {
    "platform_template": (
        "soul_md",
        "identity_md",
        "user_md",
        "tools_md",
        "agents_md",
        "boot_md",
        "bootstrap_md",
        "heartbeat_md",
    ),
    "platform_template_draft": (
        "soul_md",
        "identity_md",
        "user_md",
        "tools_md",
        "agents_md",
        "boot_md",
        "bootstrap_md",
        "heartbeat_md",
    ),
    "agent_template": (
        "soul_md",
        "identity_md",
        "user_md",
        "tools_md",
        "agents_md",
        "boot_md",
        "bootstrap_md",
        "heartbeat_md",
    ),
    "agent_template_override_draft": (
        "soul_md",
        "identity_md",
        "user_md",
        "tools_md",
        "agents_md",
        "boot_md",
        "bootstrap_md",
        "heartbeat_md",
    ),
    "agent_template_override_version": (
        "soul_md",
        "identity_md",
        "user_md",
        "tools_md",
        "agents_md",
        "boot_md",
        "bootstrap_md",
        "heartbeat_md",
    ),
}

_VERSIONED_SKILL_TABLES = (
    ("agent_template_skill", "template_id", "uq_agent_template_skill", "fk_agent_template_skill_version"),
    ("platform_template_skill", "template_id", "uq_platform_template_skill", "fk_platform_template_skill_version"),
    (
        "platform_template_draft_skill",
        "draft_id",
        "uq_platform_template_draft_skill",
        "fk_platform_template_draft_skill_version",
    ),
    (
        "agent_template_override_draft_skill",
        "draft_id",
        "uq_agent_template_override_draft_skill",
        "fk_agent_template_override_draft_skill_version",
    ),
    (
        "agent_template_override_version_skill",
        "version_id",
        "uq_agent_template_override_version_skill",
        "fk_agent_template_override_version_skill_version",
    ),
)


def _normalize_path(raw: str) -> str:
    path = raw.strip().replace("\\", "/").removeprefix("./")
    while "//" in path:
        path = path.replace("//", "/")
    if not path or len(path) > _MAX_PATH_LENGTH or path.startswith("/") or path.endswith("/"):
        raise RuntimeError(f"Invalid legacy Skill file path: {raw!r}")
    segments = path.split("/")
    if any(segment in ("", ".", "..") or not _SEGMENT_RE.match(segment) for segment in segments):
        raise RuntimeError(f"Invalid legacy Skill file path: {raw!r}")
    if path.startswith(("__MACOSX/", "._")) or any(segment.startswith("._") for segment in segments):
        raise RuntimeError(f"Archive metadata reached the Skill database: {raw!r}")
    return path


def _choose_entry_path(skill_name: str, skill_id: uuid.UUID, old_entry: str, paths: list[str]) -> str:
    if _ENTRY_PATH in paths:
        return _ENTRY_PATH
    if old_entry in paths:
        return old_entry
    markdown = [path for path in paths if path.lower().endswith(".md")]
    if len(markdown) == 1:
        return markdown[0]
    if not markdown:
        raise RuntimeError(
            f"Skill migration cannot find a SKILL.md candidate for {skill_name!r} ({skill_id}); "
            "repair the legacy content before retrying"
        )
    raise RuntimeError(
        f"Skill migration found multiple SKILL.md candidates for {skill_name!r} ({skill_id}): "
        f"{', '.join(sorted(markdown))}"
    )


def _replace_mount_references(content: str, old_root: str, old_entry: str, new_root: str) -> str:
    """Keep legacy pointers usable after every Skill gets its own SKILL.md root."""
    replacements = {
        f"./skills/{old_root}/{old_entry}": f"./skills/{new_root}/{_ENTRY_PATH}",
        f"skills/{old_root}/{old_entry}": f"skills/{new_root}/{_ENTRY_PATH}",
    }
    for old, new in replacements.items():
        content = content.replace(old, new)
    return content


def _normalize_template_references(bind: sa.engine.Connection, old_root: str, old_entry: str, new_root: str) -> None:
    replacements = (
        (f"./skills/{old_root}/{old_entry}", f"./skills/{new_root}/{_ENTRY_PATH}"),
        (f"skills/{old_root}/{old_entry}", f"skills/{new_root}/{_ENTRY_PATH}"),
    )
    for table, columns in _TEMPLATE_TEXT_COLUMNS.items():
        for column in columns:
            for old_path, new_path in replacements:
                bind.execute(
                    sa.text(
                        f"UPDATE {table} SET {column} = REPLACE({column}, :old_path, :new_path) "
                        f"WHERE {column} IS NOT NULL"
                    ),
                    {"old_path": old_path, "new_path": new_path},
                )


def _add_version_columns() -> None:
    for table, parent_column, constraint, _ in _VERSIONED_SKILL_TABLES:
        op.drop_constraint(constraint, table, type_="unique")
        op.add_column(table, sa.Column("skill_version", sa.Integer(), nullable=True))
        op.execute(
            sa.text(
                f"UPDATE {table} AS requirement "
                "SET skill_version = latest.version "
                "FROM (SELECT skill_id, MAX(version) AS version FROM skill_version GROUP BY skill_id) AS latest "
                "WHERE latest.skill_id = requirement.skill_id"
            )
        )
        op.execute(sa.text(f"UPDATE {table} SET skill_version = 1 WHERE skill_version IS NULL"))
        op.alter_column(table, "skill_version", existing_type=sa.Integer(), nullable=False)
        op.create_unique_constraint(
            constraint,
            table,
            [parent_column, "skill_id", "skill_version"],
        )


def _normalize_existing_files() -> None:
    bind = op.get_bind()
    rows = (
        bind.execute(
            sa.text(
                "SELECT id, organization_id, name, slug, root_dir, entry_path, source "
                "FROM skill ORDER BY created_at, id"
            )
        )
        .mappings()
        .all()
    )

    now = datetime.datetime.now(datetime.UTC)
    for row in rows:
        skill_id = row["id"]
        old_root = row["root_dir"] or row["slug"]
        old_entry = row["entry_path"] or _ENTRY_PATH
        legacy_slug = row["slug"] or "skill"
        new_root = (
            legacy_slug
            if row["source"] == "aai_cli" and legacy_slug.startswith("aai-")
            else f"aai-{legacy_slug}"
            if row["source"] == "aai_cli"
            else legacy_slug
        )

        version_rows = (
            bind.execute(
                sa.text("SELECT id FROM skill_version WHERE skill_id = :skill_id ORDER BY version"),
                {"skill_id": skill_id},
            )
            .mappings()
            .all()
        )
        for version in version_rows:
            files = (
                bind.execute(
                    sa.text(
                        "SELECT id, path, content FROM skill_file WHERE skill_version_id = :version_id ORDER BY path"
                    ),
                    {"version_id": version["id"]},
                )
                .mappings()
                .all()
            )
            paths = [_normalize_path(file["path"]) for file in files]
            entry = _choose_entry_path(row["name"], skill_id, old_entry, paths)
            seen: set[str] = set()
            for file, normalized in zip(files, paths, strict=True):
                new_path = _ENTRY_PATH if normalized == entry else normalized
                if new_path.lower() in seen:
                    raise RuntimeError(
                        f"Skill migration creates duplicate files for {row['name']!r} ({skill_id}): {new_path!r}"
                    )
                seen.add(new_path.lower())
                content = _replace_mount_references(file["content"], old_root, old_entry, new_root)
                bind.execute(
                    sa.text("UPDATE skill_file SET path = :path, content = :content, updated_at = :now WHERE id = :id"),
                    {"path": new_path, "content": content, "now": now, "id": file["id"]},
                )

            bind.execute(
                sa.text(
                    "UPDATE skill_version SET description = COALESCE(description, "
                    "(SELECT description FROM skill WHERE skill.id = skill_version.skill_id)), "
                    "required_providers = COALESCE(required_providers, "
                    "(SELECT required_providers FROM skill WHERE skill.id = skill_version.skill_id), '[]') "
                    "WHERE id = :id"
                ),
                {"id": version["id"]},
            )

        draft_rows = (
            bind.execute(
                sa.text("SELECT id FROM skill_draft WHERE skill_id = :skill_id"),
                {"skill_id": skill_id},
            )
            .mappings()
            .all()
        )
        for draft in draft_rows:
            files = (
                bind.execute(
                    sa.text(
                        "SELECT id, path, content FROM skill_draft_file WHERE skill_draft_id = :draft_id ORDER BY path"
                    ),
                    {"draft_id": draft["id"]},
                )
                .mappings()
                .all()
            )
            if not files:
                continue
            paths = [_normalize_path(file["path"]) for file in files]
            entry = _choose_entry_path(row["name"], skill_id, old_entry, paths)
            seen: set[str] = set()
            for file, normalized in zip(files, paths, strict=True):
                new_path = _ENTRY_PATH if normalized == entry else normalized
                if new_path.lower() in seen:
                    raise RuntimeError(
                        f"Skill migration creates duplicate draft files for {row['name']!r} ({skill_id}): {new_path!r}"
                    )
                seen.add(new_path.lower())
                content = _replace_mount_references(file["content"], old_root, old_entry, new_root)
                bind.execute(
                    sa.text(
                        "UPDATE skill_draft_file SET path = :path, content = :content, updated_at = :now WHERE id = :id"
                    ),
                    {"path": new_path, "content": content, "now": now, "id": file["id"]},
                )

        _normalize_template_references(bind, old_root, old_entry, new_root)
        bind.execute(
            sa.text(
                "UPDATE skill SET slug = :root_dir, root_dir = :root_dir, entry_path = :entry_path, "
                "tools_pointer = REPLACE(REPLACE(tools_pointer, :old_pointer, :new_pointer), "
                ":old_root_prefix, :new_root_prefix), updated_at = :now WHERE id = :id"
            ),
            {
                "root_dir": new_root,
                "entry_path": _ENTRY_PATH,
                "old_pointer": f"./skills/{old_root}/{old_entry}",
                "new_pointer": f"./skills/{new_root}/{_ENTRY_PATH}",
                "old_root_prefix": f"./skills/{old_root}/",
                "new_root_prefix": f"./skills/{new_root}/",
                "now": now,
                "id": skill_id,
            },
        )


def upgrade() -> None:
    op.add_column("skill", sa.Column("agent_id", sa.Uuid(), nullable=True))
    op.create_index("ix_skill_agent_id", "skill", ["agent_id"], unique=False)
    op.create_foreign_key("fk_skill_agent_id", "skill", "agent", ["agent_id"], ["id"], ondelete="CASCADE")
    op.create_check_constraint(
        "ck_skill_agent_requires_organization",
        "skill",
        "agent_id IS NULL OR organization_id IS NOT NULL",
    )

    op.add_column("skill_version", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("skill_version", sa.Column("required_providers", sa.JSON(), nullable=True))
    op.add_column("skill_version", sa.Column("source_skill_id", sa.Uuid(), nullable=True))
    op.add_column("skill_version", sa.Column("source_skill_version", sa.Integer(), nullable=True))
    op.create_index(
        "ix_skill_version_source_skill",
        "skill_version",
        ["source_skill_id", "source_skill_version"],
        unique=False,
    )
    op.create_check_constraint(
        "ck_skill_version_source_pair",
        "skill_version",
        "(source_skill_id IS NULL) = (source_skill_version IS NULL)",
    )

    op.add_column("skill_draft", sa.Column("source_skill_id", sa.Uuid(), nullable=True))
    op.add_column("skill_draft", sa.Column("source_skill_version", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_skill_draft_source_pair",
        "skill_draft",
        "(source_skill_id IS NULL) = (source_skill_version IS NULL)",
    )

    _add_version_columns()

    # Normalize legacy archives before dropping their only source of truth. The
    # migration intentionally aborts on ambiguous or missing entry files instead
    # of silently creating an unmountable Skill.
    _normalize_existing_files()

    op.alter_column(
        "skill_version",
        "required_providers",
        existing_type=sa.JSON(),
        nullable=False,
        server_default="[]",
    )

    for table, _, _, fk_name in _VERSIONED_SKILL_TABLES:
        op.create_foreign_key(
            fk_name,
            table,
            "skill_version",
            ["skill_id", "skill_version"],
            ["skill_id", "version"],
            ondelete="RESTRICT",
        )

    op.create_foreign_key(
        "fk_skill_version_source_version",
        "skill_version",
        "skill_version",
        ["source_skill_id", "source_skill_version"],
        ["skill_id", "version"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_skill_draft_source_version",
        "skill_draft",
        "skill_version",
        ["source_skill_id", "source_skill_version"],
        ["skill_id", "version"],
        ondelete="RESTRICT",
    )

    op.drop_constraint("uq_skill_organization_name", "skill", type_="unique")
    op.drop_constraint("uq_skill_organization_slug", "skill", type_="unique")
    op.create_index(
        "uq_skill_platform_name",
        "skill",
        ["name"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NULL AND agent_id IS NULL"),
    )
    op.create_index(
        "uq_skill_org_name",
        "skill",
        ["organization_id", "name"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NOT NULL AND agent_id IS NULL"),
    )
    op.create_index(
        "uq_skill_agent_name",
        "skill",
        ["agent_id", "name"],
        unique=True,
        postgresql_where=sa.text("agent_id IS NOT NULL"),
    )
    op.create_index(
        "uq_skill_platform_slug",
        "skill",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NULL AND agent_id IS NULL"),
    )
    op.create_index(
        "uq_skill_org_slug",
        "skill",
        ["organization_id", "slug"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NOT NULL AND agent_id IS NULL"),
    )
    op.create_index(
        "uq_skill_agent_slug",
        "skill",
        ["agent_id", "slug"],
        unique=True,
        postgresql_where=sa.text("agent_id IS NOT NULL"),
    )

    # ZIP bytes are migration input only. The database file rows are now the
    # sole source of truth and the legacy column must not survive this release.
    op.drop_column("skill", "zip_content")


def _restore_legacy_zip_column() -> None:
    """Recreate the pre-b6 ZIP compatibility column for Alembic test/rollback paths."""
    op.add_column("skill", sa.Column("zip_content", sa.LargeBinary(), nullable=True))
    bind = op.get_bind()
    skills = bind.execute(sa.text("SELECT id, root_dir FROM skill ORDER BY id")).mappings().all()
    for skill in skills:
        version = bind.execute(
            sa.text("SELECT id FROM skill_version WHERE skill_id = :skill_id ORDER BY version DESC LIMIT 1"),
            {"skill_id": skill["id"]},
        ).scalar()
        if version is None:
            continue
        files = (
            bind.execute(
                sa.text("SELECT path, content FROM skill_file WHERE skill_version_id = :version_id ORDER BY path"),
                {"version_id": version},
            )
            .mappings()
            .all()
        )
        if not files:
            continue
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            for file in files:
                zip_file.writestr(f"{skill['root_dir']}/{file['path']}", file["content"])
        bind.execute(
            sa.text("UPDATE skill SET zip_content = :zip_content WHERE id = :id"),
            {"zip_content": archive.getvalue(), "id": skill["id"]},
        )


def downgrade() -> None:
    # The ZIP column was removed from steady state, but Alembic's integration
    # suites and operators may still need to roll back to the preceding revision.
    # Rehydrate it from the latest normalized snapshot before removing the new
    # version metadata and constraints.
    _restore_legacy_zip_column()

    op.drop_constraint("fk_skill_draft_source_version", "skill_draft", type_="foreignkey")
    op.drop_constraint("fk_skill_version_source_version", "skill_version", type_="foreignkey")
    for table, _, _, fk_name in _VERSIONED_SKILL_TABLES:
        op.drop_constraint(fk_name, table, type_="foreignkey")

    op.drop_constraint("ck_skill_draft_source_pair", "skill_draft", type_="check")
    op.drop_column("skill_draft", "source_skill_version")
    op.drop_column("skill_draft", "source_skill_id")

    op.drop_constraint("ck_skill_version_source_pair", "skill_version", type_="check")
    op.drop_index("ix_skill_version_source_skill", table_name="skill_version")
    op.drop_column("skill_version", "source_skill_version")
    op.drop_column("skill_version", "source_skill_id")
    op.drop_column("skill_version", "required_providers")
    op.drop_column("skill_version", "description")

    for table, parent_column, constraint, _ in _VERSIONED_SKILL_TABLES:
        op.drop_constraint(constraint, table, type_="unique")
        op.drop_column(table, "skill_version")
        op.create_unique_constraint(constraint, table, [parent_column, "skill_id"])

    op.drop_index("uq_skill_agent_slug", table_name="skill")
    op.drop_index("uq_skill_org_slug", table_name="skill")
    op.drop_index("uq_skill_platform_slug", table_name="skill")
    op.drop_index("uq_skill_agent_name", table_name="skill")
    op.drop_index("uq_skill_org_name", table_name="skill")
    op.drop_index("uq_skill_platform_name", table_name="skill")
    op.drop_constraint("ck_skill_agent_requires_organization", "skill", type_="check")
    op.drop_constraint("fk_skill_agent_id", "skill", type_="foreignkey")
    op.drop_index("ix_skill_agent_id", table_name="skill")
    op.drop_column("skill", "agent_id")
    op.create_unique_constraint("uq_skill_organization_name", "skill", ["organization_id", "name"])
    op.create_unique_constraint("uq_skill_organization_slug", "skill", ["organization_id", "slug"])
