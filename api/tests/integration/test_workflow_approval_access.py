"""Who may decide a workflow approval request, and how decisions on one request are fenced (AF-390).

Deciding requires `agent.update` on the run's Agent at decision time. Per
docs/features/rbac/IMPLEMENTATION-BRIEF.md, a concealed Agent answers 404 and a
visible Agent without the operation answers 403.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from hamcrest import assert_that, contains_inanyorder, equal_to, has_length
from sqlalchemy import text

from api.domains.agents.repository import AgentRepository
from api.domains.rbac.catalog import (
    AGENT_EDITOR_ROLE_ID,
    AGENT_VIEWER_ROLE_ID,
    PERMISSION_ID_BY_KEY,
    PermissionKey,
)
from api.domains.rbac.models import AgentAccessRole, AgentAccessRolePermission
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.integration.test_workflow_runs import _RUN_GIVEN, attempt, start
from api.tests.integration.test_workflows import base, switch_member
from api.tests.steps.agent import there_is_agent_access
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

COMMAND = "rm -rf ./out && ./deploy.sh"


# --- Setup steps -----------------------------------------------------------------------------------------------


def a_running_attempt(context):
    """Start a run as the Organization Owner and admit its first attempt."""
    response, _, _ = start(context)
    _repository, row, token = attempt(context, response.json()["id"])
    return row, token


def owner_is_remembered(context):
    context.owner_token = context.access_token
    context.owner_id = context.user.id
    context.agent_url = base(context)


def a_parked_request(context):
    context.row, context.capability = a_running_attempt(context)
    context.request_id = raise_request(context, context.row, context.capability)
    park(context, context.row, context.capability, context.request_id)


def a_member_with(access):
    """Switch the caller to a new Member of the Organization and grant them `access`."""

    def step(context):
        switch_member(context)
        context.member_id = context.user.id
        access(context)

    return step


def explicit(role_id):
    return lambda context: there_is_agent_access(access_role_id=role_id)(context)


def general(role_id):
    def grant(context):
        context.agent.general_access_role_id = role_id
        context.injector.get(AgentRepository).save(context.agent)

    return grant


def custom_role_with_agent_update(context):
    delegate = context.injector.get(PostgresRepositoryDelegate)
    role = AgentAccessRole(organization_id=context.organization.id, name=f"Approver {uuid4()}", is_system=False)
    delegate.save(role)
    for key in (PermissionKey.AGENT_READ, PermissionKey.AGENT_UPDATE):
        delegate.save(AgentAccessRolePermission(role_id=role.id, permission_id=PERMISSION_ID_BY_KEY[key]))
    there_is_agent_access(access_role_id=role.id)(context)


def nothing(_context):
    """A Member of the Organization with no Agent Access and no General Access."""


def a_user_of_another_organization(context):
    """An Owner of another Organization, addressing this Agent's run through their own Organization's URLs.

    Calling the Agent's own Organization URL is refused earlier by Organization membership (403), as for every
    Organization-scoped route; see test_cross_org_isolation.py.
    """
    there_is_a_user(email=f"outsider-{uuid4()}@example.com", organization_id=uuid4())(context)
    there_is_an_access_token_for_user()(context)
    context.caller_url = base(context)


# --- Actions ---------------------------------------------------------------------------------------------------


def _runtime(row, token, path=""):
    return f"/workflow-runtime/v1/attempts/{row.id}/approvals{path}", {"Authorization": f"Bearer {token}"}


def raise_request(context, row, token, command=COMMAND):
    url, headers = _runtime(row, token)
    response = context.client.post(url, headers=headers, json={"command": command, "runtime_run_id": "hermes-run-1"})
    assert_that(response.status_code, equal_to(200), response.text)
    return response.json()["id"]


def park(context, row, token, request_id):
    url, headers = _runtime(row, token, f"/{request_id}/park")
    response = context.client.post(url, headers=headers, json={})
    assert_that(response.json(), equal_to({"state": "PARKED"}))


def decide(context, run_id, request_id, token, decision="approve", url=None):
    return context.client.post(
        (url or context.agent_url) + f"/workflow-runs/{run_id}/approvals/{request_id}/decision",
        headers={"Authorization": f"Bearer {token}"},
        json={"decision": decision},
    )


def run_detail(context, run_id):
    return context.client.get(
        context.agent_url + f"/workflow-runs/{run_id}", headers={"Authorization": f"Bearer {context.owner_token}"}
    ).json()


def decided_history(context, run_id):
    events = context.client.get(
        context.agent_url + f"/workflow-runs/{run_id}/history?page_size=100",
        headers={"Authorization": f"Bearer {context.owner_token}"},
    ).json()["items"]
    return [event for event in events if event["kind"] == "APPROVAL_DECIDED"]


# --- Who may decide --------------------------------------------------------------------------------------------

_GIVEN = [*_RUN_GIVEN, owner_is_remembered, a_parked_request]


@pytest.mark.parametrize(
    "access",
    [explicit(AGENT_EDITOR_ROLE_ID), general(AGENT_EDITOR_ROLE_ID), custom_role_with_agent_update],
    ids=["agent-editor", "general-access-editor", "custom-role-with-agent-update"],
)
def test_a_member_whose_access_grants_agent_update_decides_and_is_recorded_as_the_decider(access) -> None:
    with given([*_GIVEN, a_member_with(access)]) as context:
        with when("the Member approves the parked request"):
            response = decide(context, context.row.run_id, context.request_id, context.access_token)

        with then("the decision is accepted and attributed to that Member"):
            assert_that(response.status_code, equal_to(200), response.text)
            approval = response.json()["approval"]
            assert_that(
                (approval["state"], approval["decided_by_user_id"]), equal_to(("APPROVED", str(context.member_id)))
            )


@pytest.mark.parametrize(
    "access", [explicit(AGENT_VIEWER_ROLE_ID), general(AGENT_VIEWER_ROLE_ID)], ids=["explicit", "general"]
)
def test_an_agent_viewer_sees_the_agent_but_is_forbidden_to_decide(access) -> None:
    with given([*_GIVEN, a_member_with(access)]) as context:
        with when("the Viewer tries to approve"):
            response = decide(context, context.row.run_id, context.request_id, context.access_token)

        with then("the operation is forbidden and the request still awaits a decision"):
            assert_that(response.status_code, equal_to(403))
            assert_that(run_detail(context, context.row.run_id)["approval"]["state"], equal_to("PARKED"))


@pytest.mark.parametrize(
    "outsider", [a_member_with(nothing), a_user_of_another_organization], ids=["unassigned-member", "other-org"]
)
def test_a_caller_who_cannot_see_the_agent_is_told_it_does_not_exist(outsider) -> None:
    with given([*_GIVEN, outsider]) as context:
        with when("the caller tries to approve"):
            url = getattr(context, "caller_url", None)
            response = decide(context, context.row.run_id, context.request_id, context.access_token, url=url)

        with then("the Agent is concealed and the request still awaits a decision"):
            assert_that(response.status_code, equal_to(404))
            assert_that(run_detail(context, context.row.run_id)["approval"]["state"], equal_to("PARKED"))


def _demote_to_viewer(context):
    with context.injector.get(PostgresRepositoryDelegate).engine.begin() as connection:
        connection.execute(
            text("UPDATE agent_access SET access_role_id = :role WHERE agent_id = :agent_id"),
            {"role": AGENT_VIEWER_ROLE_ID, "agent_id": context.agent.id},
        )


def _unassign(context):
    with context.injector.get(PostgresRepositoryDelegate).engine.begin() as connection:
        connection.execute(text("DELETE FROM agent_access WHERE agent_id = :agent_id"), {"agent_id": context.agent.id})


@pytest.mark.parametrize(
    ("revoke", "refusal"), [(_demote_to_viewer, 403), (_unassign, 404)], ids=["demoted", "unassigned"]
)
def test_authority_is_checked_when_deciding_not_when_the_request_was_raised(revoke, refusal) -> None:
    # The Editor is assigned before the request is raised, so their authority existed when it was raised.
    with given(
        [*_RUN_GIVEN, owner_is_remembered, a_member_with(explicit(AGENT_EDITOR_ROLE_ID)), a_parked_request]
    ) as context:
        revoke(context)

        with when("the former Editor tries to approve"):
            response = decide(context, context.row.run_id, context.request_id, context.access_token)

        with then("the decision is refused"):
            assert_that(response.status_code, equal_to(refusal))

        with then("the Organization Owner can still decide the request"):
            owner = decide(context, context.row.run_id, context.request_id, context.owner_token)
            assert_that(owner.status_code, equal_to(200), owner.text)
            assert_that(owner.json()["approval"]["decided_by_user_id"], equal_to(str(context.owner_id)))


# --- Which request may be decided ------------------------------------------------------------------------------


def test_a_request_of_another_run_cannot_be_decided_through_this_run() -> None:
    with given([*_RUN_GIVEN, owner_is_remembered, a_parked_request]) as context:
        other_row, other_capability = a_running_attempt(context)
        other_request = raise_request(context, other_row, other_capability)
        park(context, other_row, other_capability, other_request)

        with when("the other run's request is decided through the first run"):
            response = decide(context, context.row.run_id, other_request, context.owner_token)

        with then("the decision is refused"):
            assert_that(response.status_code, equal_to(409))

        with then("both runs still await their own decisions"):
            assert_that(run_detail(context, context.row.run_id)["approval"]["state"], equal_to("PARKED"))
            assert_that(run_detail(context, other_row.run_id)["approval"]["state"], equal_to("PARKED"))

        with then("the other run's request is still decidable through its own run"):
            own = decide(context, other_row.run_id, other_request, context.owner_token)
            assert_that(own.status_code, equal_to(200), own.text)


@pytest.mark.parametrize("decisions", [("approve", "approve"), ("approve", "decline")], ids=["same", "opposite"])
def test_concurrent_decisions_on_one_request_record_exactly_one(decisions) -> None:
    with given(_GIVEN) as context:
        barrier = threading.Barrier(len(decisions))

        def submit(decision):
            barrier.wait()
            response = decide(context, context.row.run_id, context.request_id, context.owner_token, decision)
            return decision, response.status_code

        with when("two decisions on the same request arrive together"):
            with ThreadPoolExecutor(max_workers=len(decisions)) as executor:
                results = list(executor.map(submit, decisions))

        with then("exactly one is accepted and the other conflicts"):
            assert_that([status for _, status in results], contains_inanyorder(200, 409))

        with then("only the accepted decision is recorded"):
            winner = next(decision for decision, status in results if status == 200)
            approvals = run_detail(context, context.row.run_id)["approvals"]
            assert_that(approvals, has_length(1))
            assert_that(approvals[0]["state"], equal_to("APPROVED" if winner == "approve" else "DECLINED"))
            assert_that(decided_history(context, context.row.run_id), has_length(1))
