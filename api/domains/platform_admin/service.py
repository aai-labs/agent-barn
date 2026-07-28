from dataclasses import dataclass

from injector import inject, singleton

from api.domains.auth.exceptions import ForbiddenException
from api.domains.users.models import User


@inject
@singleton
@dataclass
class PlatformAdminService:
    """Seam for platform-level authority.

    Callers depend on Platform Administrator authority instead of Organization ownership.
    """

    def is_platform_admin(self, user: User) -> bool:
        return user.is_platform_admin

    def require_platform_admin(
        self,
        user: User,
        *,
        detail: str = "This action requires platform administrator access.",
    ) -> None:
        if not self.is_platform_admin(user):
            raise ForbiddenException(detail=detail)
