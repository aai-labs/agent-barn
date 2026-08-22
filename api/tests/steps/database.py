from dataclasses import dataclass

from sqlalchemy import text

from api.domains.auth.models import PasswordResetToken, RefreshToken
from api.domains.auth.repository import (
    PasswordResetTokenRepository,
    RefreshTokenRepository,
)
from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.models import User
from api.domains.users.organization_users.models import OrganizationUser
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.domains.users.repository import UserRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import LambdaWith


@dataclass
class CompositeCloseable:
    children: list

    def close(self):
        for child in self.children:
            if hasattr(child, "close"):
                child.close()


def database_repo_is_ready():
    def step(context):
        def open_db():
            repo_types = [
                OrganizationRepository,
                OrganizationUserRepository,
                UserRepository,
                RefreshTokenRepository,
                PasswordResetTokenRepository,
            ]

            context.repos = CompositeCloseable([context.injector.get(repo_type) for repo_type in repo_types])
            context.postgres_delegate = context.injector.get(PostgresRepositoryDelegate)

        def close_db():
            context.repos.close()
            context.postgres_delegate.close()

        return LambdaWith(open_db, close_db)

    return step


def database_is_clean():
    def step(context):
        delegate: PostgresRepositoryDelegate = context.postgres_delegate

        with delegate.engine.connect() as conn:
            conn.execute(
                text(
                    "TRUNCATE security_audit_record, event_delivery, event_outbox_message, skill, communication_delivery, agent_chat_message, communication_connection, tool_call, agent_template, platform_template_draft_skill, platform_template_draft, platform_template_skill, platform_template, agent CASCADE"
                )
            )
            conn.commit()
        delegate.delete_all(RefreshToken)
        delegate.delete_all(PasswordResetToken)
        delegate.delete_all(OrganizationUser)
        delegate.delete_all(Organization)
        delegate.delete_all(User)

    return step
