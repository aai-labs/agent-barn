from uuid import UUID, uuid7

from fastapi import status
from hamcrest import assert_that, contains_inanyorder, equal_to, has_item, is_in, is_not, none

from api.domains.agents.models import AgentAccess
from api.domains.agents.repository import AgentRepository
from api.domains.events.models import EventDelivery, EventDeliveryStatus, OutboxMessage
from api.domains.organizations.models import Organization
from api.domains.rbac.catalog import (
    AGENT_EDITOR_ROLE_ID,
    AGENT_VIEWER_ROLE_ID,
    PERMISSION_ID_BY_KEY,
    PermissionKey,
)
from api.domains.rbac.models import AgentAccessRole, AgentAccessRolePermission
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.tests.core.givenpy import given
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
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_BASE = "/api/v1/organizations/{organization_id}/agents"
_GIVEN = [
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
    there_is_a_template(),
    there_is_an_agent(),
]


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _access_settings_url(agent_id: UUID) -> str:
    return f"{_BASE}/{agent_id}/share"


def _outbox_messages(context) -> list[OutboxMessage]:
    repository: AgentRepository = context.injector.get(AgentRepository)
    return repository.delegate.find_all(OutboxMessage)


def _event_deliveries(context) -> list[EventDelivery]:
    repository: AgentRepository = context.injector.get(AgentRepository)
    return repository.delegate.find_all(EventDelivery)


def test_general_access_defaults_to_restricted():
    with given(_GIVEN) as context:
        response = context.client.get(_access_settings_url(context.agent.id), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["general_access"]["role"], none())


def test_owner_sets_changes_and_removes_general_access():
    with given(_GIVEN) as context:
        set_response = context.client.put(
            _access_settings_url(context.agent.id),
            json={
                "general_access_role_id": str(AGENT_VIEWER_ROLE_ID),
                "assignments": [],
            },
            headers=_auth(context),
        )

        assert_that(set_response.status_code, equal_to(status.HTTP_200_OK))
        role = set_response.json()["general_access"]["role"]
        assert_that(role["id"], equal_to(str(AGENT_VIEWER_ROLE_ID)))
        assert_that(role["name"], equal_to("VIEWER"))
        assert_that(role["is_locked"], equal_to(True))

        read_response = context.client.get(_access_settings_url(context.agent.id), headers=_auth(context))
        assert_that(read_response.json()["general_access"]["role"]["id"], equal_to(role["id"]))

        removed = context.client.put(
            _access_settings_url(context.agent.id),
            json={"general_access_role_id": None, "assignments": []},
            headers=_auth(context),
        )
        assert_that(removed.status_code, equal_to(status.HTTP_200_OK))
        restricted = context.client.get(_access_settings_url(context.agent.id), headers=_auth(context))
        assert_that(restricted.json()["general_access"]["role"], none())


def test_general_access_rejects_unknown_role():
    with given(_GIVEN) as context:
        response = context.client.put(
            _access_settings_url(context.agent.id),
            json={"general_access_role_id": str(uuid7()), "assignments": []},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def _switch_to_member(context, *, email_verified: bool = True) -> None:
    member_id = uuid7()
    there_is_a_user(
        id=member_id,
        email=f"member-{member_id}@example.com",
        role=OrganizationRole.MEMBER,
        organization_id=context.organization.id,
        email_verified=email_verified,
    )(context)
    there_is_an_access_token_for_user(member_id)(context)


def _add_target_member(context, *, email_verified: bool = True):
    saved = {
        name: getattr(context, name, None)
        for name in (
            "user",
            "organization",
            "organization_user",
            "current_user_context",
        )
    }
    member_id = uuid7()
    there_is_a_user(
        id=member_id,
        email=f"target-{member_id}@example.com",
        role=OrganizationRole.MEMBER,
        organization_id=context.organization.id,
        email_verified=email_verified,
    )(context)
    member = context.user
    membership = context.organization_user
    for name, value in saved.items():
        setattr(context, name, value)
    return member, membership


def test_member_without_access_manage_cannot_read_or_change_general_access():
    with given(_GIVEN) as context:
        agent_id = context.agent.id
        _switch_to_member(context)
        repository: AgentRepository = context.injector.get(AgentRepository)
        repository.delegate.save(
            AgentAccess(
                organization_id=context.organization.id,
                membership_id=context.organization_user.id,
                agent_id=agent_id,
                access_role_id=AGENT_VIEWER_ROLE_ID,
            )
        )

        read_response = context.client.get(_access_settings_url(agent_id), headers=_auth(context))
        set_response = context.client.put(
            _access_settings_url(agent_id),
            json={
                "general_access_role_id": str(AGENT_VIEWER_ROLE_ID),
                "assignments": [],
            },
            headers=_auth(context),
        )
        assert_that(read_response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(set_response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_unassigned_member_cannot_discover_general_access():
    with given(_GIVEN) as context:
        agent_id = context.agent.id
        _switch_to_member(context)

        response = context.client.get(_access_settings_url(agent_id), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def _insert_custom_role(context, *, organization_id: UUID, permissions: set[PermissionKey]) -> AgentAccessRole:
    repository: AgentRepository = context.injector.get(AgentRepository)
    role = AgentAccessRole(
        organization_id=organization_id,
        name=f"CUSTOM-{uuid7().hex}",
        is_system=False,
    )
    repository.delegate.save(role)
    for permission in permissions:
        repository.delegate.save(
            AgentAccessRolePermission(
                role_id=role.id,
                permission_id=PERMISSION_ID_BY_KEY[permission],
            )
        )
    return role


def test_general_access_rejects_foreign_custom_role():
    with given(_GIVEN) as context:
        repository: AgentRepository = context.injector.get(AgentRepository)
        other_organization = Organization(name="Other Org")
        repository.delegate.save(other_organization)
        foreign_role = _insert_custom_role(
            context,
            organization_id=other_organization.id,
            permissions={PermissionKey.AGENT_READ},
        )

        response = context.client.put(
            _access_settings_url(context.agent.id),
            json={"general_access_role_id": str(foreign_role.id), "assignments": []},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_general_access_requires_role_granting_agent_read():
    with given(_GIVEN) as context:
        readless_role = _insert_custom_role(
            context,
            organization_id=context.organization.id,
            permissions={PermissionKey.ACTIVITY_READ},
        )
        readable_role = _insert_custom_role(
            context,
            organization_id=context.organization.id,
            permissions={PermissionKey.AGENT_READ},
        )

        rejected = context.client.put(
            _access_settings_url(context.agent.id),
            json={"general_access_role_id": str(readless_role.id), "assignments": []},
            headers=_auth(context),
        )
        accepted = context.client.put(
            _access_settings_url(context.agent.id),
            json={"general_access_role_id": str(readable_role.id), "assignments": []},
            headers=_auth(context),
        )

        assert_that(rejected.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(accepted.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            accepted.json()["general_access"]["role"]["id"],
            equal_to(str(readable_role.id)),
        )


def test_general_access_makes_agent_visible_with_role_permissions():
    with given(_GIVEN) as context:
        agent_id = context.agent.id
        context.client.put(
            _access_settings_url(agent_id),
            json={
                "general_access_role_id": str(AGENT_VIEWER_ROLE_ID),
                "assignments": [],
            },
            headers=_auth(context),
        )
        _switch_to_member(context)

        listed = context.client.get(_BASE, headers=_auth(context))
        detail = context.client.get(f"{_BASE}/{agent_id}", headers=_auth(context))
        forbidden_update = context.client.patch(
            f"{_BASE}/{agent_id}",
            json={"name": "Viewer cannot update"},
            headers=_auth(context),
        )

        assert_that(listed.status_code, equal_to(status.HTTP_200_OK))
        assert_that(listed.json()["total"], equal_to(1))
        assert_that(listed.json()["items"][0]["id"], equal_to(str(agent_id)))
        assert_that(detail.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            detail.json()["allowed_actions"],
            contains_inanyorder(
                PermissionKey.AGENT_READ.value,
                PermissionKey.ACTIVITY_READ.value,
                PermissionKey.COST_READ.value,
            ),
        )
        assert_that(
            detail.json()["allowed_actions"],
            is_not(has_item(PermissionKey.AGENT_UPDATE.value)),
        )
        assert_that(forbidden_update.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_general_access_scopes_subordinate_agent_resources():
    with given(_GIVEN) as context:
        general_agent = context.agent
        there_is_an_agent(name="Restricted Agent")(context)
        restricted_agent = context.agent
        context.client.put(
            _access_settings_url(general_agent.id),
            json={
                "general_access_role_id": str(AGENT_VIEWER_ROLE_ID),
                "assignments": [],
            },
            headers=_auth(context),
        )
        _switch_to_member(context)

        general_urls = (
            f"{_BASE}/{general_agent.id}/logs",
            f"{_BASE}/{general_agent.id}/conversations/channels",
            f"{_BASE}/{general_agent.id}/tool-calls",
            f"/api/v1/organizations/{{organization_id}}/costs/agents/{general_agent.id}",
        )
        restricted_urls = (
            f"{_BASE}/{restricted_agent.id}/logs",
            f"{_BASE}/{restricted_agent.id}/conversations/channels",
            f"{_BASE}/{restricted_agent.id}/tool-calls",
            f"/api/v1/organizations/{{organization_id}}/costs/agents/{restricted_agent.id}",
        )

        for url in general_urls:
            response = context.client.get(url, headers=_auth(context))
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), url)
        for url in restricted_urls:
            response = context.client.get(url, headers=_auth(context))
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND), url)


def test_pending_members_do_not_receive_general_access():
    with given(_GIVEN) as context:
        agent_id = context.agent.id
        context.client.put(
            _access_settings_url(agent_id),
            json={
                "general_access_role_id": str(AGENT_VIEWER_ROLE_ID),
                "assignments": [],
            },
            headers=_auth(context),
        )
        _switch_to_member(context, email_verified=False)

        listed = context.client.get(_BASE, headers=_auth(context))
        detail = context.client.get(f"{_BASE}/{agent_id}", headers=_auth(context))

        assert_that(listed.status_code, equal_to(status.HTTP_200_OK))
        assert_that(listed.json()["total"], equal_to(0))
        assert_that(detail.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_removed_membership_receives_no_general_access():
    with given(_GIVEN) as context:
        agent_id = context.agent.id
        context.client.put(
            _access_settings_url(agent_id),
            json={
                "general_access_role_id": str(AGENT_VIEWER_ROLE_ID),
                "assignments": [],
            },
            headers=_auth(context),
        )
        target, target_membership = _add_target_member(context)
        there_is_an_access_token_for_user(target.id)(context)

        visible_before_removal = context.client.get(f"{_BASE}/{agent_id}", headers=_auth(context))

        membership_repository: OrganizationUserRepository = context.injector.get(OrganizationUserRepository)
        membership_repository.delete(target_membership)

        listed_after_removal = context.client.get(_BASE, headers=_auth(context))
        detail_after_removal = context.client.get(f"{_BASE}/{agent_id}", headers=_auth(context))

        assert_that(visible_before_removal.status_code, equal_to(status.HTTP_200_OK))
        # A removed Membership has no organization_users row at all, so the request is
        # rejected at the organization-authorization boundary before Agent visibility
        # is even evaluated, unlike a pending Member whose row still exists.
        assert_that(listed_after_removal.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(detail_after_removal.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_direct_and_general_access_permissions_are_additive():
    with given(_GIVEN) as context:
        owner_id = context.user.id
        agent_id = context.agent.id
        context.client.put(
            _access_settings_url(agent_id),
            json={
                "general_access_role_id": str(AGENT_VIEWER_ROLE_ID),
                "assignments": [],
            },
            headers=_auth(context),
        )
        _switch_to_member(context)
        member_id = context.user.id
        member_membership_id = context.organization_user.id
        repository: AgentRepository = context.injector.get(AgentRepository)
        repository.delegate.save(
            AgentAccess(
                organization_id=context.organization.id,
                membership_id=member_membership_id,
                agent_id=agent_id,
                access_role_id=AGENT_EDITOR_ROLE_ID,
            )
        )

        editable = context.client.patch(
            f"{_BASE}/{agent_id}",
            json={"name": "Direct Editor plus General Viewer"},
            headers=_auth(context),
        )
        detail = context.client.get(f"{_BASE}/{agent_id}", headers=_auth(context))
        there_is_an_access_token_for_user(owner_id)(context)
        revoked = context.client.put(
            _access_settings_url(agent_id),
            json={
                "general_access_role_id": str(AGENT_VIEWER_ROLE_ID),
                "assignments": [],
            },
            headers=_auth(context),
        )
        there_is_an_access_token_for_user(member_id)(context)
        still_visible = context.client.get(f"{_BASE}/{agent_id}", headers=_auth(context))
        no_longer_editable = context.client.patch(
            f"{_BASE}/{agent_id}",
            json={"name": "General Viewer only"},
            headers=_auth(context),
        )

        assert_that(editable.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            detail.json()["allowed_actions"],
            has_item(PermissionKey.AGENT_UPDATE.value),
        )
        assert_that(revoked.status_code, equal_to(status.HTTP_200_OK))
        assert_that(still_visible.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            still_visible.json()["allowed_actions"],
            contains_inanyorder(
                PermissionKey.AGENT_READ.value,
                PermissionKey.ACTIVITY_READ.value,
                PermissionKey.COST_READ.value,
            ),
        )
        assert_that(
            no_longer_editable.status_code,
            equal_to(status.HTTP_403_FORBIDDEN),
        )


def test_removing_general_access_leaves_direct_access_intact():
    with given(_GIVEN) as context:
        owner_id = context.user.id
        agent_id = context.agent.id
        context.client.put(
            _access_settings_url(agent_id),
            json={
                "general_access_role_id": str(AGENT_VIEWER_ROLE_ID),
                "assignments": [],
            },
            headers=_auth(context),
        )
        _switch_to_member(context)
        member_id = context.user.id
        repository: AgentRepository = context.injector.get(AgentRepository)
        repository.delegate.save(
            AgentAccess(
                organization_id=context.organization.id,
                membership_id=context.organization_user.id,
                agent_id=agent_id,
                access_role_id=AGENT_EDITOR_ROLE_ID,
            )
        )
        there_is_an_access_token_for_user(owner_id)(context)
        removed_general = context.client.put(
            _access_settings_url(agent_id),
            json={
                "general_access_role_id": None,
                "assignments": [
                    {
                        "user_id": str(member_id),
                        "access_role_id": str(AGENT_EDITOR_ROLE_ID),
                    }
                ],
            },
            headers=_auth(context),
        )
        there_is_an_access_token_for_user(member_id)(context)

        still_editable = context.client.patch(
            f"{_BASE}/{agent_id}",
            json={"name": "Direct Editor survives"},
            headers=_auth(context),
        )

        assert_that(removed_general.status_code, equal_to(status.HTTP_200_OK))
        assert_that(still_editable.status_code, equal_to(status.HTTP_200_OK))


def test_access_settings_snapshot_replaces_general_and_direct_access():
    with given(_GIVEN) as context:
        agent_id = context.agent.id
        first_member, first_membership = _add_target_member(context)
        second_member, second_membership = _add_target_member(context)
        repository: AgentRepository = context.injector.get(AgentRepository)
        repository.delegate.save(
            AgentAccess(
                organization_id=context.organization.id,
                membership_id=first_membership.id,
                agent_id=agent_id,
                access_role_id=AGENT_EDITOR_ROLE_ID,
            )
        )

        response = context.client.put(
            _access_settings_url(agent_id),
            json={
                "general_access_role_id": str(AGENT_VIEWER_ROLE_ID),
                "assignments": [
                    {
                        "user_id": str(second_member.id),
                        "access_role_id": str(AGENT_EDITOR_ROLE_ID),
                    }
                ],
            },
            headers=_auth(context),
        )
        assigned = context.client.get(_access_settings_url(agent_id), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            response.json()["general_access"]["role"]["id"],
            equal_to(str(AGENT_VIEWER_ROLE_ID)),
        )
        assert_that(
            [item["user_id"] for item in response.json()["assignments"]],
            contains_inanyorder(str(second_member.id)),
        )
        assert_that(
            [item["user_id"] for item in assigned.json()["assignments"]],
            contains_inanyorder(str(second_member.id)),
        )
        assert_that(
            [item["user_id"] for item in assigned.json()["assignments"]],
            is_not(has_item(str(first_member.id))),
        )
        messages = sorted(_outbox_messages(context), key=lambda message: message.event_name)
        assert_that(
            [message.event_name for message in messages],
            equal_to(["agent.access.granted", "agent.access.revoked", "agent.general_access.changed"]),
        )
        granted = next(message for message in messages if message.event_name == "agent.access.granted")
        revoked = next(message for message in messages if message.event_name == "agent.access.revoked")
        general = next(message for message in messages if message.event_name == "agent.general_access.changed")
        assert_that(granted.payload["agent_id"], equal_to(str(agent_id)))
        assert_that(granted.payload["membership_id"], equal_to(str(second_membership.id)))
        assert_that(revoked.payload["membership_id"], equal_to(str(first_membership.id)))
        assert_that(general.payload["new_access_role_id"], equal_to(str(AGENT_VIEWER_ROLE_ID)))
        assert_that(granted.payload["actor_display"], equal_to("admin@example.com"))
        assert_that(granted.payload["subject_display"], equal_to(context.agent.name))
        # subject_display names the Agent (the event's Subject); member_display is a
        # separate write-time snapshot of the target member's own name, so the audit
        # trail can answer "who was granted/revoked access" without a live join once
        # the membership or user is later deleted.
        assert_that(granted.payload["member_display"], equal_to(second_member.full_name))
        assert_that(revoked.payload["member_display"], equal_to(first_member.full_name))
        # Regression: replace_access_settings must attempt to enqueue its staged
        # deliveries immediately, like every other event-emitting mutation, instead of
        # leaving them stuck at PENDING forever with no enqueue attempt at all. The
        # immediate enqueue itself is best-effort (falls back to background
        # reconciliation on failure), so whether it's already ENQUEUED here depends on
        # Redis being reachable — see test_agents.py::test_start_agent_emits_started_
        # domain_event_and_delivery for the same pattern.
        event_ids = {message.event_id for message in messages}
        deliveries = [delivery for delivery in _event_deliveries(context) if delivery.event_id in event_ids]
        assert_that(len(deliveries), equal_to(3))
        for delivery in deliveries:
            assert_that(delivery.status, is_in([EventDeliveryStatus.PENDING, EventDeliveryStatus.ENQUEUED]))


def test_access_settings_role_change_for_existing_member_emits_granted_event():
    with given(_GIVEN) as context:
        agent_id = context.agent.id
        member, membership = _add_target_member(context)
        repository: AgentRepository = context.injector.get(AgentRepository)
        repository.delegate.save(
            AgentAccess(
                organization_id=context.organization.id,
                membership_id=membership.id,
                agent_id=agent_id,
                access_role_id=AGENT_VIEWER_ROLE_ID,
            )
        )

        response = context.client.put(
            _access_settings_url(agent_id),
            json={
                "general_access_role_id": None,
                "assignments": [
                    {
                        "user_id": str(member.id),
                        "access_role_id": str(AGENT_EDITOR_ROLE_ID),
                    }
                ],
            },
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            [item["access_role"]["id"] for item in response.json()["assignments"]],
            contains_inanyorder(str(AGENT_EDITOR_ROLE_ID)),
        )
        # Regression: changing an already-assigned member's role must itself be
        # audited — before this fix, the repository silently updated AgentAccess
        # in place with no event staged at all, so role changes for existing
        # assignments left no audit trail (unlike brand-new grants or revocations).
        messages = _outbox_messages(context)
        assert_that([message.event_name for message in messages], equal_to(["agent.access.granted"]))
        granted = messages[0]
        assert_that(granted.payload["membership_id"], equal_to(str(membership.id)))
        assert_that(granted.payload["access_role_id"], equal_to(str(AGENT_EDITOR_ROLE_ID)))
        assert_that(granted.payload["previous_access_role_id"], equal_to(str(AGENT_VIEWER_ROLE_ID)))
        assert_that(granted.payload["member_display"], equal_to(member.full_name))


def test_access_settings_role_change_to_same_role_emits_no_event():
    with given(_GIVEN) as context:
        agent_id = context.agent.id
        member, membership = _add_target_member(context)
        repository: AgentRepository = context.injector.get(AgentRepository)
        repository.delegate.save(
            AgentAccess(
                organization_id=context.organization.id,
                membership_id=membership.id,
                agent_id=agent_id,
                access_role_id=AGENT_VIEWER_ROLE_ID,
            )
        )

        response = context.client.put(
            _access_settings_url(agent_id),
            json={
                "general_access_role_id": None,
                "assignments": [
                    {
                        "user_id": str(member.id),
                        "access_role_id": str(AGENT_VIEWER_ROLE_ID),
                    }
                ],
            },
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(_outbox_messages(context), equal_to([]))


def test_access_settings_rolls_back_when_snapshot_is_invalid():
    with given(_GIVEN) as context:
        agent_id = context.agent.id
        member, membership = _add_target_member(context)
        repository: AgentRepository = context.injector.get(AgentRepository)
        repository.delegate.save(
            AgentAccess(
                organization_id=context.organization.id,
                membership_id=membership.id,
                agent_id=agent_id,
                access_role_id=AGENT_VIEWER_ROLE_ID,
            )
        )

        response = context.client.put(
            _access_settings_url(agent_id),
            json={
                "general_access_role_id": str(AGENT_EDITOR_ROLE_ID),
                "assignments": [
                    {
                        "user_id": str(uuid7()),
                        "access_role_id": str(AGENT_EDITOR_ROLE_ID),
                    }
                ],
            },
            headers=_auth(context),
        )
        general_access = context.client.get(_access_settings_url(agent_id), headers=_auth(context))
        assigned = context.client.get(_access_settings_url(agent_id), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
        assert_that(general_access.json()["general_access"]["role"], none())
        assert_that(
            [item["user_id"] for item in assigned.json()["assignments"]],
            contains_inanyorder(str(member.id)),
        )


def test_owner_created_agent_share_settings_round_trip_without_creator_row():
    # Regression for the Share dialog 400: agent creators who are Org Owners/Admins
    # already have implicit full access (see ShareAddMember, which refuses to grant
    # them explicit access too), so their system-managed creator row must be hidden
    # from GET and never round-tripped back through PUT — but must also survive the
    # save (not be deleted just because the client never resubmitted it), so the
    # creator keeps access if later demoted to Member.
    with given(_GIVEN[:-1]) as context:  # drop the shared there_is_an_agent(); create via the real API instead
        client = context.client
        create_response = client.post(
            _BASE,
            json={
                "name": "Owner Created Agent",
                "platform": "slack",
                "slack_bot_token": "xoxb-real-bot-token",
                "slack_app_token": "xapp-1-real-app-token",
                "template_key": "test-template",
            },
            headers=_auth(context),
        )
        agent_id = UUID(create_response.json()["id"])

        read_response = client.get(_access_settings_url(agent_id), headers=_auth(context))
        # What the Share dialog actually does on Save: echo back exactly what GET returned.
        round_trip = client.put(
            _access_settings_url(agent_id),
            json={
                "general_access_role_id": read_response.json()["general_access"]["role"],
                "assignments": [
                    {"user_id": item["user_id"], "access_role_id": item["access_role"]["id"]}
                    for item in read_response.json()["assignments"]
                ],
            },
            headers=_auth(context),
        )

        # Demote the creator and confirm their hidden row survived the round-trip.
        membership_repository: OrganizationUserRepository = context.injector.get(OrganizationUserRepository)
        membership = membership_repository.get_by_user_id_and_organization_id(context.user.id, context.organization.id)
        assert membership is not None
        membership.role = OrganizationRole.MEMBER
        membership_repository.save(membership)
        detail_after_demotion = client.get(f"{_BASE}/{agent_id}", headers=_auth(context))

        assert_that(create_response.status_code, equal_to(status.HTTP_201_CREATED))
        assert_that(read_response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(read_response.json()["assignments"], equal_to([]))
        assert_that(round_trip.status_code, equal_to(status.HTTP_200_OK))
        assert_that(detail_after_demotion.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            detail_after_demotion.json()["allowed_actions"],
            has_item(PermissionKey.AGENT_ACCESS_MANAGE.value),
        )


def test_access_settings_rejects_duplicate_assignment_users():
    with given(_GIVEN) as context:
        member, _ = _add_target_member(context)

        response = context.client.put(
            _access_settings_url(context.agent.id),
            json={
                "general_access_role_id": None,
                "assignments": [
                    {
                        "user_id": str(member.id),
                        "access_role_id": str(AGENT_VIEWER_ROLE_ID),
                    },
                    {
                        "user_id": str(member.id),
                        "access_role_id": str(AGENT_EDITOR_ROLE_ID),
                    },
                ],
            },
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
