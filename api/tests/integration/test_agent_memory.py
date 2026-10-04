"""Agent Memory opt-in and Memory Grants.

Two rules are under test:

- turning memory on or off for an Agent needs Agent Owner authority, which the
  Agent's creator, Organization Owners and Organization Admins hold;
- letting an Agent recall Organization Memory or another Agent's memories needs
  `memory.access.manage`, which only Organization Owners and Admins hold.
"""

from uuid import UUID, uuid7

import pytest
from fastapi import status
from hamcrest import (
    assert_that,
    contains_exactly,
    empty,
    equal_to,
    has_entries,
    has_item,
    is_not,
    none,
)
from sqlalchemy.exc import IntegrityError

from api.domains.agent_memory.models import AgentMemoryGrant
from api.domains.agents.models import Agent
from api.domains.events.catalog import (
    AGENT_MEMORY_DISABLED,
    AGENT_MEMORY_ENABLED,
    AGENT_MEMORY_GRANT_CREATED,
    AGENT_MEMORY_GRANT_REVOKED,
)
from api.domains.events.models import OutboxMessage
from api.domains.rbac.catalog import AGENT_EDITOR_ROLE_ID, AGENT_OWNER_ROLE_ID, AGENT_VIEWER_ROLE_ID, PermissionKey
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.steps.agent import (
    there_is_agent_access,
    there_is_an_agent,
    there_is_an_agent_in_another_org,
)
from api.tests.steps.agent_memory import (
    agent_memory_api_setup,
    an_agent_created_by_the_current_member,
    signed_in_as,
    two_agents,
)

_AGENT = "/api/v1/organizations/{organization_id}/agents/{agent_id}"
_MEMORY = _AGENT + "/memory"
_GRANTS = "/api/v1/organizations/{organization_id}/memory-grants"


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _set_memory(context, agent_id: UUID, enabled: bool):
    return context.client.put(
        _MEMORY.replace("{agent_id}", str(agent_id)),
        json={"enabled": enabled},
        headers=_auth(context),
    )


def _create_grant(context, agent_id: UUID, source_agent_id: UUID | None = None, access: str = "read"):
    return context.client.post(
        _GRANTS,
        json={
            "agent_id": str(agent_id),
            "source_agent_id": str(source_agent_id) if source_agent_id else None,
            "access": access,
        },
        headers=_auth(context),
    )


def _stored_agent(context, agent_id: UUID) -> Agent:
    return context.injector.get(PostgresRepositoryDelegate).find_by_id(Agent, agent_id)


def _event_names(context) -> list[str]:
    messages = context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
    return [message.event_name for message in sorted(messages, key=lambda message: message.occurred_at)]


def _grants(context) -> list[AgentMemoryGrant]:
    return context.injector.get(PostgresRepositoryDelegate).find_all(AgentMemoryGrant)


# --- Turning memory on and off ---------------------------------------------------


def test_an_agent_starts_with_memory_off():
    with given(agent_memory_api_setup(there_is_an_agent())) as context:
        with when("I read the Agent"):
            response = context.client.get(_AGENT.replace("{agent_id}", str(context.agent.id)), headers=_auth(context))

        with then("memory is reported off"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["memory_enabled"], equal_to(False))


def test_the_agents_creator_can_turn_memory_on():
    with given(
        agent_memory_api_setup(signed_in_as(OrganizationRole.MEMBER), an_agent_created_by_the_current_member())
    ) as context:
        with when("the Member who created the Agent turns memory on"):
            response = _set_memory(context, context.agent.id, True)

        with then("memory is on and the change is audited"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json(), has_entries(agent_id=str(context.agent.id), enabled=True))
            assert_that(_stored_agent(context, context.agent.id).memory_enabled, equal_to(True))
            assert_that(_event_names(context), has_item(AGENT_MEMORY_ENABLED))


def test_the_creator_is_told_they_may_manage_memory():
    with given(
        agent_memory_api_setup(signed_in_as(OrganizationRole.MEMBER), an_agent_created_by_the_current_member())
    ) as context:
        with when("the creator reads the Agent"):
            response = context.client.get(_AGENT.replace("{agent_id}", str(context.agent.id)), headers=_auth(context))

        with then("the memory operation is among its allowed actions"):
            assert_that(response.json()["allowed_actions"], has_item(PermissionKey.AGENT_MEMORY_MANAGE.value))


def test_an_organization_admin_can_turn_memory_on_for_any_agent():
    with given(agent_memory_api_setup(there_is_an_agent(), signed_in_as(OrganizationRole.ADMIN))) as context:
        with when("an Admin turns memory on for an Agent they did not create"):
            response = _set_memory(context, context.agent.id, True)

        with then("memory is on"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_stored_agent(context, context.agent.id).memory_enabled, equal_to(True))


def test_an_agent_editor_cannot_turn_memory_on():
    with given(
        agent_memory_api_setup(
            there_is_an_agent(),
            signed_in_as(OrganizationRole.MEMBER),
            there_is_agent_access(access_role_id=AGENT_EDITOR_ROLE_ID),
        )
    ) as context:
        with when("a Member with Agent Editor access tries to turn memory on"):
            response = _set_memory(context, context.agent.id, True)

        with then("the request is forbidden and memory stays off"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(_stored_agent(context, context.agent.id).memory_enabled, equal_to(False))


def test_an_agent_editor_is_not_told_they_may_manage_memory():
    with given(
        agent_memory_api_setup(
            there_is_an_agent(),
            signed_in_as(OrganizationRole.MEMBER),
            there_is_agent_access(access_role_id=AGENT_EDITOR_ROLE_ID),
        )
    ) as context:
        with when("the Editor reads the Agent"):
            response = context.client.get(_AGENT.replace("{agent_id}", str(context.agent.id)), headers=_auth(context))

        with then("the memory operation is not among its allowed actions"):
            assert_that(response.json()["allowed_actions"], is_not(has_item(PermissionKey.AGENT_MEMORY_MANAGE.value)))


def test_a_member_without_access_cannot_see_the_agent():
    with given(agent_memory_api_setup(there_is_an_agent(), signed_in_as(OrganizationRole.MEMBER))) as context:
        with when("a Member with no access to the Agent tries to turn memory on"):
            response = _set_memory(context, context.agent.id, True)

        with then("the Agent is concealed"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_turning_memory_off_is_audited():
    with given(agent_memory_api_setup(there_is_an_agent())) as context:
        _set_memory(context, context.agent.id, True)

        with when("the Owner turns memory off again"):
            response = _set_memory(context, context.agent.id, False)

        with then("memory is off and both transitions are audited"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_stored_agent(context, context.agent.id).memory_enabled, equal_to(False))
            assert_that(_event_names(context), contains_exactly(AGENT_MEMORY_ENABLED, AGENT_MEMORY_DISABLED))


def test_repeating_the_current_memory_setting_records_nothing():
    with given(agent_memory_api_setup(there_is_an_agent())) as context:
        with when("the Owner turns memory off on an Agent where it is already off"):
            response = _set_memory(context, context.agent.id, False)

        with then("the request succeeds without an audit record"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_event_names(context), empty())


def test_changing_memory_requires_authentication():
    with given(agent_memory_api_setup(there_is_an_agent())) as context:
        with when("an unauthenticated caller turns memory on"):
            response = context.client.put(
                _MEMORY.replace("{agent_id}", str(context.agent.id)),
                json={"enabled": True},
            )

        with then("the request is rejected"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


# --- Memory Grants -----------------------------------------------------------------


def test_an_owner_grants_organization_memory():
    with given(agent_memory_api_setup(two_agents())) as context:
        with when("the Owner grants Triage Organization Memory"):
            response = _create_grant(context, context.triage.id)

        with then("the grant is created without a source Agent and is audited"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(
                response.json(),
                has_entries(
                    agent_id=str(context.triage.id),
                    agent_name="Triage",
                    source_agent_id=none(),
                    source_agent_name=none(),
                ),
            )
            assert_that(_event_names(context), contains_exactly(AGENT_MEMORY_GRANT_CREATED))


def test_an_admin_grants_one_agent_read_access_to_another():
    with given(agent_memory_api_setup(two_agents(), signed_in_as(OrganizationRole.ADMIN))) as context:
        with when("an Admin lets Triage read Billing's memories"):
            response = _create_grant(context, context.triage.id, context.billing.id)

        with then("the grant names both Agents"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(
                response.json(),
                has_entries(
                    agent_id=str(context.triage.id),
                    source_agent_id=str(context.billing.id),
                    source_agent_name="Billing",
                ),
            )


def test_a_grant_is_one_way():
    with given(agent_memory_api_setup(two_agents())) as context:
        _create_grant(context, context.triage.id, context.billing.id)

        with when("the Owner lists memory grants"):
            response = context.client.get(_GRANTS, headers=_auth(context))

        with then("only Triage reads Billing; Billing gains nothing"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                response.json(),
                contains_exactly(has_entries(agent_id=str(context.triage.id), source_agent_id=str(context.billing.id))),
            )


def test_a_member_cannot_grant_memory_access_even_as_agent_owner():
    with given(
        agent_memory_api_setup(
            signed_in_as(OrganizationRole.MEMBER),
            an_agent_created_by_the_current_member("Reader"),
        )
    ) as context:
        with when("the Member grants their own Agent Organization Memory"):
            response = _create_grant(context, context.agent.id)

        with then("the request is forbidden and nothing is stored"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(_grants(context), empty())


def test_a_member_cannot_list_memory_grants():
    with given(agent_memory_api_setup(signed_in_as(OrganizationRole.MEMBER))) as context:
        with when("a Member lists memory grants"):
            response = context.client.get(_GRANTS, headers=_auth(context))

        with then("the request is forbidden"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_duplicate_grant_conflicts():
    with given(agent_memory_api_setup(two_agents())) as context:
        _create_grant(context, context.triage.id, context.billing.id)

        with when("the same grant is created again"):
            response = _create_grant(context, context.triage.id, context.billing.id)

        with then("it conflicts and only one grant exists"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(_grants(context), contains_exactly(is_not(none())))


def test_a_duplicate_organization_memory_grant_conflicts():
    with given(agent_memory_api_setup(two_agents())) as context:
        _create_grant(context, context.triage.id)

        with when("Organization Memory is granted to the same Agent again"):
            response = _create_grant(context, context.triage.id)

        with then("it conflicts"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_an_agent_cannot_be_granted_its_own_memories():
    with given(agent_memory_api_setup(two_agents())) as context:
        with when("Billing is granted read access to Billing"):
            response = _create_grant(context, context.billing.id, context.billing.id)

        with then("the request is rejected"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_a_grant_cannot_reach_another_organizations_agent():
    with given(agent_memory_api_setup(two_agents(), there_is_an_agent_in_another_org())) as context:
        with when("Triage is granted read access to an Agent in another Organization"):
            response = _create_grant(context, context.triage.id, context.other_org_agent.id)

        with then("that Agent is not found and nothing is stored"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(_grants(context), empty())


def test_a_grant_cannot_name_a_deleted_agent():
    with given(agent_memory_api_setup(two_agents(), there_is_an_agent(name="Gone", deleted=True))) as context:
        with when("Triage is granted read access to a deleted Agent"):
            response = _create_grant(context, context.triage.id, context.agent.id)

        with then("that Agent is not found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_revoking_a_grant_removes_it_and_is_audited():
    with given(agent_memory_api_setup(two_agents())) as context:
        grant_id = _create_grant(context, context.triage.id, context.billing.id).json()["id"]

        with when("the Owner revokes the grant"):
            response = context.client.delete(f"{_GRANTS}/{grant_id}", headers=_auth(context))

        with then("it is gone and the revocation is audited"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            assert_that(_grants(context), empty())
            assert_that(
                _event_names(context),
                contains_exactly(AGENT_MEMORY_GRANT_CREATED, AGENT_MEMORY_GRANT_REVOKED),
            )


def test_revoking_an_unknown_grant_is_not_found():
    with given(agent_memory_api_setup()) as context:
        with when("the Owner revokes a grant that does not exist"):
            response = context.client.delete(f"{_GRANTS}/{uuid7()}", headers=_auth(context))

        with then("it is not found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_a_member_cannot_revoke_a_grant():
    with given(agent_memory_api_setup(two_agents())) as context:
        grant_id = _create_grant(context, context.triage.id).json()["id"]
        signed_in_as(OrganizationRole.MEMBER)(context)

        with when("a Member revokes the grant"):
            response = context.client.delete(f"{_GRANTS}/{grant_id}", headers=_auth(context))

        with then("the request is forbidden and the grant stays"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(_grants(context), contains_exactly(is_not(none())))


def test_grants_of_a_deleted_agent_are_not_listed():
    with given(agent_memory_api_setup(two_agents())) as context:
        _create_grant(context, context.triage.id, context.billing.id)
        delegate = context.injector.get(PostgresRepositoryDelegate)
        billing = delegate.find_by_id(Agent, context.billing.id)
        billing.deleted_at = billing.updated_at
        delegate.save(billing)

        with when("the Owner lists memory grants after Billing is deleted"):
            response = context.client.get(_GRANTS, headers=_auth(context))

        with then("the grant naming Billing is no longer listed"):
            assert_that(response.json(), empty())


def test_memory_grants_require_authentication():
    with given(agent_memory_api_setup(two_agents())) as context:
        with when("an unauthenticated caller lists and creates grants"):
            listed = context.client.get(_GRANTS)
            created = context.client.post(_GRANTS, json={"agent_id": str(context.triage.id)})

        with then("both are rejected"):
            assert_that(listed.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
            assert_that(created.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


@pytest.mark.parametrize("target", ["missing", "deleted", "foreign"])
def test_memory_cannot_be_changed_on_an_absent_or_foreign_agent(target):
    with given(agent_memory_api_setup(there_is_an_agent(deleted=True))) as context:
        deleted_agent_id = context.agent.id
        there_is_an_agent_in_another_org()(context)
        agent_id = {"missing": uuid7(), "deleted": deleted_agent_id, "foreign": context.other_org_agent.id}[target]

        with when("the Owner tries to enable memory on an unavailable Agent"):
            response = _set_memory(context, agent_id, True)

        with then("the Agent is concealed and no memory event is recorded"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(_event_names(context), empty())


@pytest.mark.parametrize("role_id, expected", [(AGENT_OWNER_ROLE_ID, 200), (AGENT_VIEWER_ROLE_ID, 403)])
def test_explicit_agent_access_controls_memory_management(role_id, expected):
    with given(
        agent_memory_api_setup(
            there_is_an_agent(),
            signed_in_as(OrganizationRole.MEMBER),
            there_is_agent_access(access_role_id=role_id),
        )
    ) as context:
        with when("a Member with explicit Agent Access changes memory"):
            response = _set_memory(context, context.agent.id, True)

        with then("the current role decides the outcome"):
            assert_that(response.status_code, equal_to(expected))
            assert_that(_stored_agent(context, context.agent.id).memory_enabled, equal_to(expected == 200))


def test_disabling_source_memory_keeps_its_grants():
    with given(agent_memory_api_setup(two_agents())) as context:
        _set_memory(context, context.billing.id, True)
        grant = _create_grant(context, context.triage.id, context.billing.id).json()

        with when("the Owner turns Billing's memory off"):
            response = _set_memory(context, context.billing.id, False)

        with then("the memory setting is off and Triage's grant remains available"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_stored_agent(context, context.billing.id).memory_enabled, equal_to(False))
            listed = context.client.get(_GRANTS, headers=_auth(context))
            assert_that(listed.json(), contains_exactly(has_entries(id=grant["id"])))


@pytest.mark.parametrize(
    "endpoint, payload", [("memory", {}), ("memory", {"enabled": True, "tags": []}), ("grants", {})]
)
def test_memory_requests_validate_payloads(endpoint, payload):
    with given(agent_memory_api_setup(there_is_an_agent())) as context:
        with when("the Owner sends an invalid memory request"):
            if endpoint == "memory":
                response = context.client.put(
                    _MEMORY.replace("{agent_id}", str(context.agent.id)), json=payload, headers=_auth(context)
                )
            else:
                response = context.client.post(_GRANTS, json=payload, headers=_auth(context))

        with then("the payload is rejected without a mutation"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))
            assert_that(_event_names(context), empty())
            assert_that(_grants(context), empty())


def test_memory_grants_cannot_use_a_foreign_reader():
    with given(agent_memory_api_setup(two_agents(), there_is_an_agent_in_another_org())) as context:
        with when("the Owner grants Organization Memory to a foreign Agent"):
            response = _create_grant(context, context.other_org_agent.id)

        with then("the reader is concealed and nothing is stored"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(_grants(context), empty())


def test_foreign_grants_are_hidden_from_listing_and_revocation():
    with given(agent_memory_api_setup(two_agents(), there_is_an_agent_in_another_org())) as context:
        foreign = AgentMemoryGrant(
            organization_id=context.other_org_agent.organization_id,
            agent_id=context.other_org_agent.id,
        )
        context.injector.get(PostgresRepositoryDelegate).save(foreign)

        with when("the Owner lists and tries to revoke another Organization's grant"):
            listed = context.client.get(_GRANTS, headers=_auth(context))
            revoked = context.client.delete(f"{_GRANTS}/{foreign.id}", headers=_auth(context))

        with then("the grant is concealed and remains stored"):
            assert_that(listed.json(), empty())
            assert_that(revoked.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(_grants(context), contains_exactly(is_not(none())))


@pytest.mark.parametrize("invalid_relationship", ["self", "foreign_reader", "foreign_source"])
def test_migrated_schema_enforces_memory_grant_relationships(invalid_relationship):
    with given(agent_memory_api_setup(two_agents(), there_is_an_agent_in_another_org())) as context:
        reader_id = context.triage.id
        source_id = context.billing.id
        if invalid_relationship == "self":
            source_id = reader_id
        elif invalid_relationship == "foreign_reader":
            reader_id = context.other_org_agent.id
        else:
            source_id = context.other_org_agent.id

        with when("a write bypasses application validation"):
            with pytest.raises(IntegrityError):
                context.injector.get(PostgresRepositoryDelegate).save(
                    AgentMemoryGrant(
                        organization_id=context.organization.id, agent_id=reader_id, source_agent_id=source_id
                    )
                )

        with then("the migrated database refuses the invalid relationship"):
            assert_that(_grants(context), empty())


@pytest.mark.parametrize("role", [OrganizationRole.OWNER, OrganizationRole.ADMIN])
def test_admin_can_grant_and_revoke_organization_write_independently(role):
    with given(
        agent_memory_api_setup(two_agents(), *([signed_in_as(role)] if role != OrganizationRole.OWNER else []))
    ) as context:
        reader = _create_grant(context, context.triage.id)
        writer = _create_grant(context, context.triage.id, access="write")
        assert_that(reader.status_code, equal_to(201))
        assert_that(writer.status_code, equal_to(201))
        assert_that(writer.json()["access"], equal_to("write"))
        result = context.client.delete(_GRANTS + "/" + writer.json()["id"], headers=_auth(context))
        assert_that(result.status_code, equal_to(204))
        remaining = context.client.get(_GRANTS, headers=_auth(context)).json()
        assert_that([row["access"] for row in remaining], contains_exactly("read"))


def test_member_cannot_grant_organization_write():
    with given(agent_memory_api_setup(two_agents(), signed_in_as(OrganizationRole.MEMBER))) as context:
        assert_that(_create_grant(context, context.triage.id, access="write").status_code, equal_to(403))


def test_write_access_to_another_agents_private_memory_is_rejected():
    with given(agent_memory_api_setup(two_agents())) as context:
        response = _create_grant(context, context.triage.id, context.billing.id, access="write")
        assert_that(response.status_code, equal_to(400))
