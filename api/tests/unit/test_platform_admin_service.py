from hamcrest import assert_that, calling, equal_to, raises

from api.domains.auth.exceptions import ForbiddenException
from api.domains.platform_admin.service import PlatformAdminService
from api.domains.users.models import User


def test_is_platform_admin_uses_current_platform_admin_storage():
    service = PlatformAdminService()
    user = User(email="admin@example.com", hashed_password="hash", is_superuser=True)

    assert_that(service.is_platform_admin(user), equal_to(True))


def test_require_platform_admin_rejects_non_admin_user():
    service = PlatformAdminService()
    user = User(email="user@example.com", hashed_password="hash", is_superuser=False)

    assert_that(
        calling(service.require_platform_admin).with_args(user),
        raises(ForbiddenException),
    )
