from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from injector import inject, singleton
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.agent_webhooks.models import (
    AgentWebhook,
    WebhookDeliveryPlatform,
    WebhookInvocation,
    WebhookInvocationRead,
    WebhookInvocationStatus,
)
from api.domains.agents.models import Agent
from api.domains.agents.repository import agent_scope_predicates
from api.domains.rbac.policy import AuthorizationScope
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import PaginatedItems, Pagination

# Longer than a whole dispatch (three 10s attempts plus backoff), so a RECEIVED row
# this old was abandoned by a crashed or restarted API process, not still in flight.
STALLED_DISPATCH_AFTER = timedelta(minutes=2)


class AgentWebhookConflictError(RuntimeError):
    pass


@inject
@singleton
@dataclass
class AgentWebhookRepository:
    delegate: PostgresRepositoryDelegate

    def list_active_in_scope(self, agent_id: UUID, authorization_scope: AuthorizationScope) -> list[AgentWebhook]:
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(AgentWebhook)
                    .join(Agent, col(Agent.id) == col(AgentWebhook.agent_id))
                    .where(
                        col(AgentWebhook.agent_id) == agent_id,
                        col(AgentWebhook.retired_at).is_(None),
                        *agent_scope_predicates(authorization_scope),
                    )
                    .order_by(col(AgentWebhook.created_at), col(AgentWebhook.id))
                ).all()
            )

    def get_active_in_scope(
        self,
        webhook_id: UUID,
        agent_id: UUID,
        authorization_scope: AuthorizationScope,
    ) -> AgentWebhook | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(AgentWebhook)
                .join(Agent, col(Agent.id) == col(AgentWebhook.agent_id))
                .where(
                    col(AgentWebhook.id) == webhook_id,
                    col(AgentWebhook.agent_id) == agent_id,
                    col(AgentWebhook.retired_at).is_(None),
                    *agent_scope_predicates(authorization_scope),
                )
            ).one_or_none()

    def get_enabled_for_ingress(self, webhook_id: UUID) -> AgentWebhook | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(AgentWebhook)
                .join(Agent, col(Agent.id) == col(AgentWebhook.agent_id))
                .where(
                    col(AgentWebhook.id) == webhook_id,
                    col(AgentWebhook.enabled).is_(True),
                    col(AgentWebhook.retired_at).is_(None),
                    col(Agent.deleted_at).is_(None),
                )
            ).one_or_none()

    def create(self, webhook: AgentWebhook) -> AgentWebhook:
        try:
            with Session(self.delegate.engine, expire_on_commit=False) as session:
                session.add(webhook)
                session.commit()
                session.refresh(webhook)
                return webhook
        except IntegrityError as exc:
            raise AgentWebhookConflictError("An active webhook with that name already exists") from exc

    def update(
        self,
        webhook_id: UUID,
        *,
        expected_revision: int,
        display_name: str | None = None,
        delivery_platform: WebhookDeliveryPlatform | None = None,
        enabled: bool | None = None,
        signing_secret_encrypted: str | None = None,
    ) -> AgentWebhook:
        try:
            with Session(self.delegate.engine, expire_on_commit=False) as session:
                webhook = session.exec(
                    select(AgentWebhook)
                    .where(
                        col(AgentWebhook.id) == webhook_id,
                        col(AgentWebhook.retired_at).is_(None),
                    )
                    .with_for_update()
                ).one_or_none()
                if webhook is None or webhook.revision != expected_revision:
                    raise AgentWebhookConflictError("Agent Webhook changed; refresh and retry")
                if display_name is not None:
                    webhook.display_name = display_name
                if delivery_platform is not None:
                    webhook.delivery_platform = delivery_platform
                if enabled is not None:
                    webhook.enabled = enabled
                if signing_secret_encrypted is not None:
                    webhook.signing_secret_encrypted = signing_secret_encrypted
                webhook.revision += 1
                webhook.updated_at = datetime.now(UTC)
                session.add(webhook)
                session.commit()
                session.refresh(webhook)
                return webhook
        except IntegrityError as exc:
            raise AgentWebhookConflictError("An active webhook with that name already exists") from exc

    def retire(self, webhook_id: UUID, *, expected_revision: int) -> bool:
        with Session(self.delegate.engine) as session:
            webhook = session.exec(
                select(AgentWebhook).where(col(AgentWebhook.id) == webhook_id).with_for_update()
            ).one_or_none()
            if webhook is None or webhook.retired_at is not None:
                return False
            if webhook.revision != expected_revision:
                raise AgentWebhookConflictError("Agent Webhook changed; refresh and retry")
            now = datetime.now(UTC)
            webhook.enabled = False
            webhook.signing_secret_encrypted = ""
            webhook.retired_at = now
            webhook.updated_at = now
            webhook.revision += 1
            session.add(webhook)
            session.commit()
            return True

    def accept_invocation(
        self,
        webhook: AgentWebhook,
        *,
        external_event_id: str | None,
        prompt: str,
    ) -> tuple[WebhookInvocation, bool]:
        try:
            with Session(self.delegate.engine, expire_on_commit=False) as session:
                current = session.exec(
                    select(AgentWebhook).where(col(AgentWebhook.id) == webhook.id).with_for_update()
                ).one_or_none()
                if (
                    current is None
                    or not current.enabled
                    or current.retired_at is not None
                    or current.revision != webhook.revision
                ):
                    raise PermissionError("Agent Webhook is no longer active")
                invocation = WebhookInvocation(
                    organization_id=current.organization_id,
                    agent_id=current.agent_id,
                    webhook_id=current.id,
                    external_event_id=external_event_id,
                    prompt=prompt,
                )
                session.add(invocation)
                session.commit()
                session.refresh(invocation)
                return invocation, False
        except IntegrityError:
            if external_event_id is None:
                raise
            with Session(self.delegate.engine) as session:
                existing = session.exec(
                    select(WebhookInvocation).where(
                        col(WebhookInvocation.webhook_id) == webhook.id,
                        col(WebhookInvocation.external_event_id) == external_event_id,
                    )
                ).one()
                return existing, True

    def record_dispatch_result(
        self,
        invocation_id: UUID,
        *,
        generation: int,
        attempts: int,
        native_job_id: str | None,
        error_code: str | None,
        error_message: str | None,
    ) -> WebhookInvocation:
        now = datetime.now(UTC)
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            invocation = session.exec(
                select(WebhookInvocation).where(col(WebhookInvocation.id) == invocation_id).with_for_update()
            ).one()
            if invocation.dispatch_generation != generation:
                # A retry superseded this dispatch; its own result owns the row.
                return invocation
            invocation.dispatch_attempt_count = attempts
            invocation.native_job_id = native_job_id
            invocation.last_error_code = error_code
            invocation.last_error_message = error_message
            invocation.updated_at = now
            if native_job_id is not None:
                invocation.status = WebhookInvocationStatus.SUBMITTED
                invocation.submitted_at = now
            else:
                invocation.status = WebhookInvocationStatus.DISPATCH_FAILED
                invocation.submitted_at = None
            session.add(invocation)
            session.commit()
            session.refresh(invocation)
            return invocation

    def prepare_retry_in_scope(
        self,
        invocation_id: UUID,
        webhook_id: UUID,
        agent_id: UUID,
        authorization_scope: AuthorizationScope,
    ) -> WebhookInvocation | None:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            invocation = session.exec(
                select(WebhookInvocation)
                .join(Agent, col(Agent.id) == col(WebhookInvocation.agent_id))
                .where(
                    col(WebhookInvocation.id) == invocation_id,
                    col(WebhookInvocation.webhook_id) == webhook_id,
                    col(WebhookInvocation.agent_id) == agent_id,
                    or_(
                        col(WebhookInvocation.status) == WebhookInvocationStatus.DISPATCH_FAILED,
                        and_(
                            col(WebhookInvocation.status) == WebhookInvocationStatus.RECEIVED,
                            col(WebhookInvocation.updated_at) < datetime.now(UTC) - STALLED_DISPATCH_AFTER,
                        ),
                    ),
                    *agent_scope_predicates(authorization_scope),
                )
                .with_for_update()
            ).one_or_none()
            if invocation is None:
                return None
            invocation.dispatch_generation += 1
            invocation.dispatch_attempt_count = 0
            invocation.status = WebhookInvocationStatus.RECEIVED
            invocation.native_job_id = None
            invocation.submitted_at = None
            invocation.last_error_code = None
            invocation.last_error_message = None
            invocation.updated_at = datetime.now(UTC)
            session.add(invocation)
            session.commit()
            session.refresh(invocation)
            return invocation

    def list_invocations_in_scope(
        self,
        webhook_id: UUID,
        agent_id: UUID,
        authorization_scope: AuthorizationScope,
        pagination: Pagination,
    ) -> PaginatedItems[WebhookInvocationRead]:
        predicates = (
            col(WebhookInvocation.webhook_id) == webhook_id,
            col(WebhookInvocation.agent_id) == agent_id,
            *agent_scope_predicates(authorization_scope),
        )
        with Session(self.delegate.engine) as session:
            total = (
                session.scalar(
                    select(func.count())
                    .select_from(WebhookInvocation)
                    .join(Agent, col(Agent.id) == col(WebhookInvocation.agent_id))
                    .where(*predicates)
                )
                or 0
            )
            rows = list(
                session.exec(
                    select(WebhookInvocation)
                    .join(Agent, col(Agent.id) == col(WebhookInvocation.agent_id))
                    .where(*predicates)
                    .order_by(col(WebhookInvocation.created_at).desc(), col(WebhookInvocation.id).desc())
                    .offset((pagination.page - 1) * pagination.size)
                    .limit(pagination.size)
                ).all()
            )
        return PaginatedItems[WebhookInvocationRead](
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=[WebhookInvocationRead.model_validate(row) for row in rows],
        )
