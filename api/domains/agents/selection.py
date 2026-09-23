"""Validating a configuration selection, apart from writing one.

Two callers need the same answer to "can this configuration be applied?". The
Agent service asks before it writes. The restore-point service asks before it
starts a Job that overwrites an Agent's files, because discovering afterwards
that the recorded configuration cannot be applied leaves the files replaced and
the configuration behind. Sharing the check keeps the two from drifting, which is
what the ticket asks for; the Agent service cannot simply be called from the
restore-point service, because it already depends on it.
"""

import fnmatch
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.agent_settings.lookup import AgentSettingsLookupService
from api.domains.agents.models import (
    Agent,
    AgentTemplateSelection,
    AgentType,
    CommandApprovalMode,
    SkillVersionPin,
)
from api.domains.agents.override_repository import AgentOverrideRepository
from api.domains.agents.repository import AgentRepository
from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.skills.repository import SkillRepository
from api.domains.templates.repository import TemplateRepository
from api.domains.templates.requirements import split_requirements

_OPENROUTER_MODEL_PREFIX = "litellm/openrouter/"


def is_model_allowed(model: str, allowlist: list[str]) -> bool:
    """Whether a stored model string (litellm/openrouter/<slug>) is permitted by
    the allowlist globs. An empty allowlist blocks everything. The litellm/
    gateway prefix is stripped so patterns match the OpenRouter slug.
    """
    if not allowlist:
        return False
    patterns = [p.strip().lower() for p in allowlist if p.strip()]
    if not patterns:
        return False
    slug = model.removeprefix(_OPENROUTER_MODEL_PREFIX).lower()
    return any(fnmatch.fnmatch(slug, pattern) for pattern in patterns)


@dataclass(frozen=True)
class ResolvedSelection:
    """Everything a selection needs to be written, once it is known to be valid."""

    selected_id: UUID
    template_key: str | None
    version: int | None
    skill_pins: list[SkillVersionPin]
    removed_skill_ids: list[UUID]
    scalar_updates: dict[str, object]


def ensure_approval_mode_supported(agent_type: AgentType, approval_mode: CommandApprovalMode | None) -> None:
    """OpenClaw has no user-configurable command-approval control; only Hermes
    maps approval_mode onto a runtime policy (see builders/hermes.py). An
    omitted value defers to the AgentCreate/AgentUpdate default of AUTO, which
    is a no-op for OpenClaw, but an explicit non-AUTO value would silently
    have no effect, so it is rejected rather than accepted and ignored.
    """
    if agent_type == AgentType.OPENCLAW and approval_mode is not None and approval_mode != CommandApprovalMode.AUTO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OpenClaw does not support command approval; approval_mode is Hermes-only.",
        )


def ensure_verbose_mode_supported(agent_type: AgentType, verbose_mode: bool | None) -> None:
    """OpenClaw has no progress-message channel wired up yet; only Hermes
    reads verbose_mode (see builders/hermes.py). An explicit True would
    silently have no effect, so it is rejected rather than accepted and ignored.
    """
    if agent_type == AgentType.OPENCLAW and verbose_mode:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OpenClaw does not support verbose progress messages; verbose_mode is Hermes-only.",
        )


@inject
@singleton
@dataclass
class SelectionValidator:
    repository: AgentRepository
    override_repository: AgentOverrideRepository
    template_repository: TemplateRepository
    skill_repository: SkillRepository
    organization_lookup: OrganizationLookupService
    agent_settings_lookup: AgentSettingsLookupService

    def resolve_skill_pins(
        self,
        skill_ids: list[UUID],
        pins: list[SkillVersionPin],
        current_skill_ids: set[UUID],
        removed_skill_ids: list[UUID],
        org_id: UUID,
        agent_id: UUID | None = None,
    ) -> list[SkillVersionPin]:
        """Resolve every agent assignment to an explicit pinned version.

        Added skills pin to a requested version when given, else to the skill's
        latest at apply time. Existing skills can be re-pinned through the same
        ``pins`` list. Every pin must reference a skill the agent ends up with,
        and the requested version must exist (it can later be deleted only after
        no agent pins it, so a valid pin never dangles from version deletion).
        """
        overlap = set(skill_ids) & set(removed_skill_ids)
        if overlap:
            ids = ", ".join(str(skill_id) for skill_id in sorted(overlap, key=str))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Skill ID(s) cannot be both added and removed: {ids}",
            )

        pin_map: dict[UUID, SkillVersionPin] = {}
        for pin in pins:
            if pin.skill_id in pin_map:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Duplicate skill version pin for skill {pin.skill_id}",
                )
            pin_map[pin.skill_id] = pin
        remaining_ids = current_skill_ids - set(removed_skill_ids)
        allowed_ids = remaining_ids | set(skill_ids)
        extras = set(pin_map) - allowed_ids
        if extras:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Skill version pins must reference a skill the agent ends up with",
            )

        requested_ids = set(skill_ids) | set(pin_map)
        if requested_ids:
            visible_skills = (
                self.skill_repository.find_visible_for_agent(agent_id, org_id)
                if agent_id is not None
                else self.skill_repository.find_accessible_for_org(org_id)
            )
            accessible_ids = {skill.id for skill in visible_skills}
            inaccessible_ids = requested_ids - accessible_ids
            if inaccessible_ids:
                skill_id = min(inaccessible_ids, key=str)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Skill {skill_id} not found",
                )

        resolved: list[SkillVersionPin] = []
        resolved_ids: set[UUID] = set()
        for skill_id in dict.fromkeys(skill_ids):
            pin = pin_map.get(skill_id)
            if pin is None:
                latest = self.skill_repository.get_latest_version(skill_id)
                pin = SkillVersionPin(skill_id=skill_id, version=latest.version if latest else 1)
            else:
                if self.skill_repository.get_version(skill_id, pin.version) is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Version {pin.version} not found for skill {skill_id}",
                    )
            resolved.append(pin)
            resolved_ids.add(skill_id)
        for pin in pins:
            if pin.skill_id in current_skill_ids and pin.skill_id not in resolved_ids:
                if self.skill_repository.get_version(pin.skill_id, pin.version) is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Version {pin.version} not found for skill {pin.skill_id}",
                    )
                resolved.append(pin)
                resolved_ids.add(pin.skill_id)
        return resolved

    def validate_required_skill_versions(
        self,
        required_map: Mapping[UUID, tuple[int, str | None]],
        pinned_versions: Mapping[UUID, int],
    ) -> None:
        """Require Template Skills to be present at the Template's exact pin."""
        standalone_ids, required_groups = split_requirements(required_map)
        for skill_id in standalone_ids:
            required_version, _ = required_map[skill_id]
            if pinned_versions.get(skill_id) != required_version:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Required template Skill {skill_id} must be pinned to version {required_version}",
                )
        for member_ids in required_groups.values():
            if any(pinned_versions.get(skill_id) == required_map[skill_id][0] for skill_id in member_ids):
                continue
            names = sorted(s.name for s in self.skill_repository.get_many_by_ids(list(member_ids)))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"One of these template Skills must be pinned to its required version: {', '.join(names)}",
            )

    def validate_override_requirements(
        self,
        agent: Agent,
        required_map: Mapping[UUID, tuple[int, str | None]],
        org_id: UUID,
        prospective_pins: Mapping[UUID, int] | None = None,
        check_providers: bool = True,
    ) -> None:
        """Check a template's required Skills against the assignments that will hold.

        ``prospective_pins`` is the pins *after* the caller's changes; without it the
        present assignments are used, which rejects a template and its own skills
        arriving together.
        """
        if not required_map:
            return
        accessible = {skill.id: skill for skill in self.skill_repository.find_visible_for_agent(agent.id, org_id)}
        missing_ids = set(required_map) - accessible.keys()
        if missing_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Override requires a Skill that is no longer available to this Organization",
            )
        if prospective_pins is None:
            assigned_rows = self.skill_repository.get_agent_skills_with_details(agent.id)
            assigned_versions = {skill.id: row.pinned_version for row, skill in assigned_rows}
        else:
            assigned_versions = dict(prospective_pins)
        assigned_ids = set(assigned_versions)
        standalone_ids, groups = split_requirements(required_map)

        # Per the group contract: a group needs one member, not all of them.
        if standalone_ids - assigned_ids:
            missing = ", ".join(sorted(accessible[skill_id].name for skill_id in standalone_ids - assigned_ids))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Required template skills must be assigned to the Agent: {missing}",
            )
        for group_key, member_ids in sorted(groups.items()):
            if not member_ids & assigned_ids:
                names = ", ".join(sorted(accessible[skill_id].name for skill_id in member_ids))
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"At least one of these template skills must be assigned to the Agent: {names}",
                )

        if prospective_pins is not None:
            self.validate_required_skill_versions(required_map, assigned_versions)

        if not check_providers:
            return

        # Only for what the Agent actually has: an unchosen alternative needs none.
        satisfying_ids = (standalone_ids | {skill_id for members in groups.values() for skill_id in members}) & (
            assigned_ids
        )
        providers = {secret.provider for secret in self.repository.get_secrets_for_agent(agent.id)}
        for skill_id in sorted(satisfying_ids, key=lambda candidate: accessible[candidate].name):
            missing_providers = set(accessible[skill_id].required_providers) - providers
            if missing_providers:
                names = ", ".join(sorted(provider.value for provider in missing_providers))
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Required Skill '{accessible[skill_id].name}' needs configured providers: {names}",
                )

    def validate_incoming_skill_providers(
        self,
        agent: Agent,
        incoming_skill_ids: Collection[UUID],
    ) -> None:
        """Skills this request adds or re-pins must have their providers configured.

        Only the incoming ones, as `update_agent` does. `Skill.required_providers`
        is the *latest* version's requirement, refreshed whenever a version is
        published, so judging every assignment by it would let a requirement added
        to a Skill the Agent does not even use block an unrelated template switch.
        """
        if not incoming_skill_ids:
            return
        skills = self.skill_repository.get_many_by_ids(list(incoming_skill_ids))
        providers = {secret.provider for secret in self.repository.get_secrets_for_agent(agent.id)}
        for skill in sorted(skills, key=lambda candidate: candidate.name):
            missing = [provider for provider in skill.required_providers if provider not in providers]
            if missing:
                names = ", ".join(sorted(str(provider) for provider in missing))
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Skill '{skill.name}' requires providers that are not configured: {names}",
                )

    def ensure_model_allowed(self, model: str | None, org_id: UUID) -> None:
        """Rejects models outside the allowlist. litellm is cluster-internal, so
        create/update are the only paths that can set an agent's model; enforcing
        here is sufficient. An empty/None model defers to the resolved default.

        The resolved default is admitted whatever the allowlist says. When the
        Organization set its own default that is already true by invariant; the case
        this covers is an Organization following a platform default its allowlist
        does not cover, where the model picker offers that default and rejecting it
        would make the one pre-selected option unsavable.
        """
        if model:
            allowed_models = self.organization_lookup.get_allowed_models(org_id)
            if allowed_models is None:
                raise HTTPException(status_code=404, detail="Organization not found")
            if is_model_allowed(model, allowed_models):
                return
            if model == self.agent_settings_lookup.resolve_default_model(org_id):
                return
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Model '{model}' is not in the allowed model list",
            )

    def resolve(self, agent: Agent, data: AgentTemplateSelection, org_id: UUID) -> ResolvedSelection:
        """Validate a selection completely, without writing any of it.

        Raises the same errors the write path raises, so a caller that resolves
        first and writes later cannot be refused for a reason it could not have
        seen up front.
        """
        selected_id: UUID
        selected_template_key: str | None
        selected_version: int | None
        required_map: Mapping[UUID, tuple[int, str | None]]

        if data.selection_type == "platform":
            assert data.template_key is not None and data.template_version is not None
            platform = self.template_repository.get_platform_template_by_key_version(
                data.template_key,
                data.template_version,
            )
            if platform is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Platform Template Version not found")
            selected_id = platform.id
            selected_template_key = platform.template_key
            selected_version = platform.version
            required_map = self.template_repository.get_required_skill_map_for(platform)
        elif data.selection_type == "organization":
            assert data.template_key is not None and data.template_version is not None
            organization = self.template_repository.get_org_template_by_key_version(
                org_id,
                data.template_key,
                data.template_version,
            )
            if organization is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Organization Template Version not found",
                )
            selected_id = organization.id
            selected_template_key = organization.template_key
            selected_version = organization.version
            required_map = self.template_repository.get_required_skill_map_for(organization)
        else:
            assert data.override_version is not None
            override = self.override_repository.get_version(agent.id, org_id, data.override_version)
            if override is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Agent Template Override Version not found",
                )
            selected_id = override.id
            selected_template_key = None
            selected_version = override.version
            required_map = self.override_repository.get_version_skill_map(override.id)

        updated = data.model_dump(exclude_unset=True)
        if "approval_mode" in updated:
            ensure_approval_mode_supported(agent.agent_type, data.approval_mode)
        if "verbose_mode" in updated:
            ensure_verbose_mode_supported(agent.agent_type, data.verbose_mode)
        if "model" in updated:
            self.ensure_model_allowed(data.model, org_id)

        current_pins = {row.skill_id: row.pinned_version for row in self.repository.get_skills_for_agent(agent.id)}
        resolved_skill_pins = self.resolve_skill_pins(
            data.skill_ids,
            data.skill_versions,
            set(current_pins),
            data.removed_skill_ids,
            org_id,
            agent.id,
        )
        prospective_pins = dict(current_pins)
        prospective_pins.update({pin.skill_id: pin.version for pin in resolved_skill_pins})
        for skill_id in data.removed_skill_ids:
            prospective_pins.pop(skill_id, None)

        # Credentials are checked only for what this request brings in, below.
        # `Skill.required_providers` is the lineage's *latest* requirement, so judging
        # every assigned required Skill by it would block a plain template switch on a
        # credential added to a Skill version the Agent does not use.
        self.validate_override_requirements(agent, required_map, org_id, prospective_pins, check_providers=False)
        self.validate_incoming_skill_providers(agent, [pin.skill_id for pin in resolved_skill_pins])

        scalar_updates: dict[str, object] = {
            field: updated[field] for field in ("approval_mode", "verbose_mode") if field in updated
        }
        if "model" in updated:
            # Non-nullable column; "" is the sentinel for the Organization default.
            scalar_updates["model"] = updated["model"] or ""

        return ResolvedSelection(
            selected_id=selected_id,
            template_key=selected_template_key,
            version=selected_version,
            skill_pins=resolved_skill_pins,
            removed_skill_ids=list(data.removed_skill_ids),
            scalar_updates=scalar_updates,
        )
