from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from injector import inject, singleton
from sqlalchemy import func
from sqlmodel import Session, col, delete, or_, select

from api.domains.agents.models import Agent, AgentSkill, SecretProvider, SkillVersionPin
from api.domains.skills.models import (
    PinnedSkill,
    Skill,
    SkillDraft,
    SkillDraftFile,
    SkillFile,
    SkillFilter,
    SkillSource,
    SkillVersion,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import Pagination


@inject
@singleton
@dataclass
class SkillRepository:
    delegate: PostgresRepositoryDelegate

    def get_by_id(self, skill_id: UUID) -> Skill | None:
        return self.delegate.find_by_id(Skill, skill_id)

    def get_by_id_for_org(self, skill_id: UUID, org_id: UUID) -> Skill | None:
        """Tenant-scoped lookup: a custom skill belongs to ``org_id``, a built-in
        (organization_id IS NULL) is globally visible. Other orgs' skills are
        concealed so callers can distinguish 404 from 403 without post-fetch
        filtering."""
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(Skill).where(
                    col(Skill.id) == skill_id,
                    or_(col(Skill.organization_id) == org_id, col(Skill.organization_id).is_(None)),
                )
            ).first()

    # --- versions and files -------------------------------------------------
    #
    # The published version of a lineage is always its highest ``version``:
    # publishing and restoring both append, so "latest" and "current" coincide and
    # no current-version pointer has to be kept in sync.

    def get_latest_version(self, skill_id: UUID) -> SkillVersion | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(SkillVersion)
                .where(col(SkillVersion.skill_id) == skill_id)
                .order_by(col(SkillVersion.version).desc())
                .limit(1)
            )
            return session.exec(query).first()

    def get_latest_version_numbers(self, skill_ids: list[UUID]) -> dict[UUID, int]:
        """Latest version number per skill, for list/detail responses."""
        if not skill_ids:
            return {}
        with Session(self.delegate.engine) as session:
            query = (
                select(SkillVersion.skill_id, func.max(col(SkillVersion.version)))
                .where(col(SkillVersion.skill_id).in_(skill_ids))
                .group_by(col(SkillVersion.skill_id))
            )
            return {skill_id: version for skill_id, version in session.exec(query).all()}

    def get_version(self, skill_id: UUID, version: int) -> SkillVersion | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(SkillVersion)
                .where(col(SkillVersion.skill_id) == skill_id)
                .where(col(SkillVersion.version) == version)
            )
            return session.exec(query).first()

    def list_versions(self, skill_id: UUID) -> list[SkillVersion]:
        with Session(self.delegate.engine) as session:
            query = (
                select(SkillVersion)
                .where(col(SkillVersion.skill_id) == skill_id)
                .order_by(col(SkillVersion.version).desc())
            )
            return list(session.exec(query).all())

    def get_files(self, version_id: UUID) -> list[SkillFile]:
        with Session(self.delegate.engine) as session:
            query = (
                select(SkillFile)
                .where(col(SkillFile.skill_version_id) == version_id)
                .order_by(col(SkillFile.path).asc())
            )
            return list(session.exec(query).all())

    def get_files_for_skill_versions(self, pins: list[SkillVersionPin]) -> dict[UUID, list[SkillFile]]:
        """Files of each skill's *pinned* version, keyed by skill id.

        Used when materializing an agent's skills at start, so mounting resolves
        the exact version an agent pinned rather than the lineage's latest.
        """
        if not pins:
            return {}
        with Session(self.delegate.engine) as session:
            conditions = [
                (col(SkillVersion.skill_id) == pin.skill_id) & (col(SkillVersion.version) == pin.version)
                for pin in pins
            ]
            version_rows = list(session.exec(select(SkillVersion).where(or_(*conditions))).all())
            if not version_rows:
                return {}
            version_ids = {v.id: v.skill_id for v in version_rows}
            files = session.exec(
                select(SkillFile)
                .where(col(SkillFile.skill_version_id).in_(list(version_ids)))
                .order_by(col(SkillFile.path).asc())
            ).all()

        result: dict[UUID, list[SkillFile]] = {}
        for file in files:
            result.setdefault(version_ids[file.skill_version_id], []).append(file)
        return result

    def is_skill_version_pinned(self, skill_id: UUID, version: int, org_id: UUID) -> bool:
        """Whether an organization's non-soft-deleted agent pins this version."""
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentSkill)
                .join(Agent, col(AgentSkill.agent_id) == col(Agent.id))
                .where(col(AgentSkill.skill_id) == skill_id)
                .where(col(AgentSkill.pinned_version) == version)
                .where(col(Agent.organization_id) == org_id)
                .where(col(Agent.deleted_at).is_(None))
            )
            return session.exec(query).first() is not None

    def get_pinned_versions_for_skill(self, skill_id: UUID, org_id: UUID) -> set[int]:
        """Versions pinned by non-soft-deleted agents in an organization."""
        with Session(self.delegate.engine) as session:
            query = (
                select(col(AgentSkill.pinned_version))
                .join(Agent, col(AgentSkill.agent_id) == col(Agent.id))
                .where(col(AgentSkill.skill_id) == skill_id)
                .where(col(Agent.organization_id) == org_id)
                .where(col(Agent.deleted_at).is_(None))
            )
            return set(session.exec(query).all())

    def publish_version(
        self,
        skill_id: UUID,
        files: list[tuple[str, str]],
        *,
        created_by: UUID | None = None,
    ) -> SkillVersion:
        """Append the next immutable version of a lineage. History is never mutated in place."""
        with Session(self.delegate.engine) as session:
            current = session.exec(
                select(func.max(col(SkillVersion.version))).where(col(SkillVersion.skill_id) == skill_id)
            ).one()
            version = SkillVersion(
                skill_id=skill_id,
                version=(current or 0) + 1,
                created_by=created_by,
            )
            session.add(version)
            session.flush()
            for path, content in files:
                session.add(SkillFile(skill_version_id=version.id, path=path, content=content))
            session.commit()
            session.refresh(version)
            return version

    # --- draft -----------------------------------------------------------
    #
    # At most one draft per lineage: a get-or-create slot for in-progress file
    # edits, mutated in place until it's published or discarded.

    def get_draft(self, skill_id: UUID) -> SkillDraft | None:
        with Session(self.delegate.engine) as session:
            query = select(SkillDraft).where(col(SkillDraft.skill_id) == skill_id)
            return session.exec(query).first()

    def get_draft_skill_ids(self, skill_ids: list[UUID]) -> set[UUID]:
        """Which of these skills have an in-flight draft, for list/detail reads
        that need to show a "Draft in progress" indicator without probing."""
        if not skill_ids:
            return set()
        with Session(self.delegate.engine) as session:
            query = select(SkillDraft.skill_id).where(col(SkillDraft.skill_id).in_(skill_ids))
            return set(session.exec(query).all())

    def get_draft_files(self, draft_id: UUID) -> list[SkillDraftFile]:
        with Session(self.delegate.engine) as session:
            query = (
                select(SkillDraftFile)
                .where(col(SkillDraftFile.skill_draft_id) == draft_id)
                .order_by(col(SkillDraftFile.path).asc())
            )
            return list(session.exec(query).all())

    def save_new_draft(
        self,
        skill_id: UUID,
        files: list[tuple[str, str]],
        *,
        description: str | None = None,
        required_providers: list[str] | None = None,
    ) -> SkillDraft:
        with Session(self.delegate.engine) as session:
            draft = SkillDraft(
                skill_id=skill_id,
                description=description,
                required_providers=required_providers or [],
            )
            session.add(draft)
            session.flush()
            for path, content in files:
                session.add(SkillDraftFile(skill_draft_id=draft.id, path=path, content=content))
            session.commit()
            session.refresh(draft)
            return draft

    def update_draft_files(
        self,
        draft_id: UUID,
        files: list[tuple[str, str]],
        *,
        metadata: dict[str, str | list[str] | None] | None = None,
    ) -> SkillDraft:
        with Session(self.delegate.engine) as session:
            draft = session.get(SkillDraft, draft_id)
            if draft is None:
                raise ValueError(f"Draft {draft_id} not found")
            session.exec(  # type: ignore[call-overload]
                delete(SkillDraftFile).where(col(SkillDraftFile.skill_draft_id) == draft_id)
            )
            for path, content in files:
                session.add(SkillDraftFile(skill_draft_id=draft_id, path=path, content=content))
            if metadata is not None:
                if "description" in metadata:
                    draft.description = cast(str | None, metadata["description"])
                if "required_providers" in metadata:
                    draft.required_providers = cast(list[str] | None, metadata["required_providers"]) or []
            draft.updated_at = datetime.now(UTC)
            session.add(draft)
            session.commit()
            session.refresh(draft)
            return draft

    def delete_draft(self, draft_id: UUID) -> None:
        with Session(self.delegate.engine) as session:
            session.exec(delete(SkillDraft).where(col(SkillDraft.id) == draft_id))  # type: ignore[call-overload]
            session.commit()

    def publish_draft(
        self,
        skill_id: UUID,
        draft_id: UUID,
        files: list[tuple[str, str]],
        *,
        created_by: UUID | None = None,
    ) -> SkillVersion:
        """Publish a draft's files as the next immutable version, apply the
        draft's metadata to the skill row, then clear the draft slot, atomically."""
        with Session(self.delegate.engine) as session:
            current = session.exec(
                select(func.max(col(SkillVersion.version))).where(col(SkillVersion.skill_id) == skill_id)
            ).one()
            version = SkillVersion(
                skill_id=skill_id,
                version=(current or 0) + 1,
                created_by=created_by,
            )
            session.add(version)
            session.flush()
            for path, content in files:
                session.add(SkillFile(skill_version_id=version.id, path=path, content=content))
            # Apply the draft's metadata to the skill row so the published
            # version carries the description and required providers the author
            # staged in the draft.
            draft = session.get(SkillDraft, draft_id)
            if draft is not None:
                skill = session.get(Skill, skill_id)
                if skill is not None:
                    skill.description = draft.description
                    skill.required_providers = [SecretProvider(p) for p in draft.required_providers]
                    session.add(skill)
            session.exec(delete(SkillDraft).where(col(SkillDraft.id) == draft_id))  # type: ignore[call-overload]
            session.commit()
            session.refresh(version)
            return version

    def delete_version_by_id(self, version_id: UUID) -> None:
        """Delete one immutable version snapshot and its files (FK cascade).

        Protections (latest-assigned, last remaining) are enforced by the service
        before this is called.
        """
        with Session(self.delegate.engine) as session:
            session.exec(delete(SkillVersion).where(col(SkillVersion.id) == version_id))  # type: ignore[call-overload]
            session.commit()

    def get_aai_cli_skills(self) -> list[Skill]:
        with Session(self.delegate.engine) as session:
            query = select(Skill).where(col(Skill.source) == SkillSource.AAI_CLI)
            return list(session.exec(query).all())

    def find_all_global(self) -> list[Skill]:
        """Return every global Skill available to platform-owned resources."""
        with Session(self.delegate.engine) as session:
            query = select(Skill).where(col(Skill.organization_id).is_(None)).order_by(col(Skill.name).asc())
            return list(session.exec(query).all())

    def get_by_name_global(self, name: str) -> Skill | None:
        """Find a global (org_id=None) skill by name — used for seeder dedup."""
        with Session(self.delegate.engine) as session:
            query = select(Skill).where(col(Skill.name) == name).where(col(Skill.organization_id).is_(None))
            return session.exec(query).first()

    def find_accessible_for_org(self, org_id: UUID) -> list[Skill]:
        """Return all org-scoped + global skills without filtering or pagination."""
        with Session(self.delegate.engine) as session:
            query = select(Skill).where(
                or_(
                    col(Skill.organization_id) == org_id,
                    col(Skill.organization_id).is_(None),
                )
            )
            return list(session.exec(query).all())

    def find_org_scoped(self, org_id: UUID) -> list[Skill]:
        """Return only skills owned by an organization, without pagination."""
        with Session(self.delegate.engine) as session:
            query = select(Skill).where(col(Skill.organization_id) == org_id)
            return list(session.exec(query).all())

    def find_all_for_org(
        self,
        org_id: UUID,
        skill_filter: SkillFilter,
        pagination: Pagination,
    ) -> tuple[list[Skill], int]:
        """Return org-scoped skills + global AAI_CLI skills, filtered and paginated."""
        with Session(self.delegate.engine) as session:
            conditions = [
                or_(
                    col(Skill.organization_id) == org_id,
                    col(Skill.organization_id).is_(None),
                )
            ]
            if skill_filter.search:
                conditions.append(col(Skill.name).ilike(f"%{skill_filter.search}%"))
            if skill_filter.source is not None:
                conditions.append(col(Skill.source) == skill_filter.source)

            count_query = select(func.count()).select_from(Skill)
            for condition in conditions:
                count_query = count_query.where(condition)
            total = session.scalar(count_query) or 0

            query = select(Skill)
            for condition in conditions:
                query = query.where(condition)
            query = (
                query.order_by(col(Skill.created_at).asc())
                .offset((pagination.page - 1) * pagination.size)
                .limit(pagination.size)
            )
            return list(session.exec(query).all()), total

    def save(self, skill: Skill) -> Skill:
        self.delegate.save(skill)
        return skill

    def is_assigned_to_any_agent(self, skill_id: UUID, org_id: UUID) -> bool:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentSkill)
                .join(Agent, col(AgentSkill.agent_id) == col(Agent.id))
                .where(col(AgentSkill.skill_id) == skill_id)
                .where(col(Agent.organization_id) == org_id)
                .where(col(Agent.deleted_at).is_(None))
            )
            return session.exec(query).first() is not None

    def get_agent_skills_with_details(self, agent_id: UUID) -> list[tuple[AgentSkill, Skill]]:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentSkill, Skill)
                .join(Skill, col(AgentSkill.skill_id) == col(Skill.id))
                .where(col(AgentSkill.agent_id) == agent_id)
            )
            return list(session.exec(query).all())

    def get_many_by_ids(self, skill_ids: list[UUID]) -> list[Skill]:
        return self.delegate.find_many(Skill, skill_ids)

    def get_skills_for_agents_with_versions(self, agent_ids: list[UUID]) -> dict[UUID, list[PinnedSkill]]:
        """Each agent's assigned skills alongside their explicit pinned version.

        Joins ``Agent`` with ``deleted_at IS NULL`` so the batch load cannot
        leak skills belonging to soft-deleted agents even if stale ids are
        passed."""
        if not agent_ids:
            return {}
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentSkill, Skill)
                .join(Skill, col(AgentSkill.skill_id) == col(Skill.id))
                .join(Agent, col(AgentSkill.agent_id) == col(Agent.id))
                .where(col(AgentSkill.agent_id).in_(agent_ids))
                .where(col(Agent.deleted_at).is_(None))
            )
            result: dict[UUID, list[PinnedSkill]] = {}
            for agent_skill, skill in session.exec(query).all():
                result.setdefault(agent_skill.agent_id, []).append(
                    PinnedSkill(skill=skill, version=agent_skill.pinned_version)
                )
            return result
