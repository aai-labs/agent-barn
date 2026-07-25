from unittest.mock import Mock
from uuid import uuid7

from fastapi import HTTPException, status
from hamcrest import assert_that, calling, equal_to, raises
from sqlalchemy.exc import IntegrityError

from api.domains.organizations.models import Organization
from api.domains.users.organization_users.exceptions import (
    OneOwnerPerOrganizationException,
    UserAlreadyPartOfOrganizationException,
)
from api.domains.users.organization_users.models import (
    OrganizationRole,
    OrganizationUser,
)
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.domains.users.organization_users.service import OrganizationUserService


def test_organization_user_persists_fixed_role_directly():
    membership = OrganizationUser(
        user_id=uuid7(),
        organization_id=uuid7(),
        role=OrganizationRole.OWNER,
    )

    assert_that(membership.role, equal_to(OrganizationRole.OWNER))


def test_organization_user_service_raises_404_when_membership_missing():
    repository = Mock()
    repository.get_by_user_id_and_organization_id.return_value = None
    service = OrganizationUserService(
        organization_user_repository=repository,
        organization_repository=Mock(),
        auth_service=Mock(),
        user_repository=Mock(),
        permission_policy=Mock(),
    )

    assert_that(
        calling(service.find_by_user_id_and_organization_id).with_args(uuid7(), uuid7()),
        raises(HTTPException),
    )


def test_organization_user_service_maps_conflict_to_409():
    repository = Mock()
    repository.save.side_effect = UserAlreadyPartOfOrganizationException(uuid7(), uuid7())
    organization_repository = Mock()
    organization_repository.get.return_value = Organization(name="Org")
    service = OrganizationUserService(
        organization_user_repository=repository,
        organization_repository=organization_repository,
        auth_service=Mock(),
        user_repository=Mock(),
        permission_policy=Mock(),
    )
    org_user = OrganizationUser(
        user_id=uuid7(),
        organization_id=uuid7(),
        role=OrganizationRole.MEMBER,
    )

    try:
        service.create_user_organization(org_user)
        raise AssertionError("Expected HTTPException")
    except HTTPException as exc:
        assert_that(exc.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_organization_user_repository_maps_duplicate_member_constraint():
    delegate = Mock()
    delegate.save.side_effect = IntegrityError("stmt", "params", Exception("uq_user_organization"))
    repository = OrganizationUserRepository(delegate=delegate, outbox_repository=Mock())
    org_user = OrganizationUser(
        user_id=uuid7(),
        organization_id=uuid7(),
        role=OrganizationRole.MEMBER,
    )

    assert_that(
        calling(repository.save).with_args(org_user),
        raises(UserAlreadyPartOfOrganizationException),
    )


def test_organization_user_repository_maps_one_owner_constraint():
    delegate = Mock()
    delegate.save.side_effect = IntegrityError("stmt", "params", Exception("uq_user_organization_one_owner_per_org"))
    repository = OrganizationUserRepository(delegate=delegate, outbox_repository=Mock())
    org_user = OrganizationUser(
        user_id=uuid7(),
        organization_id=uuid7(),
        role=OrganizationRole.OWNER,
    )

    assert_that(
        calling(repository.save).with_args(org_user),
        raises(OneOwnerPerOrganizationException),
    )


def test_organization_user_repository_delete_all_by_user_id_returns_true_when_empty():
    delegate = Mock()
    repository = OrganizationUserRepository(delegate=delegate, outbox_repository=Mock())
    delegate.find_all.return_value = []

    result = repository.delete_all_by_user_id(uuid7())

    assert_that(result, equal_to(True))
    delegate.delete_many.assert_not_called()
