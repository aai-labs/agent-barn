import pytest

from api.domains.rbac.catalog import ADMIN_ROLE_ID, PermissionKey
from api.domains.rbac.repository import RbacRepository
from api.tests.core.givenpy import given
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.rbac import role_lacks_permission

_GIVEN = [
    prepare_injector(),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
]


def test_temporary_missing_permission_is_restored_after_normal_exit():
    repository: RbacRepository

    with given(
        [
            *_GIVEN,
            role_lacks_permission(ADMIN_ROLE_ID, PermissionKey.TEMPLATE_MANAGE),
        ]
    ) as context:
        repository = context.injector.get(RbacRepository)
        assert not repository.has_permission(
            ADMIN_ROLE_ID, PermissionKey.TEMPLATE_MANAGE
        )

    assert repository.has_permission(ADMIN_ROLE_ID, PermissionKey.TEMPLATE_MANAGE)


def test_temporary_missing_permission_is_restored_after_exception():
    repository: RbacRepository

    with pytest.raises(RuntimeError):
        with given(
            [
                *_GIVEN,
                role_lacks_permission(ADMIN_ROLE_ID, PermissionKey.SKILL_MANAGE),
            ]
        ) as context:
            repository = context.injector.get(RbacRepository)
            assert not repository.has_permission(
                ADMIN_ROLE_ID, PermissionKey.SKILL_MANAGE
            )
            raise RuntimeError("exercise cleanup")

    assert repository.has_permission(ADMIN_ROLE_ID, PermissionKey.SKILL_MANAGE)
