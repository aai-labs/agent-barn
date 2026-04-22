from injector import Injector
from sqlmodel import Session, col, select

from api.domains.auth.hashing import hash_text
from api.domains.auth.password_validation import validate_strong_password
from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.models import User
from api.domains.users.organization_users.models import (
    OrganizationRole,
    OrganizationUser,
)
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.domains.users.repository import UserRepository

DEMO_USERS = [
    {
        "email": "john@aai-labs.com",
        "full_name": "John Doe",
        "password": "StrongPass123",
        "organization_name": "Acme Imports",
    },
    {
        "email": "sara@aai-labs.com",
        "full_name": "Sara Smith",
        "password": "StrongPass123",
        "organization_name": "Northstar Logistics",
    },
    {
        "email": "david@aai-labs.com",
        "full_name": "David Lee",
        "password": "StrongPass123",
        "organization_name": "Bluewave Traders",
    },
]


def seed_demo_data(injector: Injector) -> None:
    """
    DEMO DATA ONLY:
    Remove this file for production deployments. It exists only to make
    the starter kit UI non-empty on first run.
    """
    user_repository = injector.get(UserRepository)
    organization_repository = injector.get(OrganizationRepository)
    organization_user_repository = injector.get(OrganizationUserRepository)

    with Session(user_repository.delegate.engine) as session:
        for demo_user in DEMO_USERS:
            validate_strong_password(demo_user["password"])

            user = user_repository.get_by_email_with_session(
                demo_user["email"], session
            )
            if user is None:
                user = User(
                    email=demo_user["email"],
                    full_name=demo_user["full_name"],
                    hashed_password=hash_text(demo_user["password"]),
                )
                user_repository.save_with_session(user, session)
            elif not user.full_name:
                user.full_name = demo_user["full_name"]
                user_repository.save_with_session(user, session)

            has_membership = session.exec(
                select(OrganizationUser).where(col(OrganizationUser.user_id) == user.id)
            ).first()
            if has_membership is None:
                organization = Organization(name=demo_user["organization_name"])
                organization_repository.save_with_session(organization, session)
                organization_user_repository.save_with_session(
                    OrganizationUser(
                        user_id=user.id,
                        organization_id=organization.id,
                        role=OrganizationRole.OWNER,
                    ),
                    session,
                )

        session.commit()
