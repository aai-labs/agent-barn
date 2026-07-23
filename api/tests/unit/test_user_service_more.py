from datetime import datetime, timezone
from typing import cast
from unittest.mock import Mock
from uuid import uuid7

from fastapi import HTTPException, status
from hamcrest import assert_that, calling, equal_to, raises
from pydantic import PostgresDsn

from api.core.config import Config
from api.domains.auth.hashing import hash_text
from api.domains.auth.repository import RefreshTokenRepository
from api.domains.organizations.models import OrganizationRead
from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.models import User, UserPasswordChange, UserUpdate
from api.domains.users.organization_users.models import (
    OrganizationRole,
    OrganizationUserRead,
)
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
        super_user_credentials="admin@example.com:StrongPass123",
        super_user_full_name="Super User",
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
    )
    organization_user_service.find_by_user_id.return_value = []
    return (
        service,
        user_repository,
        organization_user_service,
        organization_user_repository,
        refresh_token_repository,
    )


def test_ensure_default_superuser_returns_existing_user():
    service, user_repository, _, _, _ = build_user_service()
    existing = User(
        email="admin@example.com",
        hashed_password=hash_text("StrongPass123"),
        full_name="Super User",
        email_verified_at=None,
    )
    user_repository.get_superuser.return_value = existing

    result = service.ensure_default_superuser()

    assert_that(result, equal_to(existing))
    user_repository.save.assert_not_called()


def test_ensure_default_superuser_does_not_update_existing():
    service, user_repository, _, _, _ = build_user_service()
    existing = User(
        email="different@example.com",
        hashed_password=hash_text("DifferentPass999"),
        full_name="Different Name",
    )
    user_repository.get_superuser.return_value = existing

    result = service.ensure_default_superuser()

    assert_that(result, equal_to(existing))
    assert_that(result.email, equal_to("different@example.com"))
    user_repository.save.assert_not_called()


def test_ensure_default_superuser_creates_when_missing():
    service, user_repository, _, _, _ = build_user_service()
    user_repository.get_superuser.return_value = None
    user_repository.save.side_effect = lambda user: user

    result = service.ensure_default_superuser()

    assert_that(result.email, equal_to("admin@example.com"))
    assert_that(result.is_superuser, equal_to(True))
    user_repository.save.assert_called_once()


def test_create_superuser_sets_superuser_and_no_verified_timestamp():
    service, user_repository, _, _, _ = build_user_service()
    user_repository.save.side_effect = lambda user: user

    user = service.create_superuser(email="admin2@example.com", password="StrongPass123")

    assert_that(user.is_superuser, equal_to(True))
    assert user.email_verified_at is None


def test_to_user_read_with_organization_fetches_memberships():
    service, _, organization_user_service, _, _ = build_user_service()
    user = User(email="u@example.com", hashed_password="hash")
    org_id = uuid7()
    now = datetime.now(timezone.utc)
    org_user_read = OrganizationUserRead(
        id=uuid7(),
        created_at=now,
        updated_at=now,
        user_id=user.id,
        organization_id=org_id,
        role=OrganizationRole.OWNER,
        organization=OrganizationRead(
            id=org_id,
            created_at=now,
            updated_at=now,
            name="Org",
            description=None,
            is_default=False,
            owner_email=None,
            owner_name=None,
        ),
    )
    organization_user_service.find_by_user_id.return_value = [org_user_read]

    result = service.to_user_read(user)

    organization_user_service.find_by_user_id.assert_called_once_with(user.id)
    assert_that(result.organization_users, equal_to([org_user_read]))


def test_update_current_user_persists_changes():
    service, user_repository, _, _, _ = build_user_service()
    user = User(email="u@example.com", hashed_password="hash", full_name="Old")
    user_repository.get.return_value = user
    user_repository.save.return_value = user

    result = service.update_current_user(user.id, UserUpdate(full_name="New Name"))

    user_repository.save.assert_called_once()
    assert_that(result.full_name, equal_to("New Name"))


def test_verify_user_password_raises_on_invalid_password():
    service, user_repository, _, _, _ = build_user_service()
    user = User(email="u@example.com", hashed_password=hash_text("correct"))
    user_repository.get.return_value = user

    assert_that(
        calling(service.verify_user_password).with_args(user.id, "wrong"),
        raises(HTTPException),
    )


def test_change_password_rejects_wrong_old_password():
    service, user_repository, _, _, _ = build_user_service()
    user = User(email="u@example.com", hashed_password=hash_text("correct"))
    user_repository.get.return_value = user

    assert_that(
        calling(service.change_password).with_args(
            user.id,
            UserPasswordChange(
                old_password="wrong",
                new_password="NewStrongPass123",
            ),
        ),
        raises(HTTPException),
    )


def test_change_password_updates_hash_and_stamp_on_success():
    service, user_repository, _, _, _ = build_user_service()
    old_stamp = "old-stamp"
    user = User(
        email="u@example.com",
        hashed_password=hash_text("OldStrongPass123"),
        security_stamp=old_stamp,
    )
    user_repository.get.return_value = user

    service.change_password(
        user.id,
        UserPasswordChange(
            old_password="OldStrongPass123",
            new_password="NewStrongPass123",
        ),
    )

    user_repository.save.assert_called_once()
    assert user.hashed_password != hash_text("OldStrongPass123")
    assert user.security_stamp != old_stamp


def test_get_user_by_id_and_organization_id_not_found_raises():
    service, user_repository, _, _, _ = build_user_service()
    user_repository.get_by_id_and_organization_id.return_value = None

    try:
        service.get_user_by_id_and_organization_id(uuid7(), uuid7())
        raise AssertionError("Expected HTTPException")
    except HTTPException as exc:
        assert_that(exc.status_code, equal_to(status.HTTP_404_NOT_FOUND))
