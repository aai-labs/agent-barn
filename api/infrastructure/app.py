from injector import Module, provider, singleton

from api.core.config import Config, get_config
from api.domains.agents.event_handlers import AgentLifecycleEmailHandler
from api.domains.events.constants import EVENT_DELIVERY_PROCESSING_STALE_SECONDS
from api.domains.events.handlers import EventHandlerRegistry
from api.domains.events.processor import EventDeliveryProcessor
from api.domains.events.reconciliation import EventDeliveryReconciler
from api.domains.events.repository import OutboxMessageRepository
from api.domains.events.security_audit import SecurityAuditProjection
from api.domains.events.transport import EventDeliveryTransport
from api.infrastructure.clock import Clock
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


class AppModule(Module):
    @provider
    @singleton
    def provide_config(self) -> Config:
        return get_config()

    @provider
    @singleton
    def provide_postgres_delegate(self, config: Config) -> PostgresRepositoryDelegate:
        return PostgresRepositoryDelegate(config)

    @provider
    @singleton
    def provide_kubernetes_client(self, config: Config) -> KubernetesClient:
        return KubernetesClient(config)

    @provider
    @singleton
    def provide_event_handler_registry(
        self,
        agent_lifecycle_email_handler: AgentLifecycleEmailHandler,
        security_audit_projection: SecurityAuditProjection,
    ) -> EventHandlerRegistry:
        return EventHandlerRegistry([agent_lifecycle_email_handler, security_audit_projection])

    @provider
    @singleton
    def provide_event_delivery_transport(self, config: Config) -> EventDeliveryTransport:
        return EventDeliveryTransport(config)

    @provider
    def provide_event_delivery_reconciler(
        self,
        repository: OutboxMessageRepository,
        transport: EventDeliveryTransport,
    ) -> EventDeliveryReconciler:
        return EventDeliveryReconciler(repository=repository, transport=transport)

    @provider
    def provide_event_delivery_processor(
        self,
        repository: OutboxMessageRepository,
        handlers: EventHandlerRegistry,
    ) -> EventDeliveryProcessor:
        return EventDeliveryProcessor(
            repository=repository,
            handlers=handlers,
            processing_stale_seconds=EVENT_DELIVERY_PROCESSING_STALE_SECONDS,
        )

    @provider
    def provide_clock(self) -> Clock:
        return Clock.retrieve()
