from unittest.mock import Mock
from uuid import uuid7

from api.domains.agents.access_service import AgentAccessService
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent, AgentAccessSettingsUpdate
from api.domains.agents.repository import AgentRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.repository import RbacRepository
from api.domains.users.models import User
from api.domains.users.organization_users.repository import OrganizationUserRepository


def test_replace_access_settings_enqueues_staged_deliveries_immediately():
    """Regression: replace_access_settings must hand the repository's staged delivery
    ids to the dispatcher, like every other event-emitting mutation. The integration
    test covering this same path can only assert PENDING-or-ENQUEUED (Redis may be
    unreachable in CI), so this unit test is the one place that deterministically
    proves enqueue_immediate is actually invoked."""
    organization_id = uuid7()
    agent_id = uuid7()
    agent = Mock(spec=Agent)
    agent.id = agent_id
    agent.organization_id = organization_id
    agent.general_access_role_id = None
    agent.name = "Test Agent"

    delivery_ids = [uuid7(), uuid7(), uuid7()]
    repository = Mock(spec=AgentRepository)
    repository.find_access_assignments.return_value = []
    repository.replace_access_settings.return_value = delivery_ids

    authorization = Mock(spec=AgentAuthorization)
    authorization.require_action.return_value = agent

    membership_repository = Mock(spec=OrganizationUserRepository)
    rbac_repository = Mock(spec=RbacRepository)
    event_delivery_dispatcher = Mock()

    service = AgentAccessService(
        repository=repository,
        authorization=authorization,
        membership_repository=membership_repository,
        rbac_repository=rbac_repository,
        event_delivery_dispatcher=event_delivery_dispatcher,
    )

    context = CurrentUserContext(user=User(email="admin@example.com", hashed_password="hash"))

    service.replace_access_settings(
        agent_id,
        AgentAccessSettingsUpdate(general_access_role_id=None, assignments=[]),
        context,
    )

    event_delivery_dispatcher.enqueue_immediate.assert_called_once_with(delivery_ids)
