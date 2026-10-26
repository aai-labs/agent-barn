"""Integration tests for a Platform Administrator's side of Agent Add-ons.

The contract under test:

- only a Platform Administrator lists every request across Organizations, filtered by state,
  Organization or a search, each row naming the Organization, Agent, runtime, requester and
  the exact request with its why; a read-only API key can list but not decide;
- a Pending request is approved or rejected (with a reason); an Approved one is revoked; any
  other move is refused (409), and repeating a decision is a no-op that records nothing;
- each decision leaves one Organization-scoped audit Event naming the administrator as a User
  when they have no Membership there;
- Platform Administrators are emailed of each new request and the requester of each decision,
  once per delivery however often it is retried.
"""

from uuid import uuid7

import pytest
from fastapi import status
from hamcrest import (
    assert_that,
    contains_exactly,
    contains_string,
    empty,
    equal_to,
    has_entries,
    has_length,
    is_not,
    none,
)

from api.domains.agent_addons.event_handlers import AgentAddonEmailHandler
from api.domains.agent_addons.models import AgentAddonState
from api.domains.agents.models import Agent, AgentStatus
from api.domains.events import ActorIdentityType
from api.domains.events.catalog import (
    AGENT_ADDON_APPROVED,
    AGENT_ADDON_EMAIL_HANDLER,
    AGENT_ADDON_REJECTED,
    AGENT_ADDON_REQUESTED,
    AGENT_ADDON_REVOKED,
)
from api.domains.events.handlers import EventDeliveryContext
from api.domains.events.models import EventDelivery
from api.domains.users.models import User
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.email.client import EmailClient
from api.infrastructure.email.models import Email
from api.infrastructure.kubernetes.client import KubernetesClient
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector
from api.tests.steps.agent import MockK8sModule, MockLiteLLMModule, there_is_an_agent, use_org_for_auth
from api.tests.steps.agent_addons import (
    ADDON_ENV,
    HUMANIZE,
    PLATFORM_ADDONS,
    admin,
    auth,
    decide,
    delegate,
    envelope,
    events,
    member,
    platform_admin,
    read_only_key,
    request_addon,
    stored_addon,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization, there_is_an_organization_with_user_and_access_token
from api.tests.steps.template import there_is_a_template

_GIVEN = [
    ADDON_ENV,
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(email="addons-requester@example.com"),
    use_org_for_auth(),
    there_is_a_template(),
    there_is_an_agent(name="Drafting Agent"),
]


def _list(context, token: str, **params):
    return context.client.get(PLATFORM_ADDONS, params=params, headers=auth(token))


def _pending(context) -> str:
    return request_addon(context, context.access_token).json()["id"]


# --- who may review -----------------------------------------------------------------------------


def test_only_a_platform_administrator_lists_or_decides():
    with given(_GIVEN) as context:
        addon_id = _pending(context)
        organization_admin = admin(context)

        for token in (context.access_token, organization_admin):
            assert_that(_list(context, token).status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(decide(context, token, addon_id, "approve").status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(stored_addon(context, addon_id).state, equal_to(AgentAddonState.PENDING))


def test_a_read_only_api_key_lists_but_cannot_decide():
    with given(_GIVEN) as context:
        addon_id = _pending(context)
        key = read_only_key(context, platform_admin(context))

        assert_that(_list(context, key).status_code, equal_to(status.HTTP_200_OK))
        for action in ("approve", "reject", "revoke"):
            assert_that(decide(context, key, addon_id, action, "No.").status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(stored_addon(context, addon_id).state, equal_to(AgentAddonState.PENDING))


def test_an_unknown_request_is_not_found():
    with given(_GIVEN) as context:
        response = decide(context, platform_admin(context), uuid7(), "approve")

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


# --- the list ------------------------------------------------------------------------------------


def test_the_list_shows_every_organizations_requests_with_what_a_reviewer_needs():
    with given(_GIVEN) as context:
        home = context.organization
        home_agent = context.agent
        addon_id = _pending(context)
        there_is_an_organization(name="Acme")(context)
        acme = context.organization
        there_is_an_agent(name="Acme Agent", organization_id=acme.id)(context)
        acme_admin, _ = member(context, OrganizationRole.ADMIN, organization_id=acme.id)
        context.client.post(
            f"/api/v1/organizations/{acme.id}/agents/{context.agent.id}/addons",
            json={"kind": "command", "name": "fonts", "command": "echo fonts", "reason": "Rendering."},
            headers=auth(acme_admin),
        )
        context.organization, context.agent = home, home_agent
        token = platform_admin(context)

        with when("the administrator lists every request"):
            body = _list(context, token).json()

        with then("both Organizations' requests are there, newest first"):
            assert_that(body["total"], equal_to(2))
            assert_that([item["organization_name"] for item in body["items"]], contains_exactly("Acme", home.name))

        with then("each names where it comes from, who asked, and exactly what and why"):
            assert_that(
                body["items"][1],
                has_entries(
                    id=addon_id,
                    organization_id=str(home.id),
                    agent_id=str(home_agent.id),
                    agent_name="Drafting Agent",
                    agent_type="openclaw",
                    agent_deleted=False,
                    kind="pip",
                    name="humanize",
                    spec=has_entries(version="1.2.0"),
                    reason=HUMANIZE["reason"],
                    state="PENDING",
                    requested_by=has_entries(email="addons-requester@example.com"),
                    decided_by=None,
                ),
            )


def test_the_list_filters_by_state_organization_and_search():
    with given(_GIVEN) as context:
        token = platform_admin(context)
        approved = _pending(context)
        decide(context, token, approved, "approve")
        pending = request_addon(context, context.access_token, {**HUMANIZE, "name": "other-package"}).json()["id"]
        home = context.organization
        there_is_an_organization(name="Acme")(context)
        acme = context.organization
        context.organization = home

        assert_that(
            [i["id"] for i in _list(context, token, state="PENDING").json()["items"]], contains_exactly(pending)
        )
        assert_that(
            [i["id"] for i in _list(context, token, state="APPROVED").json()["items"]], contains_exactly(approved)
        )
        assert_that(_list(context, token, organization_id=str(acme.id)).json()["items"], empty())
        assert_that([i["id"] for i in _list(context, token, search="other").json()["items"]], contains_exactly(pending))
        assert_that(_list(context, token, search="drafting").json()["total"], equal_to(2))


def test_a_deleted_agents_requests_stay_listed_as_history():
    with given(_GIVEN) as context:
        token = platform_admin(context)
        addon_id = _pending(context)
        context.client.delete(
            f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}",
            headers=auth(context.access_token),
        )

        [item] = _list(context, token).json()["items"]

        assert_that(item, has_entries(id=addon_id, agent_deleted=True, state="WITHDRAWN"))


# --- deciding ----------------------------------------------------------------------------------


def test_approving_records_who_decided_and_audits_it_as_the_administrators_user():
    with given(_GIVEN) as context:
        addon_id = _pending(context)
        token = platform_admin(context, email="reviewer@example.com")

        response = decide(context, token, addon_id, "approve")

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            response.json(),
            has_entries(state="APPROVED", decided_by=has_entries(email="reviewer@example.com"), rejection_reason=None),
        )
        assert_that(response.json()["decided_at"], is_not(none()))
        [event] = events(context, AGENT_ADDON_APPROVED)
        assert_that(event.organization_id, equal_to(context.organization.id))
        assert_that(event.actor, has_entries(type=ActorIdentityType.USER.value))
        assert_that(
            event.payload,
            has_entries(addon_id=addon_id, state="APPROVED", previous_state="PENDING", name="humanize"),
        )


def test_an_administrator_with_a_membership_there_is_audited_as_that_membership():
    with given(_GIVEN) as context:
        addon_id = _pending(context)
        token, membership = member(context, OrganizationRole.MEMBER)
        assert membership.user_id is not None
        user = delegate(context).find_by_id(User, membership.user_id)
        assert user is not None
        user.is_platform_admin = True
        delegate(context).save(user)

        decide(context, token, addon_id, "approve")

        [event] = events(context, AGENT_ADDON_APPROVED)
        assert_that(event.actor, has_entries(type=ActorIdentityType.MEMBERSHIP.value, id=str(membership.id)))


def test_rejecting_needs_a_reason_and_keeps_it():
    with given(_GIVEN) as context:
        addon_id = _pending(context)
        token = platform_admin(context)

        blank = decide(context, token, addon_id, "reject", "   ")
        rejected = decide(context, token, addon_id, "reject", "Use the vendored copy instead.")

        assert_that(blank.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))
        assert_that(rejected.json(), has_entries(state="REJECTED", rejection_reason="Use the vendored copy instead."))
        [event] = events(context, AGENT_ADDON_REJECTED)
        assert_that(event.payload, has_entries(reason="Use the vendored copy instead.", state="REJECTED"))


def test_revoking_withdraws_an_approval():
    with given(_GIVEN) as context:
        addon_id = _pending(context)
        token = platform_admin(context)
        decide(context, token, addon_id, "approve")

        response = decide(context, token, addon_id, "revoke")

        assert_that(response.json(), has_entries(state="REVOKED"))
        [event] = events(context, AGENT_ADDON_REVOKED)
        assert_that(event.payload, has_entries(previous_state="APPROVED", state="REVOKED"))


@pytest.mark.parametrize(
    ("setup", "action"),
    [
        ([], "revoke"),
        (["approve"], "reject"),
        (["reject"], "approve"),
        (["reject"], "revoke"),
        (["approve", "revoke"], "approve"),
        (["withdraw"], "approve"),
        (["withdraw"], "reject"),
    ],
    ids=[
        "revoke-pending",
        "reject-approved",
        "approve-rejected",
        "revoke-rejected",
        "approve-revoked",
        "approve-withdrawn",
        "reject-withdrawn",
    ],
)
def test_a_decision_from_the_wrong_state_is_refused(setup, action):
    with given(_GIVEN) as context:
        addon_id = _pending(context)
        token = platform_admin(context)
        for step in setup:
            if step == "withdraw":
                context.client.post(
                    f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/addons/{addon_id}/withdraw",
                    headers=auth(context.access_token),
                )
            else:
                decide(context, token, addon_id, step, "No.")
        before = stored_addon(context, addon_id).state

        response = decide(context, token, addon_id, action, "No.")

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(stored_addon(context, addon_id).state, equal_to(before))


@pytest.mark.parametrize(
    ("setup", "action", "event_name"),
    [
        ([], "approve", AGENT_ADDON_APPROVED),
        ([], "reject", AGENT_ADDON_REJECTED),
        (["approve"], "revoke", AGENT_ADDON_REVOKED),
    ],
    ids=["approve", "reject", "revoke"],
)
def test_repeating_a_decision_changes_nothing_and_records_nothing(setup, action, event_name):
    with given(_GIVEN) as context:
        addon_id = _pending(context)
        token = platform_admin(context)
        for step in setup:
            decide(context, token, addon_id, step)
        decide(context, token, addon_id, action, "First reason.")

        again = decide(context, token, addon_id, action, "Second reason.")

        assert_that(again.status_code, equal_to(status.HTTP_200_OK))
        assert_that(events(context, event_name), has_length(1))
        if action == "reject":
            assert_that(again.json()["rejection_reason"], equal_to("First reason."))


def test_a_decision_never_restarts_the_agent():
    with given(_GIVEN) as context:
        addon_id = _pending(context)
        token = platform_admin(context)
        k8s = context.injector.get(KubernetesClient)
        k8s.reset_mock()

        decide(context, token, addon_id, "approve")
        decide(context, token, addon_id, "revoke")

        assert_that(k8s.create_deployment.called, equal_to(False))
        assert_that(k8s.delete_deployment.called, equal_to(False))
        stored = delegate(context).find_by_id(Agent, context.agent.id)
        assert stored is not None
        assert_that(AgentStatus(stored.status), equal_to(AgentStatus.STOPPED))


# --- emails ------------------------------------------------------------------------------------


def _capture_emails(monkeypatch) -> list[Email]:
    sent: list[Email] = []

    def fake_send(self, email: Email) -> Email:
        sent.append(email)
        return email

    monkeypatch.setattr(EmailClient, "send", fake_send)
    return sent


def _deliver(context, event_name: str) -> EventDeliveryContext:
    """Run the add-on email handler for the latest such Event, as the worker would."""
    message = events(context, event_name)[-1]
    delivery = next(
        delivery
        for delivery in delegate(context).find_all(EventDelivery)
        if delivery.event_id == message.event_id and delivery.handler_name == AGENT_ADDON_EMAIL_HANDLER
    )
    event = envelope(message)
    delivery_context = EventDeliveryContext(
        delivery_id=delivery.id,
        event_id=event.event_id,
        handler_name=AGENT_ADDON_EMAIL_HANDLER,
        attempt_count=1,
        correlation_id=event.correlation_id,
        organization_id=event.organization_id,
    )
    context.injector.get(AgentAddonEmailHandler).handle(event, delivery_context)
    return delivery_context


def test_every_platform_administrator_is_emailed_of_a_new_request_once(monkeypatch):
    sent = _capture_emails(monkeypatch)
    with given(_GIVEN) as context:
        platform_admin(context, email="first-admin@example.com")
        platform_admin(context, email="second-admin@example.com")
        _pending(context)

        with when("the notification is delivered, then retried"):
            _deliver(context, AGENT_ADDON_REQUESTED)
            _deliver(context, AGENT_ADDON_REQUESTED)

        with then("each administrator got it once, with the request and why"):
            assert_that(
                sorted(email.to_email for email in sent),
                contains_exactly("first-admin@example.com", "second-admin@example.com"),
            )
            assert_that(sent[0].subject, equal_to("Add-on waiting for review: humanize"))
            assert_that(sent[0].html_part, contains_string("humanize==1.2.0"))
            assert_that(sent[0].html_part, contains_string("Formats numbers and dates in reports."))
            assert_that(sent[0].html_part, contains_string("https://app.test.com/dashboard/platform/agent-addons"))


@pytest.mark.parametrize(
    ("decisions", "event_name", "subject"),
    [
        (["approve"], AGENT_ADDON_APPROVED, "Add-on approved: humanize"),
        (["reject"], AGENT_ADDON_REJECTED, "Add-on not approved: humanize"),
        (["approve", "revoke"], AGENT_ADDON_REVOKED, "Add-on approval withdrawn: humanize"),
    ],
    ids=["approved", "rejected", "revoked"],
)
def test_the_requester_is_emailed_of_each_decision(monkeypatch, decisions, event_name, subject):
    sent = _capture_emails(monkeypatch)
    with given(_GIVEN) as context:
        addon_id = _pending(context)
        token = platform_admin(context)
        for decision in decisions:
            decide(context, token, addon_id, decision, "Use the vendored copy instead.")

        _deliver(context, event_name)

        assert_that([email.to_email for email in sent], contains_exactly("addons-requester@example.com"))
        assert_that(sent[0].subject, equal_to(subject))
        if event_name == AGENT_ADDON_REJECTED:
            assert_that(sent[0].html_part, contains_string("Use the vendored copy instead."))
