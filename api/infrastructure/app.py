from injector import Module, provider, singleton

from api.infrastructure.clock import Clock
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.core.config import Config, get_config


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
    def provide_clock(self) -> Clock:
        return Clock.retrieve()
