from uuid import uuid4

from hamcrest import assert_that, equal_to

from api.domains.agents.authorization import AgentAuthorization
from api.domains.rbac.catalog import AGENT_EDITOR_ROLE_ID, AGENT_VIEWER_ROLE_ID, PermissionKey
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_agent_access,
    there_is_an_agent,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

_GIVEN = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    there_is_an_agent(),
]


def _demote_to_member(context) -> None:
    context.organization_user.role = OrganizationRole.MEMBER
    context.injector.get(OrganizationUserRepository).save(context.organization_user)


def _can_update(context) -> bool:
    return context.injector.get(AgentAuthorization).membership_has_permission(
        context.organization_user.id, context.agent.id, PermissionKey.AGENT_UPDATE
    )


def test_an_organization_owner_can_act_on_every_agent() -> None:
    with given(_GIVEN) as context:
        with then("the owner's membership has the permission without explicit access"):
            assert_that(_can_update(context), equal_to(True))


def test_a_member_acts_only_through_explicit_access_that_grants_the_permission() -> None:
    with given(_GIVEN) as context:
        _demote_to_member(context)

        with when("the member has no access, then viewer access, then editor access"):
            without = _can_update(context)
            there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID)(context)
            as_viewer = _can_update(context)
            there_is_an_agent(name="Edited Agent")(context)
            there_is_agent_access(access_role_id=AGENT_EDITOR_ROLE_ID)(context)
            as_editor = _can_update(context)

        with then("only the editor access grants the update permission"):
            assert_that((without, as_viewer, as_editor), equal_to((False, False, True)))


def test_an_unknown_membership_has_no_permission() -> None:
    with given(_GIVEN) as context:
        with then("a membership that does not exist is denied"):
            assert_that(
                context.injector.get(AgentAuthorization).membership_has_permission(
                    uuid4(), context.agent.id, PermissionKey.AGENT_UPDATE
                ),
                equal_to(False),
            )
