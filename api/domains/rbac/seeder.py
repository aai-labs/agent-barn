from dataclasses import dataclass

from injector import inject, singleton

from api.domains.rbac.repository import RbacRepository, RbacSeedConflictError

__all__ = ["RbacSeedConflictError", "RbacSeeder"]


@inject
@singleton
@dataclass
class RbacSeeder:
    repository: RbacRepository

    def seed(self) -> None:
        self.repository.ensure_system_catalogue()
