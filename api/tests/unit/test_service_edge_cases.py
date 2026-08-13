from typing import cast
from unittest.mock import Mock
from uuid import uuid7

from fastapi import HTTPException, status
from hamcrest import assert_that, calling, equal_to, raises
from pydantic import PostgresDsn

from api.core.config import Config
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.repository import RefreshTokenRepository
from api.domains.organizations.models import OrganizationUpdate
from api.domains.organizations.repository import OrganizationRepository
from api.domains.organizations.service import OrganizationService
from api.domains.users.models import User
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.domains.users.organization_users.service import OrganizationUserService
from api.domains.users.repository import UserRepository
from api.domains.users.service import UserService


def build_user_service() -> tuple[
    UserService,
    Mock,
    Mock,
    Mock,
    Mock,
]:
    user_repository = Mock(spec=UserRepository)
    organization_user_service = Mock(spec=OrganizationUserService)
    organization_user_repository = Mock(spec=OrganizationUserRepository)
    organization_repository = Mock(spec=OrganizationRepository)
    refresh_token_repository = Mock(spec=RefreshTokenRepository)
    config = Config(
        db_connection_url=cast(PostgresDsn, "postgresql://postgres:postgres@localhost:5432/test"),
        secret_signing_key="x" * 32,
        platform_admin_credentials="admin@example.com:StrongPass123",
        email_server_credential="noreply@example.com:password",
        email_smtp_server="smtp.example.com",
    )
    service = UserService(
        user_repository=cast(UserRepository, user_repository),
        organization_user_service=cast(OrganizationUserService, organization_user_service),
        organization_user_repository=cast(OrganizationUserRepository, organization_user_repository),
        organization_repository=cast(OrganizationRepository, organization_repository),
        refresh_token_repository=cast(RefreshTokenRepository, refresh_token_repository),
        config=config,
        event_delivery_dispatcher=Mock(),
        auth_service=Mock(),
    )
    return (
        service,
        user_repository,
        organization_user_service,
        organization_user_repository,
        refresh_token_repository,
    )


def test_get_user_not_found_raises_404():
    service, user_repository, _, _, _ = build_user_service()
    user_id = uuid7()
    user_repository.get.return_value = None

    try:
        service.get_user(user_id)
        raise AssertionError("Expected HTTPException")
    except HTTPException as exc:
        assert_that(exc.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_to_user_read_without_memberships_returns_empty_memberships():
    service, _, organization_user_service, _, _ = build_user_service()
    user = User(email="user@example.com", hashed_password="hash")
    organization_user_service.find_by_user_id.return_value = []

    user_read = service.to_user_read(user)

    assert_that(user_read.organization_users, equal_to([]))
    organization_user_service.find_by_user_id.assert_called_once_with(user.id)


def test_delete_user_deletes_refresh_tokens_memberships_and_user():
    (
        service,
        user_repository,
        _,
        organization_user_repository,
        refresh_token_repository,
    ) = build_user_service()
    user = User(email="user@example.com", hashed_password="hash")
    refresh_tokens = [Mock(), Mock()]
    user_repository.get.return_value = user
    refresh_token_repository.get_by_user.return_value = refresh_tokens

    service.delete_user(user.id, uuid7())

    refresh_token_repository.delete_all_by.assert_called_once_with(refresh_tokens)
    organization_user_repository.delete_all_by_user_id.assert_called_once_with(user.id)
    user_repository.delete.assert_called_once_with(user.id)


def test_organization_service_update_not_found_raises_404():
    repo = Mock()
    repo.get.return_value = None
    org_service = OrganizationService(
        organization_repository=repo,
        agent_service=Mock(),
        permission_policy=Mock(),
        event_delivery_dispatcher=Mock(),
    )
    platform_admin = User(email="root@example.com", hashed_password="x", is_platform_admin=True)
    context = CurrentUserContext(user=platform_admin)

    assert_that(
        calling(org_service.update_organization).with_args(uuid7(), OrganizationUpdate(name="new"), context),
        raises(HTTPException),
    )
