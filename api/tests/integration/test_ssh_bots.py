"""SSH assignments follow the Parent Agent's lifecycle and each Bot's identity."""

import pytest
from hamcrest import assert_that, equal_to, has_item, has_key, not_

from api.domains.agents.models import AgentStatus, AgentType
from api.domains.agents.repository import AgentRepository
from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID
from api.infrastructure.kubernetes.client import KubernetesClient
from api.tests.core.givenpy import given, then, when
from api.tests.integration.test_ssh import (
    _GIVEN,
    assign,
    assignments,
    headers,
    the_ssh_keys_are_assigned,
    there_are_shared_ssh_keys,
    there_is_an_organization_member_with_agent_access,
)
from api.tests.steps.agent import there_is_agent_access, there_is_an_agent


def there_is_a_parent_with_an_ssh_bot(runtime, status=AgentStatus.STOPPED, bot_status=None):
    def step(context):
        there_is_an_agent(name="Parent", agent_type=runtime, status=status)(context)
        context.parent = context.agent
        there_is_an_agent(
            name="SSH Bot",
            agent_type=runtime,
            status=bot_status or status,
            parent_agent_id=context.parent.id,
            bot_slot=1,
        )(context)

    return step


@pytest.mark.parametrize("runtime", list(AgentType))
@pytest.mark.parametrize("bot_status", [AgentStatus.RUNNING, AgentStatus.ERROR])
def test_applying_bot_ssh_access_restarts_only_the_parent_deployment(runtime, bot_status):
    with given(
        [
            *_GIVEN[:-1],
            there_is_a_parent_with_an_ssh_bot(runtime, AgentStatus.RUNNING, bot_status),
            there_are_shared_ssh_keys(),
        ]
    ) as context:
        k8s = context.injector.get(KubernetesClient)
        with when("SSH access is applied to the running Bot"):
            response = assign(context, [context.ssh_keys[0]["id"]], restart=True)

        with then("the Parent Agent restarts and the Bot remains inside that deployment"):
            assert_that(response.status_code, equal_to(200))
            names = [call.args[1].metadata.name for call in k8s.create_deployment.call_args_list]
            assert_that(names, equal_to([f"agent-{context.parent.id}"]))
            assert_that(
                context.injector.get(AgentRepository).get_by_id(context.agent.id).status, equal_to(AgentStatus.RUNNING)
            )


@pytest.mark.parametrize("runtime", list(AgentType))
def test_starting_a_parent_materializes_bot_only_ssh_access(runtime):
    with given(
        [
            *_GIVEN[:-1],
            there_is_a_parent_with_an_ssh_bot(runtime),
            there_are_shared_ssh_keys(),
            the_ssh_keys_are_assigned(),
        ]
    ) as context:
        with when("the Parent Agent starts with SSH access assigned only to its Bot"):
            response = context.client.post(
                f"/api/v1/organizations/{context.organization.id}/agents/{context.parent.id}/start",
                headers=headers(context),
            )

        with then("the actual pod has ephemeral SSH storage and the Bot gets its own socket"):
            assert_that(response.status_code, equal_to(200))
            k8s = context.injector.get(KubernetesClient)
            pod = k8s.create_deployment.call_args.args[1].spec.template.spec
            assert_that([volume.name for volume in pod.volumes], has_item("ssh-relay"))
            secrets = {
                call.args[1].metadata.name: call.args[1].string_data for call in k8s.create_secret.call_args_list
            }
            assert_that(secrets[f"agent-{context.parent.id}"], not_(has_key("AGENTBARN_SSH_SIGNER_TOKEN")))
            assert_that(
                secrets[f"agent-{context.agent.id}"]["SSH_AUTH_SOCK"],
                equal_to(f"/run/agentbarn-ssh/{context.agent.id}/agent.sock"),
            )
            saved = context.client.get(assignments(context), headers=headers(context)).json()
            assert_that(saved["pending_apply"], equal_to(False))


def test_bot_ssh_changes_cannot_race_the_parents_lifecycle():
    with given(
        [
            *_GIVEN[:-1],
            there_is_a_parent_with_an_ssh_bot(AgentType.HERMES),
            there_are_shared_ssh_keys(),
        ]
    ) as context:
        with context.injector.get(AgentRepository).lifecycle_lock(context.parent.id) as acquired:
            assert acquired
            with when("SSH assignments change while the Parent Agent has a lifecycle operation"):
                response = assign(context, [context.ssh_keys[0]["id"]])

        with then("the change is refused and the selection stays empty"):
            assert_that(response.status_code, equal_to(409))
            saved = context.client.get(assignments(context), headers=headers(context)).json()
            assert_that(saved["credentials"], equal_to([]))


def the_bot_owner_can_only_read_the_parent():
    def step(context):
        there_is_an_organization_member_with_agent_access("owner")(context)
        there_is_agent_access(agent_id=context.parent.id, access_role_id=AGENT_VIEWER_ROLE_ID)(context)

    return step


def test_applying_bot_ssh_requires_permission_to_restart_the_parent():
    with given(
        [
            *_GIVEN[:-1],
            there_is_a_parent_with_an_ssh_bot(AgentType.HERMES, AgentStatus.RUNNING),
            there_are_shared_ssh_keys(),
            the_bot_owner_can_only_read_the_parent(),
        ]
    ) as context:
        with when("a Bot owner without Parent lifecycle authority applies SSH access"):
            response = assign(context, [context.ssh_keys[0]["id"]], restart=True)
        with then("the restart is refused before changing the selection or workloads"):
            assert_that(response.status_code, equal_to(403))
            assert_that(context.injector.get(KubernetesClient).create_deployment.call_count, equal_to(0))
            saved = context.client.get(assignments(context), headers=headers(context)).json()
            assert_that(saved["credentials"], equal_to([]))


def test_an_errored_bot_cannot_add_ssh_keys_without_restarting_its_running_parent():
    with given(
        [
            *_GIVEN[:-1],
            there_is_a_parent_with_an_ssh_bot(AgentType.HERMES, AgentStatus.RUNNING, AgentStatus.ERROR),
            there_are_shared_ssh_keys(),
        ]
    ) as context:
        with when("new SSH access is saved without the required shared restart"):
            response = assign(context, [context.ssh_keys[0]["id"]])
        with then("the addition is refused and remains unapplied"):
            assert_that(response.status_code, equal_to(409))
            saved = context.client.get(assignments(context), headers=headers(context)).json()
            assert_that(saved["credentials"], equal_to([]))
