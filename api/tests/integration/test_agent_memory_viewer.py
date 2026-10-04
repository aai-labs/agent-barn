"""Read-only viewing of the memories an Agent wrote.

The product API authorizes the person (`activity.read`) and sends the memory gateway a
short-lived capability for one Agent. The gateway, not the caller, derives the bank and
tag filter. These tests cross both HTTP boundaries and record what reaches Hindsight.
"""

import time
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid7

import jwt
import pytest
from fastapi import status
from hamcrest import assert_that, contains_exactly, empty, equal_to, has_entries, has_length, is_not

from api.core.config import get_config
from api.domains.agent_memory.view_capability import (
    AUDIENCE,
    issue_view_capability,
    verify_view_capability,
)
from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.auth.service import JWT_ENCODING_ALGORITHM
from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID, PERMISSION_ID_BY_KEY, PermissionKey
from api.domains.rbac.models import AgentAccessRole, AgentAccessRolePermission
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.helpers.memory_backend import memory_gateway_is_ready, memory_viewer_is_served
from api.tests.steps.agent import there_is_agent_access, there_is_an_agent, there_is_an_agent_in_another_org
from api.tests.steps.agent_memory import agent_memory_api_setup, memory_is_enabled, signed_in_as, two_agents

_ITEMS = "/api/v1/organizations/{organization_id}/agents/{agent_id}/memory/items"
_VIEWER = "/memory/view/v1/memories"
_UNSET = object()


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _list(context, agent_id=None, **params):
    return context.client.get(
        _ITEMS.replace("{agent_id}", str(agent_id or context.agent.id)), params=params, headers=_auth(context)
    )


def _row(agent_id, text, *, fact_type="world", tags=(), **extra):
    return {
        "id": str(uuid7()),
        "text": text,
        "context": "conversation context that must not be exposed",
        "fact_type": fact_type,
        "mentioned_at": "2026-10-01T12:30:00+00:00",
        "entities": "Alice, Billing",
        "chunk_id": "chunk-1",
        "document_id": "doc-1",
        "metadata": {"secret": "metadata"},
        "source_memory_ids": [str(uuid7())],
        "tags": [f"agent:{agent_id}", *tags],
        **extra,
    }


def _backend_page(context, rows, total=None):
    context.backend_response = {"items": rows, "total": len(rows) if total is None else total, "limit": 25, "offset": 0}


def _upstream(context) -> dict:
    assert_that(context.backend_requests, has_length(1))
    request = context.backend_requests[0]
    parts = urlsplit(request["path"])
    return {**request, "path": parts.path, "query": parse_qsl(parts.query)}


def _setup(*steps):
    return agent_memory_api_setup(*steps, memory_gateway_is_ready(), memory_viewer_is_served())


def test_the_agents_own_saved_memories_are_listed_with_only_allowlisted_fields():
    with given(_setup(there_is_an_agent())) as context:
        _backend_page(
            context,
            [
                _row(context.agent.id, "Prefers metric units"),
                _row(context.agent.id, "Quarterly report is due", fact_type="observation", tags=["scope:team"]),
            ],
            total=2,
        )
        with when("an Organization Owner views the Agent's memories"):
            response = _list(context)

        with then("each memory shows only text, type, mention time, and its sharing"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body, has_entries(page=1, page_size=25, total=2))
            assert_that(
                [sorted(item) for item in body["items"]],
                contains_exactly(*[["id", "mentioned_at", "shared", "text", "type"]] * 2),
            )
            assert_that(
                [(item["text"], item["type"], item["shared"]) for item in body["items"]],
                contains_exactly(
                    ("Prefers metric units", "world", False), ("Quarterly report is due", "observation", True)
                ),
            )
            assert_that(body["items"][0]["mentioned_at"], equal_to("2026-10-01T12:30:00Z"))
            serialized = response.text
            for leaked in ("context that must not", "Alice", "chunk-1", "doc-1", "metadata", "source_memory_ids"):
                assert_that(leaked in serialized, equal_to(False), leaked)


def test_listing_is_forced_to_the_agents_own_tag_in_its_organizations_bank():
    with given(_setup(two_agents())) as context:
        _backend_page(context, [])
        with when("one Agent's memories are listed"):
            response = _list(context, context.billing.id)

        with then("Hindsight receives the server-derived bank and strict tag filter only"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            upstream = _upstream(context)
            assert_that(upstream["method"], equal_to("GET"))
            assert_that(upstream["path"], equal_to(f"/v1/default/banks/org-{context.organization.id}/memories/list"))
            assert_that(upstream["authorization"], equal_to("Bearer gateway-upstream-test-key"))
            assert_that(
                upstream["query"],
                contains_exactly(
                    ("tags", f"agent:{context.billing.id}"),
                    ("tags_match", "any_strict"),
                    ("limit", "25"),
                    ("offset", "0"),
                ),
            )


def _mismatched_rows(context):
    return {
        "foreign-tag": [_row(context.triage.id, "Triage wrote this")],
        "untagged": [{**_row(context.billing.id, "Untagged"), "tags": []}],
        "unknown-type": [_row(context.billing.id, "Odd", fact_type="mental_model")],
        "missing-text": [{k: v for k, v in _row(context.billing.id, "x").items() if k != "text"}],
    }


@pytest.mark.parametrize("case", ["foreign-tag", "untagged", "unknown-type", "missing-text"])
def test_a_row_outside_the_requested_view_fails_the_whole_page_closed(case):
    with given(_setup(two_agents())) as context:
        rows = [_row(context.billing.id, "Billing wrote this"), *_mismatched_rows(context)[case]]
        _backend_page(context, rows, total=40)
        with when("Hindsight returns a row Billing did not write or that breaks the contract"):
            response = _list(context, context.billing.id)

        with then("neither the rows nor the aggregate count are relayed"):
            assert_that(response.status_code, equal_to(status.HTTP_502_BAD_GATEWAY))
            assert_that("Billing wrote this" in response.text, equal_to(False))
            assert_that("40" in response.text, equal_to(False))


@pytest.mark.parametrize("case", ["more-than-limit", "total-below-items"])
def test_an_inconsistent_page_is_a_generic_error(case):
    with given(_setup(there_is_an_agent())) as context:
        rows = [_row(context.agent.id, f"Fact {i}") for i in range(3)]
        _backend_page(context, rows, total=1 if case == "total-below-items" else 3)
        with when("Hindsight returns more rows than asked for or than its total"):
            response = _list(context, page_size=2 if case == "more-than-limit" else 25)

        with then("the page is rejected"):
            assert_that(response.status_code, equal_to(status.HTTP_502_BAD_GATEWAY))


def test_shared_and_private_memories_the_agent_wrote_carry_their_scope_and_missing_dates():
    with given(_setup(there_is_an_agent())) as context:
        undated = {**_row(context.agent.id, "Undated"), "mentioned_at": None, "updated_at": "2026-10-02T00:00:00+00:00"}
        _backend_page(context, [undated])
        with when("an Agent's memory has no mention time"):
            response = _list(context)

        with then("it has no date rather than borrowing the write time"):
            assert_that(response.json()["items"][0]["mentioned_at"], equal_to(None))


def test_pagination_and_search_are_scoped_and_literal():
    with given(_setup(there_is_an_agent())) as context:
        _backend_page(context, [], total=120)
        with when("the third page of a search containing wildcards is requested"):
            response = _list(context, search="  50%_off\\  ", page=3, page_size=10)

        with then("the offset is computed and the wildcards are escaped"):
            assert_that(response.json(), has_entries(page=3, page_size=10, total=120))
            query = dict(_upstream(context)["query"])
            assert_that(query, has_entries(limit="10", offset="20", q="50\\%\\_off\\\\"))


@pytest.mark.parametrize(
    "params",
    [{"page": 0}, {"page": 2001}, {"page_size": 0}, {"page_size": 51}, {"search": "x" * 201}, {"page": "a"}],
)
def test_listing_query_is_validated_before_contacting_the_gateway(params):
    with given(_setup(there_is_an_agent())) as context:
        with when("an invalid query is sent"):
            response = _list(context, **params)

        with then("it is rejected without reaching Hindsight"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))
            assert_that(context.backend_requests, empty())


@pytest.mark.parametrize("state", ["stopped", "memory-disabled", "running-enabled"])
def test_stored_memories_are_viewable_whatever_the_agents_runtime_state(state):
    with given(
        _setup(there_is_an_agent(status=AgentStatus.RUNNING if state == "running-enabled" else AgentStatus.STOPPED))
    ) as context:
        if state == "running-enabled":
            memory_is_enabled()(context)
        _backend_page(context, [_row(context.agent.id, "Still stored")])
        with when("the Agent's memories are viewed"):
            response = _list(context)

        with then("viewing needs neither a running Agent nor enabled memory"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["items"][0]["text"], equal_to("Still stored"))


def test_a_bank_that_was_never_created_has_no_memories():
    with given(_setup(there_is_an_agent())) as context:
        context.backend_status = 404
        with when("the Organization has not saved anything yet"):
            response = _list(context)

        with then("the page is empty rather than an error"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json(), has_entries(total=0, items=empty()))


@pytest.mark.parametrize("backend_status, expected", [(500, 502), (429, 502)])
def test_backend_errors_are_generic(backend_status, expected):
    with given(_setup(there_is_an_agent())) as context:
        context.backend_status = backend_status
        context.backend_response = {"detail": "internal backend trace secret"}
        with when("Hindsight fails"):
            response = _list(context)

        with then("the person sees a generic error without backend content or headers"):
            assert_that(response.status_code, equal_to(expected))
            assert_that("secret" in response.text.lower(), equal_to(False))
            assert_that(response.headers.get("X-Backend-Secret"), equal_to(None))


def test_an_unexpected_backend_shape_is_a_generic_error():
    with given(_setup(there_is_an_agent())) as context:
        context.backend_response = {"unexpected": True}
        with when("Hindsight returns a page the contract does not describe"):
            response = _list(context)

        with then("it is rejected rather than relayed"):
            assert_that(response.status_code, equal_to(status.HTTP_502_BAD_GATEWAY))


def test_an_unreachable_gateway_is_service_unavailable():
    with given(_setup(there_is_an_agent())) as context:
        get_config().memory_view_base_url = "http://127.0.0.1:1/memory/view/v1"
        with when("the gateway cannot be reached"):
            response = _list(context)

        with then("viewing reports unavailability"):
            assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))


def test_an_unconfigured_backend_is_service_unavailable():
    with given(_setup(there_is_an_agent())) as context:
        config = get_config()
        previous = config.hindsight_base_url
        config.hindsight_base_url = ""
        try:
            with when("the gateway has no Hindsight backend"):
                response = _list(context)
        finally:
            config.hindsight_base_url = previous

        with then("viewing reports unavailability"):
            assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))


def _there_is_agent_access_with(context, permissions):
    repository = context.injector.get(AgentRepository)
    role = AgentAccessRole(organization_id=context.organization.id, name=f"CUSTOM-{uuid7()}", is_system=False)
    repository.delegate.save(role)
    for permission in permissions:
        repository.delegate.save(
            AgentAccessRolePermission(role_id=role.id, permission_id=PERMISSION_ID_BY_KEY[permission])
        )
    there_is_agent_access(access_role_id=role.id)(context)


def test_an_agent_viewer_can_view_memories():
    with given(
        _setup(
            there_is_an_agent(),
            signed_in_as(OrganizationRole.MEMBER),
            there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID),
        )
    ) as context:
        _backend_page(context, [_row(context.agent.id, "Visible")])
        with when("a Member with the Viewer role views memories"):
            response = _list(context)

        with then("activity.read is enough"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))


@pytest.mark.parametrize(
    "permissions",
    [
        {PermissionKey.AGENT_READ, PermissionKey.AGENT_MEMORY_MANAGE},
        {PermissionKey.AGENT_READ, PermissionKey.COST_READ},
    ],
)
def test_memory_management_alone_does_not_grant_content_access(permissions):
    with given(_setup(there_is_an_agent(), signed_in_as(OrganizationRole.MEMBER))) as context:
        _there_is_agent_access_with(context, permissions)
        with when("a Member who can see the Agent but lacks activity.read views its memories"):
            response = _list(context)

        with then("it is refused without contacting Hindsight"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(context.backend_requests, empty())


def test_a_member_without_agent_access_cannot_see_the_agent():
    with given(_setup(there_is_an_agent(), signed_in_as(OrganizationRole.MEMBER))) as context:
        with when("a Member without Agent Access views memories"):
            response = _list(context)

        with then("the Agent is concealed"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(context.backend_requests, empty())


@pytest.mark.parametrize("target", ["missing", "deleted", "foreign"])
def test_absent_deleted_and_foreign_agents_are_concealed(target):
    with given(_setup(there_is_an_agent(deleted=True))) as context:
        deleted_agent_id = context.agent.id
        there_is_an_agent_in_another_org()(context)
        agent_id = {"missing": uuid7(), "deleted": deleted_agent_id, "foreign": context.other_org_agent.id}[target]
        with when("an Owner views memories of an unavailable Agent"):
            response = _list(context, agent_id)

        with then("it is a 404 and Hindsight is untouched"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(context.backend_requests, empty())


def test_viewing_requires_authentication():
    with given(_setup(there_is_an_agent())) as context:
        response = context.client.get(_ITEMS.replace("{agent_id}", str(context.agent.id)))
        assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


# --- the gateway's viewer boundary ---------------------------------------------------------


def _viewer(context, token, **params):
    return context.memory_client.get(_VIEWER, params=params, headers={"Authorization": f"Bearer {token}"})


def _capability(context, agent_id=None, organization_id=None):
    return issue_view_capability(get_config(), organization_id or context.organization.id, agent_id or context.agent.id)


def test_viewer_accepts_its_capability_and_derives_the_target_from_it():
    with given(_setup(there_is_an_agent())) as context:
        _backend_page(context, [_row(context.agent.id, "Fact")])
        with when("a valid capability lists memories"):
            response = _viewer(context, _capability(context))

        with then("the page is returned"):
            assert_that(response.status_code, equal_to(200))
            assert_that(response.json()["items"][0]["text"], equal_to("Fact"))


@pytest.mark.parametrize(
    "params",
    [{"tags": "agent:other"}, {"bank": "org-other"}, {"tags_match": "any"}, {"limit": 51}, {"offset": -1}, {"q": "x"}],
)
def test_viewer_rejects_forged_or_invalid_parameters(params):
    with given(_setup(there_is_an_agent())) as context:
        with when("a caller adds bank, tag, or out-of-range parameters"):
            response = _viewer(context, _capability(context), **params)

        with then("the request is rejected before contacting Hindsight"):
            assert_that(response.status_code, equal_to(422))
            assert_that(context.backend_requests, empty())


def _token(context, **overrides):
    now = int(time.time())
    claims = {
        "aud": AUDIENCE,
        "op": "list",
        "organization_id": str(context.organization.id),
        "agent_id": str(context.agent.id),
        "iat": now,
        "exp": now + 30,
        **overrides,
    }
    claims = {key: value for key, value in claims.items() if value is not _UNSET}
    return jwt.encode(claims, get_config().secret_signing_key, algorithm=JWT_ENCODING_ALGORITHM)


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "agentbarn-api"},
        {"aud": _UNSET},
        {"op": "delete"},
        {"op": _UNSET},
        {"exp": int(time.time()) - 5},
        {"exp": int(time.time()) + 3600},
        {"agent_id": "not-a-uuid"},
        {"organization_id": _UNSET},
    ],
)
def test_viewer_rejects_capabilities_for_other_purposes_or_expired(overrides):
    with given(_setup(there_is_an_agent())) as context:
        with when("a token that is not a current viewing capability is presented"):
            response = _viewer(context, _token(context, **overrides))

        with then("it grants nothing"):
            assert_that(response.status_code, equal_to(401))
            assert_that(context.backend_requests, empty())


def test_viewer_rejects_a_token_signed_with_another_key():
    with given(_setup(there_is_an_agent())) as context:
        forged = jwt.encode(
            {
                "aud": AUDIENCE,
                "op": "list",
                "organization_id": str(context.organization.id),
                "agent_id": str(context.agent.id),
                "iat": int(time.time()),
                "exp": int(time.time()) + 30,
            },
            "a-different-signing-key-of-sufficient-length",
            algorithm=JWT_ENCODING_ALGORITHM,
        )
        response = _viewer(context, forged)
        assert_that(response.status_code, equal_to(401))


def test_user_access_tokens_and_agent_credentials_are_not_viewing_capabilities():
    with given(_setup(there_is_an_agent(status=AgentStatus.RUNNING), memory_is_enabled())) as context:
        with when("a user access token and an Agent memory key are presented to the viewer"):
            by_user = _viewer(context, context.access_token)
            by_agent = _viewer(context, context.memory_key)

        with then("neither is accepted"):
            assert_that(by_user.status_code, equal_to(401))
            assert_that(by_agent.status_code, equal_to(401))
            assert_that(context.backend_requests, empty())


def test_a_viewing_capability_is_not_a_user_or_agent_credential():
    with given(_setup(there_is_an_agent(status=AgentStatus.RUNNING), memory_is_enabled())) as context:
        capability = _capability(context)
        with when("the capability is replayed against the API and the Agent gateway"):
            api = context.client.get(
                _ITEMS.replace("{agent_id}", str(context.agent.id)), headers={"Authorization": f"Bearer {capability}"}
            )
            agent_gateway = context.memory_client.post(
                "/memory/v1/v1/default/banks/x/memories/recall",
                json={"query": "fact"},
                headers={"Authorization": f"Bearer {capability}"},
            )

        with then("it authenticates as neither"):
            assert_that(api.status_code, equal_to(401))
            assert_that(agent_gateway.status_code, equal_to(401))
            assert_that(context.backend_requests, empty())


@pytest.mark.parametrize(
    "method, path", [("GET", "/memory/v1/v1/default/banks/x/memories/list"), ("GET", "/memory/v1/view/v1/memories")]
)
def test_agent_credentials_cannot_list_through_the_agent_gateway(method, path):
    with given(_setup(there_is_an_agent(status=AgentStatus.RUNNING), memory_is_enabled())) as context:
        with when("an Agent credential asks the Agent gateway to list"):
            response = context.memory_client.request(
                method, path, headers={"Authorization": f"Bearer {context.memory_key}"}
            )

        with then("the allowlist denies it"):
            assert_that(response.status_code, equal_to(403))
            assert_that(context.backend_requests, empty())


def test_viewer_checks_the_target_against_current_state():
    with given(_setup(there_is_an_agent(), two_agents())) as context:
        other = _capability(context, agent_id=uuid7())
        in_other_organization = _capability(context, organization_id=uuid7())
        with when("capabilities name a missing Agent or a different Organization"):
            missing = _viewer(context, other)
            wrong_org = _viewer(context, in_other_organization)
            context.triage.deleted_at = context.triage.updated_at
            context.injector.get(PostgresRepositoryDelegate).save(context.triage)
            deleted = _viewer(context, _capability(context, agent_id=context.triage.id))

        with then("each is a 404 and nothing is listed"):
            assert_that([missing.status_code, wrong_org.status_code, deleted.status_code], equal_to([404, 404, 404]))
            assert_that(context.backend_requests, empty())


def test_a_capability_is_valid_only_briefly():
    config = get_config()
    capability = issue_view_capability(config, uuid7(), uuid7())
    assert_that(verify_view_capability(config, capability), is_not(equal_to(None)))
    assert_that(verify_view_capability(config, capability + "x"), equal_to(None))


def test_viewing_logs_do_not_contain_memory_search_or_capability(caplog):
    with given(_setup(there_is_an_agent())) as context:
        _backend_page(context, [_row(context.agent.id, "Private diagnosis")])
        caplog.set_level("INFO")
        capability = _capability(context)
        with when("memories are searched through the viewer"):
            _viewer(context, capability, search="Private diagnosis")

        with then("logs record identity and status, not content, search text, or the capability"):
            assert_that("Private diagnosis" in caplog.text, equal_to(False))
            assert_that(capability in caplog.text, equal_to(False))
            assert_that("memories/list" in caplog.text, equal_to(True))
