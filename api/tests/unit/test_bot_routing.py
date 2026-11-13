from unittest.mock import MagicMock
from uuid import UUID

import pytest

from api.core.config import Config
from api.domains.agent_webhooks.dispatch import AgentWebhookDispatcher
from api.domains.agents.models import Agent, AgentStatus, trigger_target
from api.domains.workflows.controller import WorkflowController
from api.infrastructure.crypto import encrypt_token
from api.tests.steps.agent import TEST_ENCRYPTION_KEY

PARENT_ID = UUID("aaaaaaaa-0000-4000-8000-00000000000a")
BOT_ID = UUID("bbbbbbbb-0000-4000-8000-00000000000b")
ORG_ID = UUID("cccccccc-0000-4000-8000-00000000000c")
URL_TEMPLATE = Config.model_fields["agent_trigger_url"].default


def _agent(agent_id=PARENT_ID, parent_id=None, slot=None) -> Agent:
    return Agent(
        id=agent_id,
        organization_id=ORG_ID,
        name="Agent",
        status=AgentStatus.RUNNING,
        communication_key_encrypted=encrypt_token("trigger-key", TEST_ENCRYPTION_KEY),
        parent_agent_id=parent_id,
        bot_slot=slot,
    )


def _bot(slot=3) -> Agent:
    return _agent(BOT_ID, PARENT_ID, slot)


def test_an_agent_is_triggered_on_its_own_service_and_the_standard_port():
    assert trigger_target(_agent()) == (PARENT_ID, 8082)


def test_a_bot_is_triggered_on_its_parents_service_and_its_slot_port():
    assert trigger_target(_bot()) == (PARENT_ID, 8103)


@pytest.mark.parametrize(
    ("agent", "host", "port"),
    [(_agent(), PARENT_ID, 8082), (_bot(), PARENT_ID, 8103)],
)
def test_a_webhook_reaches_the_right_pod_and_port(monkeypatch, agent, host, port):
    seen = {}

    def request(method, url, **fields):
        seen["url"] = url
        return MagicMock(status_code=202, json=lambda: {"native_job_id": "job"})

    monkeypatch.setattr("api.domains.agent_webhooks.dispatch.httpx.request", request)
    agents = MagicMock()
    agents.get_by_id.return_value = agent
    config = MagicMock(
        agent_trigger_url=URL_TEMPLATE, k8s_namespace="ns", agent_token_encryption_key=TEST_ENCRYPTION_KEY
    )

    AgentWebhookDispatcher(agents, config).dispatch(
        MagicMock(delivery_platform="slack"),
        MagicMock(id=UUID(int=1), agent_id=agent.id, dispatch_generation=1, prompt="hello"),
    )

    assert seen["url"] == f"http://agent-{host}.ns.svc.cluster.local:{port}/agent-triggers/v1/invocations"


@pytest.mark.parametrize(
    ("agent", "host", "port"),
    [(_agent(), PARENT_ID, 8082), (_bot(), PARENT_ID, 8103)],
)
def test_a_workflow_step_reaches_the_right_pod_and_port(agent, host, port):
    controller = WorkflowController.__new__(WorkflowController)
    controller.repository = MagicMock()
    controller.repository.owning_agent_id.return_value = agent.id
    controller.agents = MagicMock()
    controller.agents.get_by_id.return_value = agent
    controller.config = MagicMock(k8s_namespace="ns", agent_token_encryption_key=TEST_ENCRYPTION_KEY)
    controller.k8s = MagicMock()
    controller.k8s.proxy_to_agent.return_value = (202, {}, b"")

    controller._send(MagicMock(workflow_id=UUID(int=2), id=UUID(int=3)), "/agent-triggers/v1/workflow-steps", {})

    args = controller.k8s.proxy_to_agent.call_args.args
    assert (args[0], args[2]) == (f"agent-{host}", port)
