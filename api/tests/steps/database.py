from dataclasses import dataclass

from sqlalchemy import text

from api.domains.agent_sizes.models import (
    STANDARD_CPU_LIMIT_MILLICORES,
    STANDARD_CPU_REQUEST_MILLICORES,
    STANDARD_MEMORY_LIMIT_BYTES,
    STANDARD_MEMORY_REQUEST_BYTES,
    STANDARD_SIZE_ID,
    STANDARD_SIZE_NAME,
    STANDARD_STORAGE_BYTES,
)
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
                    "TRUNCATE artifact_reference, artifact, artifact_bucket, platform_workflow_settings, memory_key_revocation, platform_memory_settings, platform_playbook_settings, platform_trial_settings, platform_billing_settings, platform_organization_settings, billing_checkout, billing_unapplied_payment, trial_grant, security_audit_record, gateway_audit_event, event_delivery, event_outbox_message, communication_operation_journal, skill, communication_delivery, agent_chat_message, communication_connection, tool_call, agent_template, platform_template_draft_skill, platform_template_draft, platform_template_skill, platform_template, platform_resource_limits, agent CASCADE"
                )
            )
            # The Agent Size catalog back to what the migration seeded: Standard, the default.
            conn.execute(text("DELETE FROM agent_sizes"))
            conn.execute(
                text(
                    "INSERT INTO agent_sizes (id, created_at, updated_at, name, cpu_request_millicores,"
                    " cpu_limit_millicores, memory_request_bytes, memory_limit_bytes, storage_bytes, enabled,"
                    " is_default, sort_order) VALUES (:id, now(), now(), :name, :cpu_request, :cpu_limit,"
                    " :memory_request, :memory_limit, :storage, true, true, 0)"
                ),
                {
                    "id": STANDARD_SIZE_ID,
                    "name": STANDARD_SIZE_NAME,
                    "cpu_request": STANDARD_CPU_REQUEST_MILLICORES,
                    "cpu_limit": STANDARD_CPU_LIMIT_MILLICORES,
                    "memory_request": STANDARD_MEMORY_REQUEST_BYTES,
                    "memory_limit": STANDARD_MEMORY_LIMIT_BYTES,
                    "storage": STANDARD_STORAGE_BYTES,
                },
            )
            conn.commit()
        delegate.delete_all(RefreshToken)
        delegate.delete_all(PasswordResetToken)
        delegate.delete_all(OrganizationUser)
        delegate.delete_all(Organization)
        delegate.delete_all(User)

    return step
