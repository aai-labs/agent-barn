"""AF-411 Agent Tasks: an Agent writes its own Tasks and Notes, and people read them
only through Agents they may read Tasks on."""

from datetime import UTC, datetime
from uuid import UUID, uuid7

import pytest
from fastapi import HTTPException, status
from hamcrest import assert_that, calling, contains_exactly, contains_inanyorder, equal_to, has_properties, raises

from api.domains.agent_tasks.models import (
    AgentTaskCreate,
    AgentTaskFileCreate,
    AgentTaskFilter,
    AgentTaskNoteCreate,
    AgentTaskStatus,
)
from api.domains.agent_tasks.service import AgentTaskService
from api.domains.agents.repository import AgentRepository
from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID, PERMISSION_ID_BY_KEY, PermissionKey
from api.domains.rbac.models import AgentAccessRole, AgentAccessRolePermission
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.shared.models import Pagination
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_agent_access,
    there_is_an_agent,
    there_is_an_agent_in_another_org,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization
from api.tests.steps.user import there_is_a_user

_GIVEN = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization(),
]
_FIRST_PAGE = Pagination(page=1, size=20)


def _admin_is_signed_in():
    def step(context):
        there_is_a_user(
            email=f"admin-{uuid7()}@example.com", role=OrganizationRole.ADMIN, organization_id=context.organization.id
        )(context)

    return step


def _member_is_signed_in():
    def step(context):
        there_is_a_user(
            email=f"member-{uuid7()}@example.com", role=OrganizationRole.MEMBER, organization_id=context.organization.id
        )(context)

    return step


def _remember_agent_as(name: str):
    def step(context):
        setattr(context, name, context.agent)

    return step


def _custom_role(context, permissions: set[PermissionKey]) -> AgentAccessRole:
    repository: AgentRepository = context.injector.get(AgentRepository)
    role = AgentAccessRole(organization_id=context.organization.id, name=f"CUSTOM-{uuid7()}", is_system=False)
    repository.delegate.save(role)
    for permission in permissions:
        repository.delegate.save(
            AgentAccessRolePermission(role_id=role.id, permission_id=PERMISSION_ID_BY_KEY[permission])
        )
    return role


def _service(context) -> AgentTaskService:
    return context.injector.get(AgentTaskService)


def _create(context, agent_id: UUID, title: str = "Reconcile invoices", **fields):
    return _service(context).create_task(context.organization.id, agent_id, AgentTaskCreate(title=title, **fields))


def _status_code(call) -> int:
    with pytest.raises(HTTPException) as raised:
        call()
    return raised.value.status_code


# Agent writes


def test_an_agent_creates_an_open_task():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        with when("the Agent records a Task"):
            task = _create(context, context.agent.id, description="Match March invoices to payments")

            with then("it is open and belongs to that Agent"):
                assert_that(
                    task,
                    has_properties(
                        agent_id=context.agent.id,
                        title="Reconcile invoices",
                        description="Match March invoices to payments",
                        status=AgentTaskStatus.OPEN,
                    ),
                )


def test_a_task_title_cannot_be_blank():
    assert_that(calling(AgentTaskCreate).with_args(title="   "), raises(ValueError))


def test_a_deleted_agent_cannot_create_tasks():
    with given([*_GIVEN, there_is_an_agent(deleted=True)]) as context:
        assert_that(
            _status_code(lambda: _create(context, context.agent.id)),
            equal_to(status.HTTP_404_NOT_FOUND),
        )


def test_a_task_cannot_be_created_for_an_agent_in_another_organization():
    with given([*_GIVEN, there_is_an_agent_in_another_org()]) as context:
        assert_that(
            _status_code(lambda: _create(context, context.other_org_agent.id)),
            equal_to(status.HTTP_404_NOT_FOUND),
        )


def test_an_agent_moves_its_task_through_statuses():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        task = _create(context, context.agent.id)

        with when("the Agent marks it in progress and then done"):
            _service(context).update_status(
                context.organization.id, context.agent.id, task.id, AgentTaskStatus.IN_PROGRESS
            )
            updated = _service(context).update_status(
                context.organization.id, context.agent.id, task.id, AgentTaskStatus.DONE
            )

            with then("the Task is done"):
                assert_that(updated.status, equal_to(AgentTaskStatus.DONE))


def test_an_agent_cannot_change_another_agents_task():
    with given(
        [*_GIVEN, there_is_an_agent(), _remember_agent_as("first"), there_is_an_agent(name="Second")]
    ) as context:
        task = _create(context, context.first.id)

        assert_that(
            _status_code(
                lambda: _service(context).update_status(
                    context.organization.id, context.agent.id, task.id, AgentTaskStatus.FAILED
                )
            ),
            equal_to(status.HTTP_404_NOT_FOUND),
        )


def test_notes_form_the_tasks_timeline_in_order():
    with given([*_GIVEN, there_is_an_agent(), _admin_is_signed_in()]) as context:
        task = _create(context, context.agent.id)
        service = _service(context)

        with when("the Agent adds two notes"):
            service.add_note(context.organization.id, context.agent.id, task.id, AgentTaskNoteCreate(body="Started"))
            service.add_note(context.organization.id, context.agent.id, task.id, AgentTaskNoteCreate(body="Found 3"))

            with then("the Task shows them oldest first"):
                detail = service.get_task(context.agent.id, task.id, context.current_user_context)
                assert_that([note.body for note in detail.notes], contains_exactly("Started", "Found 3"))


def test_a_note_cannot_be_added_to_another_agents_task():
    with given(
        [*_GIVEN, there_is_an_agent(), _remember_agent_as("first"), there_is_an_agent(name="Second")]
    ) as context:
        task = _create(context, context.first.id)

        assert_that(
            _status_code(
                lambda: _service(context).add_note(
                    context.organization.id, context.agent.id, task.id, AgentTaskNoteCreate(body="Not mine")
                )
            ),
            equal_to(status.HTTP_404_NOT_FOUND),
        )


# Reads by people


def test_an_admin_lists_an_agents_tasks_newest_first():
    with given([*_GIVEN, there_is_an_agent(), _admin_is_signed_in()]) as context:
        _create(context, context.agent.id, title="First")
        _create(context, context.agent.id, title="Second")

        page = _service(context).list_agent_tasks(
            context.agent.id, context.current_user_context, AgentTaskFilter(), _FIRST_PAGE
        )

        assert_that(([task.title for task in page.items], page.total), equal_to((["Second", "First"], 2)))


def test_an_agents_tasks_can_be_filtered_by_status_and_paginated():
    with given([*_GIVEN, there_is_an_agent(), _admin_is_signed_in()]) as context:
        for title in ("One", "Two", "Three"):
            _create(context, context.agent.id, title=title)
        failed = _create(context, context.agent.id, title="Broken")
        _service(context).update_status(context.organization.id, context.agent.id, failed.id, AgentTaskStatus.FAILED)

        open_page = _service(context).list_agent_tasks(
            context.agent.id,
            context.current_user_context,
            AgentTaskFilter(status=AgentTaskStatus.OPEN),
            Pagination(page=2, size=2),
        )

        assert_that(([task.title for task in open_page.items], open_page.total), equal_to((["One"], 3)))


def test_a_member_without_access_cannot_see_an_agents_tasks():
    with given([*_GIVEN, there_is_an_agent(), _member_is_signed_in()]) as context:
        _create(context, context.agent.id)

        assert_that(
            _status_code(
                lambda: _service(context).list_agent_tasks(
                    context.agent.id, context.current_user_context, AgentTaskFilter(), _FIRST_PAGE
                )
            ),
            equal_to(status.HTTP_404_NOT_FOUND),
        )


def test_an_agent_viewer_can_read_its_tasks():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            _member_is_signed_in(),
            there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID),
        ]
    ) as context:
        task = _create(context, context.agent.id)

        detail = _service(context).get_task(context.agent.id, task.id, context.current_user_context)

        assert_that(detail.id, equal_to(task.id))


def test_a_member_who_sees_the_agent_without_task_read_is_forbidden():
    with given([*_GIVEN, there_is_an_agent(), _member_is_signed_in()]) as context:
        role = _custom_role(context, {PermissionKey.AGENT_READ})
        there_is_agent_access(access_role_id=role.id)(context)
        task = _create(context, context.agent.id)

        assert_that(
            _status_code(lambda: _service(context).get_task(context.agent.id, task.id, context.current_user_context)),
            equal_to(status.HTTP_403_FORBIDDEN),
        )


def test_a_task_is_not_found_through_a_different_agent():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            _remember_agent_as("first"),
            there_is_an_agent(name="Second"),
            _admin_is_signed_in(),
        ]
    ) as context:
        task = _create(context, context.first.id)

        assert_that(
            _status_code(lambda: _service(context).get_task(context.agent.id, task.id, context.current_user_context)),
            equal_to(status.HTTP_404_NOT_FOUND),
        )


def test_the_organization_list_shows_only_tasks_on_agents_the_member_can_read():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(name="Hidden"),
            _remember_agent_as("hidden"),
            there_is_an_agent(name="Shared"),
            _member_is_signed_in(),
            there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID),
        ]
    ) as context:
        _create(context, context.hidden.id, title="Hidden work")
        _create(context, context.agent.id, title="Shared work")

        page = _service(context).list_organization_tasks(context.current_user_context, AgentTaskFilter(), _FIRST_PAGE)

        assert_that(([task.title for task in page.items], page.total), equal_to((["Shared work"], 1)))


def test_the_organization_list_shows_an_admin_every_agents_tasks_but_no_other_organizations():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(name="One"),
            _remember_agent_as("one"),
            there_is_an_agent(name="Two"),
            _remember_agent_as("two"),
            there_is_an_agent_in_another_org(),
            _admin_is_signed_in(),
        ]
    ) as context:
        _create(context, context.one.id, title="One's work")
        _create(context, context.two.id, title="Two's work")
        _service(context).create_task(
            context.other_org_agent.organization_id, context.other_org_agent.id, AgentTaskCreate(title="Elsewhere")
        )

        page = _service(context).list_organization_tasks(context.current_user_context, AgentTaskFilter(), _FIRST_PAGE)

        assert_that([task.title for task in page.items], contains_inanyorder("One's work", "Two's work"))


def test_general_access_lets_every_member_read_the_agents_tasks():
    with given([*_GIVEN, there_is_an_agent(), _member_is_signed_in()]) as context:
        repository: AgentRepository = context.injector.get(AgentRepository)
        context.agent.general_access_role_id = AGENT_VIEWER_ROLE_ID
        repository.delegate.save(context.agent)
        _create(context, context.agent.id, title="Visible to all")

        page = _service(context).list_organization_tasks(context.current_user_context, AgentTaskFilter(), _FIRST_PAGE)

        assert_that([task.title for task in page.items], contains_exactly("Visible to all"))


@pytest.mark.parametrize("write", ["status", "note", "file"])
def test_an_agent_cannot_write_to_its_tasks_once_deleted(write: str):
    with given([*_GIVEN, there_is_an_agent()]) as context:
        task = _create(context, context.agent.id)
        context.agent.deleted_at = datetime.now(UTC)
        context.injector.get(AgentRepository).delegate.save(context.agent)
        service = _service(context)
        org_id, agent_id = context.organization.id, context.agent.id
        writes = {
            "status": lambda: service.update_status(org_id, agent_id, task.id, AgentTaskStatus.DONE),
            "note": lambda: service.add_note(org_id, agent_id, task.id, AgentTaskNoteCreate(body="Late")),
            "file": lambda: service.attach_file(org_id, agent_id, task.id, AgentTaskFileCreate(artifact_id=uuid7())),
        }

        assert_that(_status_code(writes[write]), equal_to(status.HTTP_404_NOT_FOUND))


def test_the_organization_list_can_be_filtered_by_agent():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(name="One"),
            _remember_agent_as("one"),
            there_is_an_agent(name="Two"),
            _admin_is_signed_in(),
        ]
    ) as context:
        _create(context, context.one.id, title="One's work")
        _create(context, context.agent.id, title="Two's work")

        page = _service(context).list_organization_tasks(
            context.current_user_context, AgentTaskFilter(agent_id=context.one.id), _FIRST_PAGE
        )

        assert_that(([task.title for task in page.items], page.total), equal_to((["One's work"], 1)))


def test_filtering_by_an_agent_the_member_cannot_read_shows_nothing():
    with given([*_GIVEN, there_is_an_agent(name="Hidden"), _member_is_signed_in()]) as context:
        _create(context, context.agent.id, title="Hidden work")

        page = _service(context).list_organization_tasks(
            context.current_user_context, AgentTaskFilter(agent_id=context.agent.id), _FIRST_PAGE
        )

        assert_that((page.items, page.total), equal_to(([], 0)))
