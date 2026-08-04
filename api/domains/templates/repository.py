from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlalchemy import or_
from sqlmodel import Session, col, delete, select, update

from api.domains.agents.models import (
    Agent,
    AgentTemplateSkill,
    PlatformTemplateDraftSkill,
    PlatformTemplateSkill,
)
from api.domains.skills.models import Skill
from api.domains.templates.models import (
    AgentTemplate,
    PlatformTemplate,
    PlatformTemplateAdminSummary,
    PlatformTemplateDraft,
    PlatformTemplateDraftRead,
    TemplateFilter,
    TemplateRead,
    TemplateRequiredSkillRead,
    TemplateSource,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import Pagination


@inject
@singleton
@dataclass
class TemplateRepository:
    delegate: PostgresRepositoryDelegate

    @staticmethod
    def to_read(
        template: AgentTemplate | PlatformTemplate,
        skills: list[tuple[Skill, str | None]] | None = None,
    ) -> TemplateRead:
        from api.domains.skills.models import SkillRead

        required_skills = [
            TemplateRequiredSkillRead(**SkillRead.model_validate(skill).model_dump(), group_key=group_key)
            for skill, group_key in (skills or [])
        ]
        if isinstance(template, PlatformTemplate):
            return TemplateRead(
                id=template.id,
                organization_id=None,
                template_slug=template.template_slug,
                template_name=template.template_name,
                template_source=TemplateSource.PRE_DEFINED,
                forked_from_platform_template_id=None,
                version=template.version,
                description=template.description,
                soul_md=template.soul_md,
                identity_md=template.identity_md,
                user_md=template.user_md,
                tools_md=template.tools_md,
                agents_md=template.agents_md,
                boot_md=template.boot_md,
                bootstrap_md=template.bootstrap_md,
                heartbeat_md=template.heartbeat_md,
                created_at=template.created_at,
                updated_at=template.updated_at,
                required_skills=required_skills,
            )
        return TemplateRead(
            id=template.id,
            organization_id=template.organization_id,
            template_slug=template.template_slug,
            template_name=template.template_name,
            template_source=template.template_source,
            forked_from_platform_template_id=template.forked_from_platform_template_id,
            fork_baseline_platform_template_id=template.fork_baseline_platform_template_id,
            version=template.version,
            description=template.description,
            soul_md=template.soul_md,
            identity_md=template.identity_md,
            user_md=template.user_md,
            tools_md=template.tools_md,
            agents_md=template.agents_md,
            boot_md=template.boot_md,
            bootstrap_md=template.bootstrap_md,
            heartbeat_md=template.heartbeat_md,
            created_at=template.created_at,
            updated_at=template.updated_at,
            required_skills=required_skills,
        )

    @staticmethod
    def to_draft_read(
        draft: PlatformTemplateDraft,
        skills: list[tuple[Skill, str | None]] | None = None,
    ) -> PlatformTemplateDraftRead:
        from api.domains.skills.models import SkillRead

        required_skills = [
            TemplateRequiredSkillRead(**SkillRead.model_validate(skill).model_dump(), group_key=group_key)
            for skill, group_key in (skills or [])
        ]
        return PlatformTemplateDraftRead(
            id=draft.id,
            template_slug=draft.template_slug,
            template_name=draft.template_name,
            description=draft.description,
            soul_md=draft.soul_md,
            identity_md=draft.identity_md,
            user_md=draft.user_md,
            tools_md=draft.tools_md,
            agents_md=draft.agents_md,
            boot_md=draft.boot_md,
            bootstrap_md=draft.bootstrap_md,
            heartbeat_md=draft.heartbeat_md,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
            required_skills=required_skills,
        )

    def get_org_template_by_slug_version(self, org_id: UUID, slug: str, version: int) -> AgentTemplate | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentTemplate)
                .where(col(AgentTemplate.organization_id) == org_id)
                .where(col(AgentTemplate.template_slug) == slug)
                .where(col(AgentTemplate.version) == version)
            )
            return session.exec(query).first()

    def get_latest_org_template(self, org_id: UUID, slug: str) -> AgentTemplate | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentTemplate)
                .where(col(AgentTemplate.organization_id) == org_id)
                .where(col(AgentTemplate.template_slug) == slug)
                .order_by(col(AgentTemplate.version).desc())
                .limit(1)
            )
            return session.exec(query).first()

    def find_org_versions(self, org_id: UUID, slug: str) -> list[AgentTemplate]:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentTemplate)
                .where(col(AgentTemplate.organization_id) == org_id)
                .where(col(AgentTemplate.template_slug) == slug)
                .order_by(col(AgentTemplate.version).desc())
            )
            return list(session.exec(query).all())

    def _latest_org_template_keys(
        self, org_id: UUID, template_filter: TemplateFilter
    ) -> list[tuple[UUID, str, str, int, TemplateSource]]:
        """Latest org-scoped version per slug, filtered (no pagination).

        Selects only identity columns (not the markdown body columns) since this
        is used to merge/sort/paginate across both template tables in memory;
        full rows are fetched afterwards for just the resulting page.
        """
        with Session(self.delegate.engine) as session:
            query = select(  # ty: ignore[no-matching-overload]
                col(AgentTemplate.id),
                col(AgentTemplate.template_slug),
                col(AgentTemplate.template_name),
                col(AgentTemplate.version),
                col(AgentTemplate.template_source),
            )
            query = (
                query.where(col(AgentTemplate.organization_id) == org_id)
                .distinct(col(AgentTemplate.template_slug))
                .order_by(
                    col(AgentTemplate.template_slug).asc(),
                    col(AgentTemplate.version).desc(),
                )
            )
            if template_filter.search:
                pattern = f"%{template_filter.search}%"
                query = query.where(
                    or_(
                        col(AgentTemplate.template_name).ilike(pattern),
                        col(AgentTemplate.template_slug).ilike(pattern),
                    )
                )
            if template_filter.source is not None:
                query = query.where(col(AgentTemplate.template_source) == template_filter.source)
            return list(session.exec(query).all())  # type: ignore[call-overload]

    def save_template(self, template: AgentTemplate) -> AgentTemplate:
        self.delegate.save(template)
        return template

    def save_org_template_version_with_skills(
        self,
        template: AgentTemplate,
        group_keys_by_skill_id: dict[UUID, str | None],
    ) -> AgentTemplate:
        """Persist one org template version and its requirements atomically."""
        with Session(self.delegate.engine) as session:
            session.add(template)
            session.flush()
            for skill_id, group_key in group_keys_by_skill_id.items():
                session.add(AgentTemplateSkill(template_id=template.id, skill_id=skill_id, group_key=group_key))
            session.commit()
            session.refresh(template)
        return template

    def save_org_template_skills(self, template_id: UUID, group_keys_by_skill_id: dict[UUID, str | None]) -> None:
        """Diff-sync a template's required-skill rows, including each row's
        group_key (None = standalone AND-required; shared non-None keys form
        an "at least one of" group)."""
        with Session(self.delegate.engine) as session:
            existing_rows = session.exec(
                select(AgentTemplateSkill).where(col(AgentTemplateSkill.template_id) == template_id)
            ).all()
            existing_by_id = {row.skill_id: row for row in existing_rows}
            for skill_id, row in existing_by_id.items():
                if skill_id not in group_keys_by_skill_id:
                    session.delete(row)
                elif row.group_key != group_keys_by_skill_id[skill_id]:
                    row.group_key = group_keys_by_skill_id[skill_id]
                    session.add(row)
            for skill_id, group_key in group_keys_by_skill_id.items():
                if skill_id not in existing_by_id:
                    session.add(AgentTemplateSkill(template_id=template_id, skill_id=skill_id, group_key=group_key))
            session.commit()

    def get_org_required_skills(self, template_id: UUID) -> list[tuple[Skill, str | None]]:
        with Session(self.delegate.engine) as session:
            query = (
                select(Skill, AgentTemplateSkill.group_key)
                .join(
                    AgentTemplateSkill,
                    col(AgentTemplateSkill.skill_id) == col(Skill.id),
                )
                .where(col(AgentTemplateSkill.template_id) == template_id)
                .order_by(col(AgentTemplateSkill.group_key).nulls_first(), col(Skill.name))
            )
            return list(session.exec(query).all())

    def get_org_required_skill_map(self, template_id: UUID) -> dict[UUID, str | None]:
        with Session(self.delegate.engine) as session:
            query = select(AgentTemplateSkill.skill_id, AgentTemplateSkill.group_key).where(
                col(AgentTemplateSkill.template_id) == template_id
            )
            return dict(session.exec(query).all())

    def get_org_required_skill_ids(self, template_id: UUID) -> set[UUID]:
        with Session(self.delegate.engine) as session:
            query = select(AgentTemplateSkill.skill_id).where(col(AgentTemplateSkill.template_id) == template_id)
            return set(session.exec(query).all())

    def get_platform_template_by_slug_version(self, slug: str, version: int) -> PlatformTemplate | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(PlatformTemplate)
                .where(col(PlatformTemplate.template_slug) == slug)
                .where(col(PlatformTemplate.version) == version)
            )
            return session.exec(query).first()

    def get_platform_template_by_id(self, template_id: UUID) -> PlatformTemplate | None:
        return self.delegate.find_by_id(PlatformTemplate, template_id)

    def get_latest_platform_template(self, slug: str) -> PlatformTemplate | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(PlatformTemplate)
                .where(col(PlatformTemplate.template_slug) == slug)
                .order_by(col(PlatformTemplate.version).desc())
                .limit(1)
            )
            return session.exec(query).first()

    def find_platform_versions(self, slug: str) -> list[PlatformTemplate]:
        with Session(self.delegate.engine) as session:
            query = (
                select(PlatformTemplate)
                .where(col(PlatformTemplate.template_slug) == slug)
                .order_by(col(PlatformTemplate.version).desc())
            )
            return list(session.exec(query).all())

    def _latest_platform_template_keys(
        self, template_filter: TemplateFilter
    ) -> list[tuple[UUID, str, str, int, TemplateSource]]:
        """Latest platform version per slug, filtered (no pagination).

        Selects only identity columns; see `_latest_org_template_keys`.
        """
        # Platform templates are always pre-defined; a custom filter excludes them.
        if template_filter.source is not None and template_filter.source != TemplateSource.PRE_DEFINED:
            return []
        with Session(self.delegate.engine) as session:
            query = (
                select(
                    col(PlatformTemplate.id),
                    col(PlatformTemplate.template_slug),
                    col(PlatformTemplate.template_name),
                    col(PlatformTemplate.version),
                )
                .distinct(col(PlatformTemplate.template_slug))
                .order_by(
                    col(PlatformTemplate.template_slug).asc(),
                    col(PlatformTemplate.version).desc(),
                )
            )
            if template_filter.search:
                pattern = f"%{template_filter.search}%"
                query = query.where(
                    or_(
                        col(PlatformTemplate.template_name).ilike(pattern),
                        col(PlatformTemplate.template_slug).ilike(pattern),
                    )
                )
            return [
                (id_, slug, name, version, TemplateSource.PRE_DEFINED)
                for id_, slug, name, version in session.exec(query).all()
            ]

    def save_platform_template(self, template: PlatformTemplate) -> PlatformTemplate:
        self.delegate.save(template)
        return template

    def save_platform_template_skills(self, template_id: UUID, group_keys_by_skill_id: dict[UUID, str | None]) -> None:
        """Diff-sync a platform template's required-skill rows, group-aware
        (see save_org_template_skills)."""
        with Session(self.delegate.engine) as session:
            existing_rows = session.exec(
                select(PlatformTemplateSkill).where(col(PlatformTemplateSkill.template_id) == template_id)
            ).all()
            existing_by_id = {row.skill_id: row for row in existing_rows}
            for skill_id, row in existing_by_id.items():
                if skill_id not in group_keys_by_skill_id:
                    session.delete(row)
                elif row.group_key != group_keys_by_skill_id[skill_id]:
                    row.group_key = group_keys_by_skill_id[skill_id]
                    session.add(row)
            for skill_id, group_key in group_keys_by_skill_id.items():
                if skill_id not in existing_by_id:
                    session.add(PlatformTemplateSkill(template_id=template_id, skill_id=skill_id, group_key=group_key))
            session.commit()

    def get_platform_required_skills(self, template_id: UUID) -> list[tuple[Skill, str | None]]:
        with Session(self.delegate.engine) as session:
            query = (
                select(Skill, PlatformTemplateSkill.group_key)
                .join(
                    PlatformTemplateSkill,
                    col(PlatformTemplateSkill.skill_id) == col(Skill.id),
                )
                .where(col(PlatformTemplateSkill.template_id) == template_id)
                .order_by(col(PlatformTemplateSkill.group_key).nulls_first(), col(Skill.name))
            )
            return list(session.exec(query).all())

    def get_platform_required_skill_map(self, template_id: UUID) -> dict[UUID, str | None]:
        with Session(self.delegate.engine) as session:
            query = select(PlatformTemplateSkill.skill_id, PlatformTemplateSkill.group_key).where(
                col(PlatformTemplateSkill.template_id) == template_id
            )
            return dict(session.exec(query).all())

    def get_platform_required_skill_ids(self, template_id: UUID) -> set[UUID]:
        with Session(self.delegate.engine) as session:
            query = select(PlatformTemplateSkill.skill_id).where(col(PlatformTemplateSkill.template_id) == template_id)
            return set(session.exec(query).all())

    def get_draft(self, slug: str) -> PlatformTemplateDraft | None:
        with Session(self.delegate.engine) as session:
            query = select(PlatformTemplateDraft).where(col(PlatformTemplateDraft.template_slug) == slug)
            return session.exec(query).first()

    def save_draft(self, draft: PlatformTemplateDraft) -> PlatformTemplateDraft:
        self.delegate.save(draft)
        return draft

    def delete_draft(self, draft_id: UUID) -> None:
        with Session(self.delegate.engine) as session:
            purge = delete(PlatformTemplateDraft).where(col(PlatformTemplateDraft.id) == draft_id)
            session.exec(purge)  # type: ignore[call-overload]
            session.commit()

    def save_draft_skills(self, draft_id: UUID, group_keys_by_skill_id: dict[UUID, str | None]) -> None:
        """Diff-sync a draft's required-skill rows, group-aware (see save_platform_template_skills)."""
        with Session(self.delegate.engine) as session:
            existing_rows = session.exec(
                select(PlatformTemplateDraftSkill).where(col(PlatformTemplateDraftSkill.draft_id) == draft_id)
            ).all()
            existing_by_id = {row.skill_id: row for row in existing_rows}
            for skill_id, row in existing_by_id.items():
                if skill_id not in group_keys_by_skill_id:
                    session.delete(row)
                elif row.group_key != group_keys_by_skill_id[skill_id]:
                    row.group_key = group_keys_by_skill_id[skill_id]
                    session.add(row)
            for skill_id, group_key in group_keys_by_skill_id.items():
                if skill_id not in existing_by_id:
                    session.add(PlatformTemplateDraftSkill(draft_id=draft_id, skill_id=skill_id, group_key=group_key))
            session.commit()

    def get_draft_required_skills(self, draft_id: UUID) -> list[tuple[Skill, str | None]]:
        with Session(self.delegate.engine) as session:
            query = (
                select(Skill, PlatformTemplateDraftSkill.group_key)
                .join(
                    PlatformTemplateDraftSkill,
                    col(PlatformTemplateDraftSkill.skill_id) == col(Skill.id),
                )
                .where(col(PlatformTemplateDraftSkill.draft_id) == draft_id)
                .order_by(col(PlatformTemplateDraftSkill.group_key).nulls_first(), col(Skill.name))
            )
            return list(session.exec(query).all())

    def get_draft_required_skill_map(self, draft_id: UUID) -> dict[UUID, str | None]:
        with Session(self.delegate.engine) as session:
            query = select(PlatformTemplateDraftSkill.skill_id, PlatformTemplateDraftSkill.group_key).where(
                col(PlatformTemplateDraftSkill.draft_id) == draft_id
            )
            return dict(session.exec(query).all())

    def list_platform_lineages_for_admin(self) -> list[PlatformTemplateAdminSummary]:
        """Every Platform Template lineage plus its draft status, for the admin authoring catalogue.

        Includes lineages that only exist as a draft (no published version yet).
        """
        with Session(self.delegate.engine) as session:
            latest_published = session.exec(
                select(
                    col(PlatformTemplate.template_slug),
                    col(PlatformTemplate.template_name),
                    col(PlatformTemplate.version),
                )
                .distinct(col(PlatformTemplate.template_slug))
                .order_by(col(PlatformTemplate.template_slug).asc(), col(PlatformTemplate.version).desc())
            ).all()
            drafts = session.exec(
                select(col(PlatformTemplateDraft.template_slug), col(PlatformTemplateDraft.template_name))
            ).all()

        published_by_slug = {slug: (name, version) for slug, name, version in latest_published}
        draft_slugs = {slug for slug, _ in drafts}
        summaries = [
            PlatformTemplateAdminSummary(
                template_slug=slug,
                template_name=name,
                latest_published_version=version,
                has_draft=slug in draft_slugs,
            )
            for slug, (name, version) in published_by_slug.items()
        ]
        draft_only_slugs = draft_slugs - published_by_slug.keys()
        summaries += [
            PlatformTemplateAdminSummary(
                template_slug=slug,
                template_name=name,
                latest_published_version=None,
                has_draft=True,
            )
            for slug, name in drafts
            if slug in draft_only_slugs
        ]
        return sorted(summaries, key=lambda s: s.template_slug)

    def resolve_template(self, org_id: UUID, slug: str, version: int) -> AgentTemplate | PlatformTemplate | None:
        org_template = self.get_org_template_by_slug_version(org_id, slug, version)
        if org_template is not None:
            return org_template
        return self.get_platform_template_by_slug_version(slug, version)

    def resolve_latest_template(self, org_id: UUID, slug: str) -> AgentTemplate | PlatformTemplate | None:
        org_latest = self.get_latest_org_template(org_id, slug)
        platform_latest = self.get_latest_platform_template(slug)
        if org_latest is None:
            return platform_latest
        if platform_latest is None:
            return org_latest
        # An org fork continues the platform lineage at a higher version, so the
        # higher version is the lineage's latest. A custom template cannot share
        # a slug with a platform template (enforced at create time).
        return org_latest if org_latest.version >= platform_latest.version else platform_latest

    def resolve_versions(self, org_id: UUID, slug: str) -> list[AgentTemplate | PlatformTemplate]:
        org_versions = self.find_org_versions(org_id, slug)
        platform_versions = self.find_platform_versions(slug)
        combined: list[AgentTemplate | PlatformTemplate] = list(org_versions) + list(platform_versions)
        combined.sort(key=lambda t: t.version, reverse=True)
        return combined

    def find_latest_templates(
        self,
        org_id: UUID,
        template_filter: TemplateFilter,
        pagination: Pagination,
    ) -> tuple[list[TemplateRead], int]:
        org_keys = self._latest_org_template_keys(org_id, template_filter)
        platform_keys = self._latest_platform_template_keys(template_filter)

        # Merge: a slug present in both resolves to the higher version (the org
        # fork shadows the platform template). Custom slugs never collide with
        # platform slugs (enforced at create time). Only identity columns are
        # touched here so this stays cheap regardless of markdown body size.
        by_slug: dict[str, tuple[UUID, str, str, int, TemplateSource, bool]] = {}
        for id_, slug, name, version, source in platform_keys:
            by_slug[slug] = (id_, slug, name, version, source, True)
        for id_, slug, name, version, source in org_keys:
            existing = by_slug.get(slug)
            if existing is None or version >= existing[3]:
                by_slug[slug] = (id_, slug, name, version, source, False)

        merged = list(by_slug.values())
        merged.sort(key=lambda t: (0 if t[4] == TemplateSource.PRE_DEFINED else 1, t[2]))
        total = len(merged)
        start = (pagination.page - 1) * pagination.size
        page_keys = merged[start : start + pagination.size]

        # Fetch full rows (including markdown bodies) for just this page.
        org_ids = [k[0] for k in page_keys if not k[5]]
        platform_ids = [k[0] for k in page_keys if k[5]]
        with Session(self.delegate.engine) as session:
            org_by_id = {
                t.id: t for t in session.exec(select(AgentTemplate).where(col(AgentTemplate.id).in_(org_ids))).all()
            }
            platform_by_id = {
                t.id: t
                for t in session.exec(select(PlatformTemplate).where(col(PlatformTemplate.id).in_(platform_ids))).all()
            }
        page: list[AgentTemplate | PlatformTemplate] = [
            platform_by_id[k[0]] if k[5] else org_by_id[k[0]] for k in page_keys
        ]

        # Bulk-fetch required skills for the page.
        skills_by_org = self._org_required_skills_for_templates(org_ids)
        skills_by_platform = self._platform_required_skills_for_templates(platform_ids)

        items = [
            self.to_read(
                t,
                skills_by_platform.get(t.id, []) if isinstance(t, PlatformTemplate) else skills_by_org.get(t.id, []),
            )
            for t in page
        ]
        return items, total

    def get_slugs_used_by_live_agents(self, org_id: UUID, slugs: list[str]) -> set[str]:
        if not slugs:
            return set()
        used: set[str] = set()
        with Session(self.delegate.engine) as session:
            org_query = (
                select(AgentTemplate.template_slug)
                .join(Agent, col(Agent.agent_template_id) == col(AgentTemplate.id))
                .distinct()
                .where(col(Agent.organization_id) == org_id)
                .where(col(Agent.deleted_at).is_(None))
                .where(col(AgentTemplate.template_slug).in_(slugs))
            )
            used.update(session.exec(org_query).all())

            platform_query = (
                select(PlatformTemplate.template_slug)
                .join(Agent, col(Agent.platform_template_id) == col(PlatformTemplate.id))
                .distinct()
                .where(col(Agent.organization_id) == org_id)
                .where(col(Agent.deleted_at).is_(None))
                .where(col(PlatformTemplate.template_slug).in_(slugs))
            )
            used.update(session.exec(platform_query).all())
        return used

    def is_org_lineage_used_by_live_agent(self, org_id: UUID, slug: str) -> bool:
        with Session(self.delegate.engine) as session:
            query = (
                select(Agent.id)
                .join(AgentTemplate, col(Agent.agent_template_id) == col(AgentTemplate.id))
                .where(col(Agent.organization_id) == org_id)
                .where(col(Agent.deleted_at).is_(None))
                .where(col(AgentTemplate.organization_id) == org_id)
                .where(col(AgentTemplate.template_slug) == slug)
                .limit(1)
            )
            return session.exec(query).first() is not None

    def purge_org_template_lineage(self, org_id: UUID, slug: str) -> None:
        """Delete every org-scoped version, detaching soft-deleted agents first.

        Live agents retain their RESTRICT pin and are checked before purge.
        Soft-deleted agents keep their row for audit/history, but no longer
        block deleting the template lineage they used to pin.
        """
        with Session(self.delegate.engine) as session:
            template_ids = session.exec(
                select(AgentTemplate.id)
                .where(col(AgentTemplate.organization_id) == org_id)
                .where(col(AgentTemplate.template_slug) == slug)
            ).all()
            if not template_ids:
                return
            detach = (
                update(Agent)
                .where(col(Agent.organization_id) == org_id)
                .where(col(Agent.deleted_at).is_not(None))
                .where(col(Agent.agent_template_id).in_(template_ids))
                .values(agent_template_id=None)
            )
            session.exec(detach)  # type: ignore[call-overload]
            purge = delete(AgentTemplate).where(col(AgentTemplate.id).in_(template_ids))
            session.exec(purge)  # type: ignore[call-overload]
            session.commit()

    def get_required_skills_for(self, template: AgentTemplate | PlatformTemplate) -> list[tuple[Skill, str | None]]:
        if isinstance(template, PlatformTemplate):
            return self.get_platform_required_skills(template.id)
        return self.get_org_required_skills(template.id)

    def get_required_skill_map_for(self, template: AgentTemplate | PlatformTemplate) -> dict[UUID, str | None]:
        if isinstance(template, PlatformTemplate):
            return self.get_platform_required_skill_map(template.id)
        return self.get_org_required_skill_map(template.id)

    def is_skill_required_by_any_template(self, skill_id: UUID) -> bool:
        with Session(self.delegate.engine) as session:
            org_q = select(AgentTemplateSkill).where(col(AgentTemplateSkill.skill_id) == skill_id)
            if session.exec(org_q).first() is not None:
                return True
            platform_q = select(PlatformTemplateSkill).where(col(PlatformTemplateSkill.skill_id) == skill_id)
            return session.exec(platform_q).first() is not None

    def _org_required_skills_for_templates(
        self, template_ids: list[UUID]
    ) -> dict[UUID, list[tuple[Skill, str | None]]]:
        if not template_ids:
            return {}
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentTemplateSkill, Skill)
                .join(Skill, col(AgentTemplateSkill.skill_id) == col(Skill.id))
                .where(col(AgentTemplateSkill.template_id).in_(template_ids))
                .order_by(col(AgentTemplateSkill.group_key).nulls_first(), col(Skill.name))
            )
            result: dict[UUID, list[tuple[Skill, str | None]]] = {}
            for ats, skill in session.exec(query).all():
                result.setdefault(ats.template_id, []).append((skill, ats.group_key))
            return result

    def _platform_required_skills_for_templates(
        self, template_ids: list[UUID]
    ) -> dict[UUID, list[tuple[Skill, str | None]]]:
        if not template_ids:
            return {}
        with Session(self.delegate.engine) as session:
            query = (
                select(PlatformTemplateSkill, Skill)
                .join(Skill, col(PlatformTemplateSkill.skill_id) == col(Skill.id))
                .where(col(PlatformTemplateSkill.template_id).in_(template_ids))
                .order_by(col(PlatformTemplateSkill.group_key).nulls_first(), col(Skill.name))
            )
            result: dict[UUID, list[tuple[Skill, str | None]]] = {}
            for pts, skill in session.exec(query).all():
                result.setdefault(pts.template_id, []).append((skill, pts.group_key))
            return result

    def get_pinned_template(self, agent: Agent) -> AgentTemplate | PlatformTemplate | None:
        if agent.agent_template_id is not None:
            with Session(self.delegate.engine) as session:
                return session.get(AgentTemplate, agent.agent_template_id)
        if agent.platform_template_id is not None:
            with Session(self.delegate.engine) as session:
                return session.get(PlatformTemplate, agent.platform_template_id)
        return None

    def get_pinned_template_info_for_agents(self, agents: list[Agent]) -> dict[UUID, tuple[str, int]]:
        """Bulk-resolve (slug, version) for each agent's pinned template."""
        result: dict[UUID, tuple[str, int]] = {}
        org_ids = [a.agent_template_id for a in agents if a.agent_template_id is not None]
        platform_ids = [a.platform_template_id for a in agents if a.platform_template_id is not None]

        org_by_id: dict[UUID, AgentTemplate] = {}
        if org_ids:
            with Session(self.delegate.engine) as session:
                for t in session.exec(select(AgentTemplate).where(col(AgentTemplate.id).in_(org_ids))).all():
                    org_by_id[t.id] = t
        platform_by_id: dict[UUID, PlatformTemplate] = {}
        if platform_ids:
            with Session(self.delegate.engine) as session:
                for t in session.exec(select(PlatformTemplate).where(col(PlatformTemplate.id).in_(platform_ids))).all():
                    platform_by_id[t.id] = t

        for a in agents:
            if a.agent_template_id is not None:
                t = org_by_id.get(a.agent_template_id)
                if t:
                    result[a.id] = (t.template_slug, t.version)
            elif a.platform_template_id is not None:
                t = platform_by_id.get(a.platform_template_id)
                if t:
                    result[a.id] = (t.template_slug, t.version)
        return result

    def get_required_skill_map_for_agents(self, agents: list[Agent]) -> dict[UUID, dict[UUID, str | None]]:
        """Bulk-fetch each agent's required-skill map (skill_id -> group_key),
        across both pin kinds, group-aware."""
        result: dict[UUID, dict[UUID, str | None]] = {a.id: {} for a in agents}
        org_template_ids = [a.agent_template_id for a in agents if a.agent_template_id is not None]
        platform_template_ids = [a.platform_template_id for a in agents if a.platform_template_id is not None]

        # Map template id -> list of agent ids that pin it.
        org_agents: dict[UUID, list[UUID]] = {}
        for a in agents:
            if a.agent_template_id is not None:
                org_agents.setdefault(a.agent_template_id, []).append(a.id)
        platform_agents: dict[UUID, list[UUID]] = {}
        for a in agents:
            if a.platform_template_id is not None:
                platform_agents.setdefault(a.platform_template_id, []).append(a.id)

        if org_template_ids:
            with Session(self.delegate.engine) as session:
                rows = session.exec(
                    select(AgentTemplateSkill).where(col(AgentTemplateSkill.template_id).in_(org_template_ids))
                ).all()
                for row in rows:
                    for agent_id in org_agents.get(row.template_id, []):
                        result[agent_id][row.skill_id] = row.group_key

        if platform_template_ids:
            with Session(self.delegate.engine) as session:
                rows = session.exec(
                    select(PlatformTemplateSkill).where(
                        col(PlatformTemplateSkill.template_id).in_(platform_template_ids)
                    )
                ).all()
                for row in rows:
                    for agent_id in platform_agents.get(row.template_id, []):
                        result[agent_id][row.skill_id] = row.group_key

        return result
