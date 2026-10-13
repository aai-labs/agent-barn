"""What an Agent's pod is told about its Organization's spend limit (AF-381), on both
runtimes: on credit, with payments on, the in-pod proxy tells the person chatting to have
credit bought rather than a limit raised."""

from unittest.mock import MagicMock

import pytest
from hamcrest import assert_that, equal_to

from api.domains.agents.models import AgentType
from api.infrastructure.kubernetes.client import KubernetesClient
from api.tests.core.givenpy import given
from api.tests.core.modules import set_env_variable
from api.tests.integration.test_agents import _BASE, _GIVEN, _GIVEN_WITH_HERMES_IMAGE, _auth
from api.tests.integration.test_credit_spend_limits import the_organization_runs_on_credit
from api.tests.steps.agent import there_is_an_agent

RUNTIMES = {AgentType.OPENCLAW: _GIVEN, AgentType.HERMES: _GIVEN_WITH_HERMES_IMAGE}


def spend_limit_kind(runtime: AgentType, *steps, payments: str) -> str:
    with given(
        [
            set_env_variable({"PAYMENTS_ENABLED": payments}),
            *RUNTIMES[runtime],
            there_is_an_agent(agent_type=runtime),
            *steps,
        ]
    ) as context:
        response = context.client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))
        assert_that(response.status_code, equal_to(200), response.text)
        k8s: MagicMock = context.injector.get(KubernetesClient)
        return k8s.create_secret.call_args.args[1].string_data["AGENTBARN_SPEND_LIMIT_KIND"]


@pytest.mark.parametrize("runtime", list(RUNTIMES))
def test_an_agent_on_credit_is_told_so_when_payments_are_on(runtime):
    assert_that(spend_limit_kind(runtime, the_organization_runs_on_credit(), payments="true"), equal_to("credit"))


@pytest.mark.parametrize("runtime", list(RUNTIMES))
def test_without_payments_credit_reads_as_a_limit(runtime):
    assert_that(spend_limit_kind(runtime, the_organization_runs_on_credit(), payments="false"), equal_to("limit"))


@pytest.mark.parametrize("runtime", list(RUNTIMES))
def test_an_agent_on_a_renewing_limit_is_told_so(runtime):
    assert_that(spend_limit_kind(runtime, payments="true"), equal_to("limit"))
