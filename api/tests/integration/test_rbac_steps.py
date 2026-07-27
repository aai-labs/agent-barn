import pytest

from api.domains.rbac import policy as rbac_policy
from api.domains.rbac.catalog import OrganizationRole, PermissionKey
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
    with given(
        [
            *_GIVEN,
            role_lacks_permission(OrganizationRole.ADMIN, PermissionKey.TEMPLATE_MANAGE),
        ]
    ):
        assert not rbac_policy.organization_role_allows(OrganizationRole.ADMIN, PermissionKey.TEMPLATE_MANAGE)

    assert rbac_policy.organization_role_allows(OrganizationRole.ADMIN, PermissionKey.TEMPLATE_MANAGE)


def test_temporary_missing_permission_is_restored_after_exception():
    with pytest.raises(RuntimeError):
        with given(
            [
                *_GIVEN,
                role_lacks_permission(OrganizationRole.ADMIN, PermissionKey.SKILL_MANAGE),
            ]
        ):
            assert not rbac_policy.organization_role_allows(OrganizationRole.ADMIN, PermissionKey.SKILL_MANAGE)
            raise RuntimeError("exercise cleanup")

    assert rbac_policy.organization_role_allows(OrganizationRole.ADMIN, PermissionKey.SKILL_MANAGE)
