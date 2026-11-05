from dataclasses import dataclass
from typing import NoReturn
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent, AgentType
from api.domains.auth.models import CurrentUserContext
from api.domains.personas.models import (
    DEFAULT_PERSONA_KEY,
    AgentPersona,
    PersonaList,
    PersonaRead,
    PersonaSummary,
    PersonaVersionRead,
)
from api.domains.personas.repository import PersonaRepository
from api.domains.rbac.catalog import PermissionKey
from api.domains.templates.renderer import render_template
from api.domains.templates.repository import TemplateRepository


@inject
@singleton
@dataclass
class PersonaService:
    repository: PersonaRepository
    templates: TemplateRepository
    authorization: AgentAuthorization
    config: Config

    def list_personas(self, agent_id: UUID, context: CurrentUserContext) -> PersonaList:
        agent = self.authorization.require_visible(context, agent_id)
        hermes = agent.agent_type == AgentType.HERMES
        rows = self._active_rows(agent, context) if hermes else []
        return PersonaList(
            enabled=hermes and self.config.personas_enabled,
            personas=[self._default_summary(agent), *[self._summary(row) for row in rows]],
        )

    def get_persona(self, agent_id: UUID, key: str, context: CurrentUserContext) -> PersonaRead:
        agent = self.authorization.require_visible(context, agent_id)
        if key == DEFAULT_PERSONA_KEY:
            return self._default_read(agent)
        persona = self._require_active(agent, key, context)
        version = self.repository.get_version(persona.id, persona.current_version)
        if version is None:
            self._raise_not_found(key)
        return PersonaRead(
            **self._summary(persona).model_dump(),
            soul_md=version.soul_md,
            identity_md=version.identity_md,
        )

    def list_versions(self, agent_id: UUID, key: str, context: CurrentUserContext) -> list[PersonaVersionRead]:
        agent = self.authorization.require_visible(context, agent_id)
        if key == DEFAULT_PERSONA_KEY:
            return []
        persona = self._require_active(agent, key, context)
        return [PersonaVersionRead.model_validate(row) for row in self.repository.list_versions(persona.id)]

    def _active_rows(self, agent: Agent, context: CurrentUserContext) -> list[AgentPersona]:
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_READ)
        return self.repository.list_active_in_scope(agent.id, scope)

    def _require_active(self, agent: Agent, key: str, context: CurrentUserContext) -> AgentPersona:
        if agent.agent_type != AgentType.HERMES:
            self._raise_not_found(key)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_READ)
        persona = self.repository.get_active_in_scope(agent.id, key, scope)
        if persona is None:
            self._raise_not_found(key)
        return persona

    def _default_read(self, agent: Agent) -> PersonaRead:
        template = self.templates.get_pinned_template(agent)
        if template is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent.id} has no pinned template",
            )
        rendered = render_template(template, agent.name)
        return PersonaRead(
            **self._default_summary(agent).model_dump(),
            soul_md=rendered.soul_md,
            identity_md=rendered.identity_md,
        )

    @staticmethod
    def _default_summary(agent: Agent) -> PersonaSummary:
        return PersonaSummary(
            id=None,
            key=DEFAULT_PERSONA_KEY,
            display_name=agent.name,
            emoji=None,
            is_default=True,
            current_version=None,
            updated_at=agent.updated_at,
        )

    @staticmethod
    def _summary(persona: AgentPersona) -> PersonaSummary:
        return PersonaSummary(
            id=persona.id,
            key=persona.key,
            display_name=persona.display_name,
            emoji=persona.emoji,
            is_default=False,
            current_version=persona.current_version,
            updated_at=persona.updated_at,
        )

    @staticmethod
    def _raise_not_found(key: str) -> NoReturn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Persona {key} not found")
