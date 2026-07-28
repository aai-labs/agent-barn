from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
from uuid import uuid7

import jwt
from hamcrest import assert_that, calling, equal_to, raises

from api.domains.auth.exceptions import (
    CredentialsException,
    EmailNotVerifiedException,
    ForbiddenException,
)
from api.domains.auth.utils import get_authenticated_user
from api.core.config import Config
from api.domains.users.models import User
from api.domains.users.repository import UserRepository
from api.domains.users.organization_users.models import (
    OrganizationRole,
    OrganizationUser,
)
from api.domains.users.organization_users.repository import OrganizationUserRepository


class DummyUserRepo:
    def __init__(self, user):
        self._user = user

    def get(self, _):
        return self._user


class DummyOrgUserRepo:
    def __init__(self, user_orgs):
        self._user_orgs = user_orgs

    def get_by_user_id(self, _):
        return self._user_orgs


def test_get_authenticated_user_returns_context():
    user = User(
        email="ctx@example.com",
        hashed_password="x",
        email_verified_at=datetime.now(timezone.utc),
    )
    org_user = OrganizationUser(
        user_id=user.id,
        organization_id=uuid7(),
        role=OrganizationRole.OWNER,
    )
    config = SimpleNamespace(secret_signing_key="x" * 32)
    token = jwt.encode(
        {"user_id": str(user.id), "token_type": "access"},
        config.secret_signing_key,
        algorithm="HS256",
    )

    context = get_authenticated_user(
        token=token,
        config=cast(Config, config),
        user_repository=cast(UserRepository, DummyUserRepo(user)),
        organization_user_repository=cast(OrganizationUserRepository, DummyOrgUserRepo([org_user])),
    )

    assert_that(context.user.id, equal_to(user.id))
    assert_that(context.organization_ids, equal_to([org_user.organization_id]))


def test_get_authenticated_user_rejects_unverified_user_when_required():
    user = User(email="unverified@example.com", hashed_password="x", email_verified_at=None)
    config = SimpleNamespace(secret_signing_key="x" * 32)
    token = jwt.encode(
        {"user_id": str(user.id), "token_type": "access"},
        config.secret_signing_key,
        algorithm="HS256",
    )

    assert_that(
        calling(get_authenticated_user).with_args(
            token=token,
            config=cast(Config, config),
            user_repository=cast(UserRepository, DummyUserRepo(user)),
            organization_user_repository=cast(OrganizationUserRepository, DummyOrgUserRepo([])),
            verified_required=True,
        ),
        raises(EmailNotVerifiedException),
    )


def test_get_authenticated_user_requires_role_for_org_context():
    user = User(
        email="member@example.com",
        hashed_password="x",
        email_verified_at=datetime.now(timezone.utc),
        is_platform_admin=True,
    )
    org_user = OrganizationUser(
        user_id=user.id,
        organization_id=uuid7(),
        role=OrganizationRole.MEMBER,
    )
    config = SimpleNamespace(secret_signing_key="x" * 32)
    token = jwt.encode(
        {"user_id": str(user.id), "token_type": "access"},
        config.secret_signing_key,
        algorithm="HS256",
    )

    assert_that(
        calling(get_authenticated_user).with_args(
            token=token,
            config=cast(Config, config),
            user_repository=cast(UserRepository, DummyUserRepo(user)),
            organization_user_repository=cast(OrganizationUserRepository, DummyOrgUserRepo([org_user])),
            organization_id=org_user.organization_id,
            organization_roles=[OrganizationRole.ADMIN],
        ),
        raises(ForbiddenException),
    )


def test_get_authenticated_user_rejects_platform_admin_without_org_membership():
    user = User(
        email="platform-admin@example.com",
        hashed_password="x",
        email_verified_at=datetime.now(timezone.utc),
        is_platform_admin=True,
    )
    config = SimpleNamespace(secret_signing_key="x" * 32)
    token = jwt.encode(
        {"user_id": str(user.id), "token_type": "access"},
        config.secret_signing_key,
        algorithm="HS256",
    )

    assert_that(
        calling(get_authenticated_user).with_args(
            token=token,
            config=cast(Config, config),
            user_repository=cast(UserRepository, DummyUserRepo(user)),
            organization_user_repository=cast(OrganizationUserRepository, DummyOrgUserRepo([])),
            organization_id=uuid7(),
        ),
        raises(ForbiddenException),
    )


def test_get_authenticated_user_rejects_invalid_token_type():
    user = User(
        email="token@example.com",
        hashed_password="x",
        email_verified_at=datetime.now(timezone.utc),
    )
    config = SimpleNamespace(secret_signing_key="x" * 32)
    token = jwt.encode(
        {"user_id": str(user.id), "token_type": "refresh"},
        config.secret_signing_key,
        algorithm="HS256",
    )

    assert_that(
        calling(get_authenticated_user).with_args(
            token=token,
            config=cast(Config, config),
            user_repository=cast(UserRepository, DummyUserRepo(user)),
            organization_user_repository=cast(OrganizationUserRepository, DummyOrgUserRepo([])),
        ),
        raises(CredentialsException),
    )
