from dataclasses import dataclass
from typing import NoReturn
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from sqlalchemy.exc import IntegrityError

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent, AgentStatus, AgentType
from api.domains.agents.repository import AgentRepository
from api.domains.agents.selection import ensure_personas_supported
from api.domains.agents.service import AgentService, _refuse_during_managed_update
from api.domains.auth.models import CurrentUserContext
from api.domains.communications.gateway_service import CommunicationsGatewayService
from api.domains.events import resolve_actor_identity
from api.domains.personas.keys import derive_key
from api.domains.personas.models import (
    DEFAULT_PERSONA_KEY,
    MAX_ACTIVE_PERSONAS,
    AgentPersona,
    AgentPersonaVersion,
    PersonaCreate,
    PersonaList,
    PersonaRead,
    PersonaSummary,
    PersonaUpdate,
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
    agents: AgentRepository
    lifecycle: AgentService
    gateway: CommunicationsGatewayService
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
        return self._read(self._require_active(agent, key, context))

    def list_versions(self, agent_id: UUID, key: str, context: CurrentUserContext) -> list[PersonaVersionRead]:
        agent = self.authorization.require_visible(context, agent_id)
        if key == DEFAULT_PERSONA_KEY:
            return []
        persona = self._require_active(agent, key, context)
        return [PersonaVersionRead.model_validate(row) for row in self.repository.list_versions(persona.id)]

    def create_persona(self, agent_id: UUID, payload: PersonaCreate, context: CurrentUserContext) -> PersonaRead:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        ensure_personas_supported(agent.agent_type)
        if not self.config.personas_enabled:
            raise HTTPException(status.HTTP_409_CONFLICT, "Personas are not available yet")
        with self.agents.lifecycle_lock(agent_id) as acquired:
            if not acquired:
                raise HTTPException(status.HTTP_409_CONFLICT, "An Agent lifecycle operation is already in progress")
            agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
            self._require_changeable(agent)
            if len(self._active_rows(agent, context)) >= MAX_ACTIVE_PERSONAS:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"An Agent can have at most {MAX_ACTIVE_PERSONAS} Personas",
                )
            scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_READ)
            key = derive_key(payload.display_name, self.repository.list_all_keys_in_scope(agent.id, scope))
            persona = AgentPersona(
                organization_id=agent.organization_id,
                agent_id=agent.id,
                key=key,
                display_name=payload.display_name,
                emoji=payload.emoji,
                current_version=1,
            )
            version = AgentPersonaVersion(
                organization_id=agent.organization_id,
                persona_id=persona.id,
                version=1,
                soul_md=payload.soul_md,
                identity_md=payload.identity_md,
                author_user_id=context.user.id,
            )
            actor = resolve_actor_identity(context, agent.organization_id)
            try:
                deliveries = self.repository.create_with_event(
                    persona, version, agent, actor, self._actor_display(context)
                )
            except IntegrityError:
                raise HTTPException(status.HTTP_409_CONFLICT, "That Persona already exists") from None
        self.lifecycle.event_delivery_dispatcher.enqueue_immediate(deliveries)
        return self._read(persona)

    def update_persona(
        self,
        agent_id: UUID,
        key: str,
        payload: PersonaUpdate,
        context: CurrentUserContext,
    ) -> PersonaRead:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        ensure_personas_supported(agent.agent_type)
        if key == DEFAULT_PERSONA_KEY:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "The Default Persona comes from the Agent's Template",
            )
        with self.agents.lifecycle_lock(agent_id) as acquired:
            if not acquired:
                raise HTTPException(status.HTTP_409_CONFLICT, "An Agent lifecycle operation is already in progress")
            agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
            persona = self._require_active(agent, key, context)
            self._require_changeable(agent)
            if payload.expected_version != persona.current_version:
                raise HTTPException(status.HTTP_409_CONFLICT, "This Persona has changed; reload it and try again")
            current = self._current_version(persona)
            text_changed = (current.soul_md, current.identity_md) != (payload.soul_md, payload.identity_md)
            details_changed = (persona.display_name, persona.emoji) != (payload.display_name, payload.emoji)
            if not text_changed and not details_changed:
                return self._read(persona)
            version = None
            if text_changed:
                version = AgentPersonaVersion(
                    organization_id=agent.organization_id,
                    persona_id=persona.id,
                    version=persona.current_version + 1,
                    soul_md=payload.soul_md,
                    identity_md=payload.identity_md,
                    author_user_id=context.user.id,
                )
            actor = resolve_actor_identity(context, agent.organization_id)
            updated, deliveries = self.repository.update_with_event(
                persona.id,
                payload.display_name,
                payload.emoji,
                version,
                agent,
                actor,
                self._actor_display(context),
            )
        self.lifecycle.event_delivery_dispatcher.enqueue_immediate(deliveries)
        return self._read(updated)

    def delete_persona(self, agent_id: UUID, key: str, context: CurrentUserContext) -> None:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        ensure_personas_supported(agent.agent_type)
        if key == DEFAULT_PERSONA_KEY:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The Default Persona can't be deleted")
        with self.agents.lifecycle_lock(agent_id) as acquired:
            if not acquired:
                raise HTTPException(status.HTTP_409_CONFLICT, "An Agent lifecycle operation is already in progress")
            agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
            persona = self._require_active(agent, key, context)
            self._require_changeable(agent)
            actor = resolve_actor_identity(context, agent.organization_id)
            deliveries, cancelled = self.repository.soft_delete_with_event(
                persona.id, agent, actor, self._actor_display(context)
            )
        self.lifecycle.event_delivery_dispatcher.enqueue_immediate(deliveries)
        self.gateway.announce_cancelled(agent.id, cancelled)

    def _require_changeable(self, agent: Agent) -> None:
        _refuse_during_managed_update(agent)
        if self.lifecycle.restore_points.has_blocking_operation(agent.id):
            raise HTTPException(status.HTTP_409_CONFLICT, "An Agent restore operation is in progress")
        if agent.status == AgentStatus.RUNNING:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Agent {agent.id} must be stopped before changing Personas")

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

    def _current_version(self, persona: AgentPersona) -> AgentPersonaVersion:
        version = self.repository.get_version(persona.id, persona.current_version)
        if version is None:
            self._raise_not_found(persona.key)
        return version

    def _read(self, persona: AgentPersona) -> PersonaRead:
        version = self._current_version(persona)
        return PersonaRead(
            **self._summary(persona).model_dump(),
            soul_md=version.soul_md,
            identity_md=version.identity_md,
        )

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
    def _actor_display(context: CurrentUserContext) -> str:
        return context.user.full_name or context.user.email

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
