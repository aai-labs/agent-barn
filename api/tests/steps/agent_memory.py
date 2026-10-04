import hashlib
from uuid import uuid7

from sqlalchemy import text

from api.domains.agents.models import AgentStatus
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user


def agent_memory_api_setup(*steps):
    return [
        set_env_variable(
            {
                "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                "LITELLM_BASE_URL": "http://litellm:4000",
                "LITELLM_SECRET_NAME": "litellm",
                "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
                "SKIP_SLACK_TOKEN_VALIDATION": "true",
            }
        ),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(),
        use_org_for_auth(),
        *steps,
    ]


def two_agents():
    def step(context):
        there_is_an_agent(name="Billing", status=AgentStatus.RUNNING)(context)
        context.billing = context.agent
        there_is_an_agent(name="Triage", status=AgentStatus.RUNNING)(context)
        context.triage = context.agent

    return step


def purge_tasks_are_clean():
    def step(context):
        with context.injector.get(PostgresRepositoryDelegate).engine.begin() as connection:
            connection.execute(text("TRUNCATE agent_memory_purge"))

    return step


def signed_in_as(role: OrganizationRole, name: str = "Second User"):
    """Switch the authenticated actor to a new Membership in the same Organization."""

    def step(context):
        user_id = uuid7()
        there_is_a_user(
            id=user_id,
            name=name,
            email=f"{role.value.lower()}-{user_id}@example.com",
            role=role,
            organization_id=context.organization.id,
        )(context)
        there_is_an_access_token_for_user(user_id)(context)

    return step


def an_agent_created_by_the_current_member(name: str = "Member Agent"):
    def step(context):
        there_is_an_agent(
            name=name,
            created_by_user_id=context.user.id,
            creator_membership_id=context.organization_user.id,
        )(context)

    return step


def memory_is_enabled():
    def step(context):
        context.memory_key = "per-agent-memory-test-key"
        agent = context.agent
        agent.memory_enabled = True
        agent.memory_key_hash = hashlib.sha256(context.memory_key.encode()).hexdigest()
        context.injector.get(PostgresRepositoryDelegate).save(agent)

    return step
