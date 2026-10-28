"""Integration tests for an Organization's side of Agent Add-ons.

The contract under test:

- only Organization Owners and Admins list, request and withdraw an Agent's add-ons
  (`agent.addon.manage`); an Agent's own Owner, Editor or Viewer cannot (403), and an Agent the
  caller cannot see is concealed (404), as is one in another Organization or deleted;
- each kind's pin is validated (422), a kind the runtime does not offer is refused (400), and an
  Agent has at most 20 Pending and Approved add-ons (409);
- a request is Pending until a Platform Administrator decides; the Organization may withdraw it
  only while it is Pending, and withdrawing again is a no-op;
- every state change leaves one Organization-scoped audit Event carrying the request, and a
  no-op none;
- an approved add-on is installed at the Agent's next start: until then a running Agent reads
  `pending_addons`, and its pod gets the install container, plan and volume;
- a failed install puts the Agent in ERROR naming the add-on, and keeps the install log;
- deleting the Agent withdraws its Pending requests, keeps the rest as history, and deletes its
  add-ons volume.
"""

import json
from datetime import UTC, datetime
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
    has_item,
    has_items,
    has_length,
    is_not,
    none,
)

from api.domains.agent_addons.models import KINDS_BY_RUNTIME, AgentAddonKind, AgentAddonState
from api.domains.agents.models import Agent, AgentStatus, AgentType
from api.domains.events import ActorIdentityType
from api.domains.events.catalog import (
    AGENT_ADDON_APPROVED,
    AGENT_ADDON_REQUESTED,
    AGENT_ADDON_REVOKED,
    AGENT_ADDON_WITHDRAWN,
    AGENT_DELETED,
    SECURITY_AUDIT_HANDLER,
)
from api.domains.events.models import EventDelivery, EventScope
from api.domains.rbac.catalog import AGENT_EDITOR_ROLE_ID, AGENT_OWNER_ROLE_ID, AGENT_VIEWER_ROLE_ID
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.kubernetes.client import KubernetesClient
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector
from api.tests.steps.agent import MockK8sModule, MockLiteLLMModule, there_is_an_agent, use_org_for_auth
from api.tests.steps.agent_addons import (
    ADDON_ENV,
    AGENTS,
    HUMANIZE,
    admin,
    an_approved_addon,
    auth,
    delegate,
    events,
    list_addons,
    member,
    owner,
    pending_member,
    platform_admin,
    read_only_key,
    request_addon,
    stored_addon,
    unassigned_member,
    with_agent_role,
    withdraw_addon,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.template import there_is_a_template

_GIVEN = [
    ADDON_ENV,
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(email="addons-owner@example.com"),
    use_org_for_auth(),
    there_is_a_template(),
    there_is_an_agent(),
]

_PERSONAS = pytest.mark.parametrize(
    ("persona", "allowed"),
    [
        (owner, status.HTTP_200_OK),
        (admin, status.HTTP_200_OK),
        (with_agent_role(AGENT_OWNER_ROLE_ID), status.HTTP_403_FORBIDDEN),
        (with_agent_role(AGENT_EDITOR_ROLE_ID), status.HTTP_403_FORBIDDEN),
        (with_agent_role(AGENT_VIEWER_ROLE_ID), status.HTTP_403_FORBIDDEN),
        (unassigned_member, status.HTTP_404_NOT_FOUND),
        (pending_member, status.HTTP_404_NOT_FOUND),
        (platform_admin, status.HTTP_403_FORBIDDEN),
    ],
    ids=["owner", "admin", "agent-owner", "agent-editor", "agent-viewer", "unassigned", "pending", "platform-admin"],
)


def _k8s(context):
    return context.injector.get(KubernetesClient)


def _agent_url(context) -> str:
    return f"{AGENTS}/{context.agent.id}"


def _read_agent(context, token: str | None = None) -> dict:
    return context.client.get(_agent_url(context), headers=auth(token or context.access_token)).json()


def _start(context):
    response = context.client.post(f"{_agent_url(context)}/start", headers=auth(context.access_token))
    assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
    return response


def _stop(context):
    response = context.client.post(f"{_agent_url(context)}/stop", headers=auth(context.access_token))
    assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)


def _stored_agent(context) -> Agent:
    agent = delegate(context).find_by_id(Agent, context.agent.id)
    assert agent is not None
    return agent


# --- who may use it ---------------------------------------------------------------------------


@_PERSONAS
def test_only_owners_and_admins_list_an_agents_add_ons(persona, allowed):
    with given(_GIVEN) as context:
        token = persona(context)

        response = list_addons(context, token)

        assert_that(response.status_code, equal_to(allowed))


@_PERSONAS
def test_only_owners_and_admins_request_an_add_on(persona, allowed):
    with given(_GIVEN) as context:
        token = persona(context)

        response = request_addon(context, token)

        expected = status.HTTP_201_CREATED if allowed == status.HTTP_200_OK else allowed
        assert_that(response.status_code, equal_to(expected))
        stored = list_addons(context, context.access_token).json()["items"]
        assert_that(stored, has_length(1 if expected == status.HTTP_201_CREATED else 0))


def test_a_read_only_api_key_lists_but_cannot_request():
    with given(_GIVEN) as context:
        key = read_only_key(context, context.access_token)

        assert_that(list_addons(context, key).status_code, equal_to(status.HTTP_200_OK))
        assert_that(request_addon(context, key).status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_an_agent_in_another_organization_or_deleted_is_not_found():
    with given(_GIVEN) as context:
        with when("an Owner of another Organization names this Agent under their own"):
            outsider_org = uuid7()
            outsider, _ = member(context, OrganizationRole.OWNER, organization_id=outsider_org)
            response = context.client.post(
                f"/api/v1/organizations/{outsider_org}/agents/{context.agent.id}/addons",
                json=HUMANIZE,
                headers=auth(outsider),
            )

        with then("it is not found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

        with when("the Agent is soft-deleted"):
            agent = _stored_agent(context)
            agent.deleted_at = datetime.now(UTC)
            delegate(context).save(agent)

        with then("its own Owner can neither list nor request"):
            assert_that(list_addons(context, context.access_token).status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(request_addon(context, context.access_token).status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_the_add_on_action_is_offered_to_owners_and_admins_only():
    with given(_GIVEN) as context:
        editor = with_agent_role(AGENT_EDITOR_ROLE_ID)(context)
        key = read_only_key(context, context.access_token)

        assert_that(_read_agent(context)["allowed_actions"], has_item("agent.addon.manage"))
        assert_that(_read_agent(context, admin(context))["allowed_actions"], has_item("agent.addon.manage"))
        assert_that(_read_agent(context, editor)["allowed_actions"], is_not(has_item("agent.addon.manage")))
        assert_that(_read_agent(context, key)["allowed_actions"], is_not(has_item("agent.addon.manage")))


# --- what may be requested ---------------------------------------------------------------------


def test_a_request_is_pending_with_its_pin_and_why_and_who_asked():
    with given(_GIVEN) as context:
        response = request_addon(context, context.access_token)

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        assert_that(
            response.json(),
            has_entries(
                kind="pip",
                name="humanize",
                spec=has_entries(version="1.2.0", url=None, command=None),
                reason=HUMANIZE["reason"],
                state="PENDING",
                rejection_reason=None,
                decided_at=None,
                requested_by=has_entries(email=context.user.email),
            ),
        )


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "npm", "name": "left-pad", "version": "1.3.0"},
        {"kind": "npm", "name": "@scope/tool", "version": "2.0.0-beta.1"},
        {
            "kind": "git",
            "name": "toolkit",
            "url": "https://github.com/example/toolkit.git",
            "commit": "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d",
        },
        {"kind": "binary", "name": "drawtool", "url": "https://example.com/drawtool", "sha256": "A" * 64},
        {"kind": "command", "name": "fonts", "command": "curl -fsSL https://example.com/x.sh | bash"},
        {"kind": "pip", "name": "humanize", "version": "==1.2.0"},
    ],
    ids=["npm", "npm-scoped", "git", "binary", "command", "pip-with-operator"],
)
def test_each_kind_is_accepted_with_an_exact_pin(body):
    with given(_GIVEN) as context:
        response = request_addon(context, context.access_token, {**body, "reason": "Needed for reports."})

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED), response.text)


def test_a_sha_is_stored_in_lowercase_and_a_pip_operator_is_dropped():
    with given(_GIVEN) as context:
        binary = request_addon(
            context,
            context.access_token,
            {"kind": "binary", "name": "x", "url": "https://example.com/x", "sha256": "AB" * 32, "reason": "r"},
        ).json()
        pip = request_addon(context, context.access_token, {**HUMANIZE, "version": "==1.2.0"}).json()

        assert_that(binary["spec"]["sha256"], equal_to("ab" * 32))
        assert_that(pip["spec"]["version"], equal_to("1.2.0"))


@pytest.mark.parametrize(
    "body",
    [
        {**HUMANIZE, "version": ">=1.2"},
        {**HUMANIZE, "version": "1.*"},
        {**HUMANIZE, "version": ""},
        {**HUMANIZE, "name": "humanize[extra]"},
        {**HUMANIZE, "name": "humanize==1.2.0"},
        {"kind": "npm", "name": "left-pad", "version": "latest", "reason": "r"},
        {"kind": "npm", "name": "left-pad", "version": "^1.3.0", "reason": "r"},
        {"kind": "npm", "name": "Left Pad", "version": "1.3.0", "reason": "r"},
        {"kind": "git", "name": "repo", "url": "https://github.com/x/y", "commit": "7fd1a60", "reason": "r"},
        {"kind": "git", "name": "repo", "url": "http://github.com/x/y", "commit": "a" * 40, "reason": "r"},
        {"kind": "git", "name": "repo", "url": "https://user:pw@github.com/x/y", "commit": "a" * 40, "reason": "r"},
        {"kind": "git", "name": "../escape", "url": "https://github.com/x/y", "commit": "a" * 40, "reason": "r"},
        {"kind": "binary", "name": "tool", "url": "https://example.com/t", "sha256": "abc", "reason": "r"},
        {"kind": "binary", "name": ".hidden", "url": "https://example.com/t", "sha256": "a" * 64, "reason": "r"},
        {"kind": "command", "name": "c", "command": "   ", "reason": "r"},
        {"kind": "command", "name": "c", "command": "x" * 4001, "reason": "r"},
        {**HUMANIZE, "reason": "  "},
        {key: value for key, value in HUMANIZE.items() if key != "reason"},
        {**HUMANIZE, "kind": "apt"},
        {**HUMANIZE, "extra": "field"},
    ],
    ids=[
        "pip-range",
        "pip-wildcard",
        "pip-empty",
        "pip-extras",
        "pip-pinned-name",
        "npm-tag",
        "npm-caret",
        "npm-bad-name",
        "git-short-sha",
        "git-http",
        "git-credentials",
        "git-path-name",
        "binary-short-sha",
        "binary-dot-name",
        "command-blank",
        "command-too-long",
        "blank-why",
        "no-why",
        "unknown-kind",
        "unknown-field",
    ],
)
def test_an_unpinned_or_malformed_request_is_refused(body):
    with given(_GIVEN) as context:
        response = request_addon(context, context.access_token, body)

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))
        assert_that(list_addons(context, context.access_token).json()["items"], empty())


def test_a_kind_the_runtime_does_not_offer_is_refused(monkeypatch):
    # Both pinned images carry every tool today, so drop one to prove the rule holds.
    monkeypatch.setitem(
        KINDS_BY_RUNTIME, AgentType.HERMES, tuple(kind for kind in AgentAddonKind if kind != AgentAddonKind.NPM)
    )
    with given([*_GIVEN, there_is_an_agent(name="Hermes Agent", agent_type=AgentType.HERMES)]) as context:
        listed = list_addons(context, context.access_token).json()

        response = request_addon(
            context, context.access_token, {"kind": "npm", "name": "left-pad", "version": "1.3.0", "reason": "r"}
        )

        assert_that(listed["available_kinds"], is_not(has_item("npm")))
        assert_that(listed["available_kinds"], has_items("pip", "git", "binary", "command"))
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_an_agent_has_at_most_twenty_pending_and_approved_add_ons():
    with given(_GIVEN) as context:
        admin_token = platform_admin(context)
        ids = [
            request_addon(context, context.access_token, {**HUMANIZE, "name": f"package-{index}"}).json()["id"]
            for index in range(20)
        ]
        context.client.post(f"/api/v1/platform/agent-addons/{ids[0]}/approve", headers=auth(admin_token))

        with when("a twenty-first is requested"):
            refused = request_addon(context, context.access_token, {**HUMANIZE, "name": "package-20"})

        with then("it is refused"):
            assert_that(refused.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(refused.json()["detail"], contains_string("at most 20"))

        with when("a pending one is withdrawn"):
            withdraw_addon(context, context.access_token, ids[1])

        with then("there is room again"):
            assert_that(
                request_addon(context, context.access_token, {**HUMANIZE, "name": "package-20"}).status_code,
                equal_to(status.HTTP_201_CREATED),
            )


def test_the_same_package_cannot_be_pending_or_approved_twice_but_may_be_asked_again_once_refused():
    with given(_GIVEN) as context:
        admin_token = platform_admin(context)
        first = request_addon(context, context.access_token).json()["id"]

        duplicate = request_addon(context, context.access_token, {**HUMANIZE, "name": "Humanize"})
        context.client.post(
            f"/api/v1/platform/agent-addons/{first}/reject", json={"reason": "Pin 1.3.0"}, headers=auth(admin_token)
        )
        again = request_addon(context, context.access_token, {**HUMANIZE, "version": "1.3.0"})

        assert_that(duplicate.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(again.status_code, equal_to(status.HTTP_201_CREATED))


# --- withdrawing -------------------------------------------------------------------------------


def test_a_pending_request_is_withdrawn_once_and_audited_once():
    with given(_GIVEN) as context:
        addon_id = request_addon(context, context.access_token).json()["id"]

        with when("it is withdrawn twice"):
            first = withdraw_addon(context, context.access_token, addon_id)
            second = withdraw_addon(context, context.access_token, addon_id)

        with then("it is Withdrawn, and only the first left an Event"):
            assert_that(first.status_code, equal_to(status.HTTP_200_OK))
            assert_that(second.status_code, equal_to(status.HTTP_200_OK))
            assert_that(first.json()["state"], equal_to("WITHDRAWN"))
            assert_that(events(context, AGENT_ADDON_WITHDRAWN), has_length(1))


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_a_decided_request_cannot_be_withdrawn(decision):
    with given(_GIVEN) as context:
        admin_token = platform_admin(context)
        addon_id = request_addon(context, context.access_token).json()["id"]
        context.client.post(
            f"/api/v1/platform/agent-addons/{addon_id}/{decision}",
            json={"reason": "No."} if decision == "reject" else None,
            headers=auth(admin_token),
        )

        response = withdraw_addon(context, context.access_token, addon_id)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(events(context, AGENT_ADDON_WITHDRAWN), empty())


def test_another_agents_add_on_cannot_be_withdrawn_through_this_one():
    with given(_GIVEN) as context:
        addon_id = request_addon(context, context.access_token).json()["id"]
        first_agent = context.agent
        there_is_an_agent(name="Other Agent")(context)

        response = withdraw_addon(context, context.access_token, addon_id)

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
        assert_that(stored_addon(context, addon_id).state, equal_to(AgentAddonState.PENDING))
        context.agent = first_agent


# --- the audit trail ---------------------------------------------------------------------------


def test_a_request_is_audited_with_its_content_and_requester():
    with given(_GIVEN) as context:
        addon_id = request_addon(context, context.access_token).json()["id"]

        [event] = events(context, AGENT_ADDON_REQUESTED)

        assert_that(event.event_scope, equal_to(EventScope.ORGANIZATION))
        assert_that(event.organization_id, equal_to(context.organization.id))
        assert_that(event.actor, has_entries(type=ActorIdentityType.MEMBERSHIP.value))
        assert_that(event.subject, has_entries(type="AGENT", id=str(context.agent.id)))
        assert_that(
            event.payload,
            has_entries(
                addon_id=addon_id,
                agent_id=str(context.agent.id),
                kind="pip",
                name="humanize",
                version="1.2.0",
                request_reason=HUMANIZE["reason"],
                state="PENDING",
                previous_state=None,
                reason=None,
                subject_display=context.agent.name,
            ),
        )
        handlers = [
            delivery.handler_name
            for delivery in delegate(context).find_all(EventDelivery)
            if delivery.event_id == event.event_id
        ]
        assert_that(handlers, has_item(SECURITY_AUDIT_HANDLER))


def test_a_refused_request_leaves_no_event():
    with given(_GIVEN) as context:
        request_addon(context, context.access_token, {**HUMANIZE, "version": ">=1"})

        assert_that(events(context, AGENT_ADDON_REQUESTED), empty())


# --- reaching the pod --------------------------------------------------------------------------


def test_an_agent_without_add_ons_starts_as_it_always_did():
    with given(_GIVEN) as context:
        _start(context)

        deployment = _k8s(context).create_deployment.call_args.args[1]
        assert_that([c.name for c in deployment.spec.template.spec.init_containers], contains_exactly("fix-pvc-owner"))
        assert_that(_stored_agent(context).running_addons_hash, none())
        assert_that(_read_agent(context)["pending_addons"], equal_to(False))


def test_an_approval_applies_at_the_next_start_and_reads_as_pending_until_then():
    with given(_GIVEN) as context:
        admin_token = platform_admin(context)
        _start(context)

        with when("an add-on is approved while the Agent runs"):
            addon_id = an_approved_addon(context, admin_token)

        with then("the running Agent reads as pending and was not restarted"):
            assert_that(_read_agent(context)["pending_addons"], equal_to(True))
            assert_that(_k8s(context).create_deployment.call_count, equal_to(1))

        with when("it restarts"):
            _stop(context)
            _start(context)

        with then("its pod installs the add-on and nothing is pending"):
            deployment = _k8s(context).create_deployment.call_args.args[1]
            init = [c.name for c in deployment.spec.template.spec.init_containers]
            assert_that(init, contains_exactly("fix-pvc-owner", "install-addons"))
            plans = [
                call.args[1]
                for call in _k8s(context).create_config_map.call_args_list
                if call.args[1].metadata.name.endswith("-addons")
            ]
            assert_that(plans, has_length(1))
            plan = json.loads(plans[0].data["addons.json"])
            assert_that(plan["addons"], contains_exactly(has_entries(id=addon_id, name="humanize")))
            volumes = [
                call.args[1].metadata.name
                for call in _k8s(context).create_pvc.call_args_list
                if call.args[1].metadata.name.endswith("-addons")
            ]
            assert_that(volumes, contains_exactly(f"agent-{context.agent.id}-addons"))
            assert_that(_read_agent(context)["pending_addons"], equal_to(False))

        with then("the Agent is told it has the add-on"):
            config_map = [
                call.args[1]
                for call in _k8s(context).create_config_map.call_args_list
                if call.args[1].metadata.name == f"agent-{context.agent.id}"
            ][-1]
            assert_that(config_map.data["AGENTS.md"], contains_string("**humanize**"))
            assert_that(config_map.data["AGENTS.md"], contains_string(HUMANIZE["reason"]))


def test_a_revocation_reads_as_pending_until_the_agent_restarts_without_it():
    with given(_GIVEN) as context:
        admin_token = platform_admin(context)
        addon_id = an_approved_addon(context, admin_token)
        _start(context)

        context.client.post(f"/api/v1/platform/agent-addons/{addon_id}/revoke", headers=auth(admin_token))

        assert_that(events(context, AGENT_ADDON_REVOKED), has_length(1))
        assert_that(_read_agent(context)["pending_addons"], equal_to(True))
        _stop(context)
        _start(context)
        deployment = _k8s(context).create_deployment.call_args.args[1]
        assert_that([c.name for c in deployment.spec.template.spec.init_containers], contains_exactly("fix-pvc-owner"))
        assert_that(_read_agent(context)["pending_addons"], equal_to(False))


def test_a_pending_request_does_not_reach_the_pod():
    with given(_GIVEN) as context:
        request_addon(context, context.access_token)
        _start(context)

        deployment = _k8s(context).create_deployment.call_args.args[1]
        assert_that([c.name for c in deployment.spec.template.spec.init_containers], contains_exactly("fix-pvc-owner"))
        assert_that(_read_agent(context)["pending_addons"], equal_to(False))


# --- a failed install ------------------------------------------------------------------------


def test_a_failed_install_puts_the_agent_in_error_naming_the_add_on_and_keeps_its_log():
    with given(_GIVEN) as context:
        admin_token = platform_admin(context)
        addon_id = an_approved_addon(context, admin_token)
        _start(context)
        k8s = _k8s(context)

        with when("the install container reports the add-on failed"):
            k8s.get_init_container_failure.return_value = json.dumps({"addon_id": addon_id, "reason": "failed"})
            k8s.read_init_container_logs.return_value = (
                "[install-addons] $ uv pip install humanize==1.2.0\n"
                "No solution found when resolving dependencies\n"
                "[install-addons] FAILED: humanize: uv exited with 1\n"
            )
            agent = _read_agent(context)

        with then("the Agent is in ERROR with the add-on named"):
            assert_that(agent["status"], equal_to("ERROR"))
            assert_that(
                agent["last_error"],
                has_entries(
                    code="ADDON_INSTALL_FAILED",
                    category="addon_install_failed",
                    detail="humanize: install failed",
                ),
            )
            k8s.delete_deployment.assert_called_with(f"agent-{context.agent.id}", "agent-farm")

        with then("the last lines of the install log are the Agent's logs"):
            logs = context.client.get(f"{_agent_url(context)}/logs", headers=auth(context.access_token)).json()
            assert_that(logs["source"], equal_to("snapshot"))
            assert_that(logs["lines"][0], contains_string("Add-on humanize failed to install"))
            assert_that(logs["lines"], has_item(contains_string("No solution found")))


def test_an_install_failure_naming_no_approved_add_on_still_fails_the_start_without_a_name():
    with given(_GIVEN) as context:
        admin_token = platform_admin(context)
        an_approved_addon(context, admin_token)
        _start(context)
        _k8s(context).get_init_container_failure.return_value = json.dumps(
            {"addon_id": str(uuid7()), "reason": "<script>"}
        )

        agent = context.client.get(f"{_agent_url(context)}/healthz", headers=auth(context.access_token))

        stored = _stored_agent(context)
        assert_that(stored.status, equal_to(AgentStatus.ERROR))
        assert_that(stored.last_error_code, equal_to("ADDON_INSTALL_FAILED"))
        assert_that(stored.last_error_detail, none())
        assert_that(agent.json(), has_entries(status="error"))


def test_a_running_agent_without_add_ons_is_never_asked_about_an_install():
    with given(_GIVEN) as context:
        _start(context)

        _read_agent(context)

        _k8s(context).get_init_container_failure.assert_not_called()


# --- deleting the Agent -----------------------------------------------------------------------


def test_deleting_the_agent_withdraws_pending_requests_keeps_the_rest_and_its_volume_goes():
    with given(_GIVEN) as context:
        admin_token = platform_admin(context)
        approved = an_approved_addon(context, admin_token)
        pending = request_addon(context, context.access_token, {**HUMANIZE, "name": "other-package"}).json()["id"]

        response = context.client.delete(_agent_url(context), headers=auth(context.access_token))

        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        assert_that(stored_addon(context, pending).state, equal_to(AgentAddonState.WITHDRAWN))
        assert_that(stored_addon(context, approved).state, equal_to(AgentAddonState.APPROVED))
        [withdrawn] = events(context, AGENT_ADDON_WITHDRAWN)
        [deleted] = events(context, AGENT_DELETED)
        assert_that(withdrawn.correlation_id, equal_to(deleted.correlation_id))
        assert_that(withdrawn.payload, has_entries(addon_id=pending, previous_state="PENDING"))
        deleted_volumes = [call.args[0] for call in _k8s(context).delete_pvc.call_args_list]
        assert_that(deleted_volumes, has_item(f"agent-{context.agent.id}-addons"))


def test_deleting_an_agent_that_never_had_an_add_on_touches_no_add_on_resources():
    with given(_GIVEN) as context:
        request_addon(context, context.access_token)

        context.client.delete(_agent_url(context), headers=auth(context.access_token))

        deleted_volumes = [call.args[0] for call in _k8s(context).delete_pvc.call_args_list]
        assert_that(deleted_volumes, contains_exactly(f"agent-{context.agent.id}"))
        assert_that(events(context, AGENT_ADDON_APPROVED), empty())
