import hashlib
import json
from pathlib import Path
from uuid import uuid7

import pytest
from hamcrest import assert_that, contains_exactly, empty, equal_to, has_entries, is_not, none

from api.domains.agent_memory.models import AgentMemoryGrant
from api.domains.agents.models import Agent, AgentStatus
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.helpers.memory_backend import memory_gateway_is_ready
from api.tests.steps.agent import there_is_an_agent
from api.tests.steps.agent_memory import agent_memory_api_setup, memory_is_enabled, two_agents

_BASE = "/memory/v1/v1/default/banks/forged-bank"
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "agent_memory"
_CAPTURES = [
    (runtime, row)
    for runtime in ("hermes", "openclaw")
    for row in json.loads((_FIXTURES / f"{runtime}.json").read_text())
]


def _scope_tags(payload):
    return [scope["tags"][0] for scope in payload["tag_groups"][0]["or"]]


def _headers(context):
    return {"Authorization": f"Bearer {context.memory_key}"}


def _request(context, endpoint="memories/recall", body=None):
    return context.memory_client.post(
        f"{_BASE}/{endpoint}", json=body or {"query": "sample fact"}, headers=_headers(context)
    )


def _grant(context, source_id=None, access="read"):
    grant = AgentMemoryGrant(
        organization_id=context.organization.id, agent_id=context.agent.id, source_agent_id=source_id, access=access
    )
    context.injector.get(PostgresRepositoryDelegate).save(grant)
    return grant


@pytest.mark.parametrize("runtime,capture", _CAPTURES)
def test_recorded_plugin_requests_are_accepted_and_scoped(runtime, capture):
    with given(
        agent_memory_api_setup(
            there_is_an_agent(status=AgentStatus.RUNNING), memory_is_enabled(), memory_gateway_is_ready()
        )
    ) as context:
        shared = any("scope:team" in (item.get("tags") or []) for item in (capture.get("body") or {}).get("items", []))
        if shared:
            _grant(context, access="read_write")
        with when("a runtime sends its captured request"):
            response = context.memory_client.request(
                capture["method"], "/memory/v1" + capture["path"], json=capture.get("body"), headers=_headers(context)
            )

        with then("the wire contract is accepted"):
            assert_that(response.status_code, equal_to(200))
        with then("bank and visibility belong to the authenticated Agent"):
            if capture["path"] == "/health":
                assert_that(response.json(), equal_to({"status": "ok"}))
                assert_that(context.backend_requests, empty())
            else:
                upstream = context.backend_requests[0]
                assert_that(upstream["authorization"], equal_to("Bearer gateway-upstream-test-key"))
                if capture["method"] == "POST":
                    assert_that(upstream["path"].split("/")[4], equal_to(f"org-{context.organization.id}"))
                    payload = upstream["payload"]
                    if capture["path"].endswith("/memories"):
                        assert_that(
                            payload["items"][0]["tags"],
                            equal_to(
                                [f"author:{context.agent.id}", "scope:team"]
                                if shared
                                else [f"agent:{context.agent.id}"]
                            ),
                        )
                        assert_that(payload["items"][0]["observation_scopes"], equal_to("per_tag"))
                    else:
                        assert_that(_scope_tags(payload), contains_exactly(f"agent:{context.agent.id}"))
                        assert_that(payload["tag_groups"][0]["or"][0]["match"], equal_to("exact"))


@pytest.mark.parametrize("authorization", [None, "Bearer bad", "Basic per-agent-memory-test-key"])
def test_gateway_rejects_invalid_credentials(authorization):
    with given(
        agent_memory_api_setup(
            there_is_an_agent(status=AgentStatus.RUNNING), memory_is_enabled(), memory_gateway_is_ready()
        )
    ) as context:
        with when("an unauthenticated request reaches the gateway"):
            response = context.memory_client.post(
                f"{_BASE}/memories/recall",
                json={"query": "fact"},
                headers={"Authorization": authorization} if authorization else {},
            )
        with then("it is rejected before contacting Hindsight"):
            assert_that(response.status_code, equal_to(401))
            assert_that(context.backend_requests, empty())


@pytest.mark.parametrize("state", ["disabled", "stopped", "error", "deleted"])
def test_gateway_rechecks_agent_lifecycle(state):
    with given(
        agent_memory_api_setup(
            there_is_an_agent(status=AgentStatus.RUNNING), memory_is_enabled(), memory_gateway_is_ready()
        )
    ) as context:
        agent = context.agent
        if state == "disabled":
            agent.memory_enabled = False
        elif state == "deleted":
            agent.deleted_at = agent.updated_at
        else:
            agent.status = AgentStatus(state.upper())
        context.injector.get(PostgresRepositoryDelegate).save(agent)
        with when("the Agent reuses its key after a lifecycle change"):
            response = _request(context)
        with then("the key grants no access"):
            assert_that(response.status_code, equal_to(401))
            assert_that(context.backend_requests, empty())


def test_grants_and_revocations_apply_on_the_next_request():
    with given(agent_memory_api_setup(two_agents(), memory_is_enabled(), memory_gateway_is_ready())) as context:
        # Stored memories stay readable even though their source has memory disabled.
        _request(context)
        source_grant = _grant(context, context.billing.id)
        _grant(context)
        with when("the Agent recalls with grants and after one is revoked"):
            _request(context)
            context.injector.get(PostgresRepositoryDelegate).delete(source_grant)
            _request(context)
        with then("each request reflects the current grants"):
            tags = [_scope_tags(r["payload"]) for r in context.backend_requests]
            assert_that(tags[0], contains_exactly(f"agent:{context.triage.id}"))
            assert_that(
                tags[1], contains_exactly(f"agent:{context.triage.id}", f"agent:{context.billing.id}", "scope:team")
            )
            assert_that(tags[2], contains_exactly(f"agent:{context.triage.id}", "scope:team"))


@pytest.mark.parametrize("grant_access", [None, "read", "read_write"])
def test_retain_forces_tags_and_separates_private_and_team_documents(grant_access):
    with given(
        agent_memory_api_setup(
            there_is_an_agent(status=AgentStatus.RUNNING), memory_is_enabled(), memory_gateway_is_ready()
        )
    ) as context:
        team_granted = grant_access == "read_write"
        if grant_access:
            _grant(context, access=grant_access)
        body = {
            "items": [
                {"content": "private fact", "document_id": "same-session", "tags": ["agent:other"]},
                {
                    "content": "shared fact",
                    "document_id": "same-session",
                    "tags": ["scope:team", "agent:other"],
                    "observation_scopes": "shared",
                    "strategy": "unsafe",
                    "entities": [{"id": "other-entity"}],
                },
            ],
            "document_tags": ["scope:team"],
            "bank_id": "other-org",
        }
        with when("the Agent attempts to forge retain visibility"):
            response = _request(context, "memories", body)
        if not team_granted:
            assert_that(response.status_code, equal_to(403))
            assert_that(context.backend_requests, empty())
            return
        with then("only the granted scope can be written"):
            assert_that(response.status_code, equal_to(200))
            payload = context.backend_requests[0]["payload"]
            private, shared = payload["items"]
            assert_that(private["tags"], contains_exactly(f"agent:{context.agent.id}"))
            assert_that(
                shared["tags"],
                equal_to(
                    [f"author:{context.agent.id}", "scope:team"] if team_granted else [f"agent:{context.agent.id}"]
                ),
            )
            assert_that(shared["observation_scopes"], equal_to("per_tag"))
            assert_that("entities" in shared or "strategy" in shared or "document_tags" in payload, equal_to(False))
            assert_that(shared["document_id"] == private["document_id"], equal_to(not team_granted))


def test_recall_cannot_override_tags_or_enable_unverified_response_surfaces():
    with given(
        agent_memory_api_setup(
            there_is_an_agent(status=AgentStatus.RUNNING), memory_is_enabled(), memory_gateway_is_ready()
        )
    ) as context:
        with when("the Agent asks for arbitrary tags and raw traces"):
            response = _request(
                context,
                body={
                    "query": "fact",
                    "tags": ["agent:other"],
                    "tags_match": "any",
                    "tag_groups": [{"not": {"tags": []}}],
                    "trace": True,
                    "include": {"chunks": {}, "source_facts": {}},
                },
            )
        with then("the gateway enforces the safe recall surface"):
            assert_that(response.status_code, equal_to(200))
            payload = context.backend_requests[0]["payload"]
            assert_that(
                payload,
                has_entries(
                    tag_groups=[{"or": [{"tags": [f"agent:{context.agent.id}"], "match": "exact"}]}], trace=False
                ),
            )
            assert_that(payload["include"], has_entries(chunks=none(), source_facts=none()))
            assert_that("tags" in payload, equal_to(False))


def test_reflect_cannot_enable_global_directives_or_tool_traces():
    with given(
        agent_memory_api_setup(
            there_is_an_agent(status=AgentStatus.RUNNING), memory_is_enabled(), memory_gateway_is_ready()
        )
    ) as context:
        with when("the Agent requests all directives and a tool trace"):
            response = _request(
                context,
                "reflect",
                {
                    "query": "fact",
                    "apply_all_directives": True,
                    "include": {"tool_calls": {}},
                    "exclude_mental_model_ids": ["foreign-id"],
                },
            )
        with then("the gateway scopes reflection and disables unverified surfaces"):
            assert_that(response.status_code, equal_to(200))
            assert_that(
                context.backend_requests[0]["payload"],
                has_entries(
                    tag_groups=[{"or": [{"tags": [f"agent:{context.agent.id}"], "match": "exact"}]}],
                    apply_all_directives=False,
                    exclude_mental_models=True,
                    include={"facts": None, "tool_calls": None},
                ),
            )


@pytest.mark.parametrize("body", [None, b"{invalid"])
@pytest.mark.parametrize(
    "method,endpoint,expected",
    [
        ("GET", "memories", 403),
        ("DELETE", "memories", 403),
        ("POST", "directives", 403),
        ("GET", "operations/foreign-id", 404),
    ],
)
def test_gateway_denies_other_operations(method, endpoint, expected, body):
    with given(
        agent_memory_api_setup(
            there_is_an_agent(status=AgentStatus.RUNNING), memory_is_enabled(), memory_gateway_is_ready()
        )
    ) as context:
        with when("the Agent calls an operation outside the allowlist"):
            response = context.memory_client.request(
                method, f"{_BASE}/{endpoint}", content=body, headers=_headers(context)
            )
        with then("no request reaches Hindsight"):
            assert_that(response.status_code, equal_to(expected))
            assert_that(context.backend_requests, empty())


def test_upstream_errors_do_not_expose_backend_content_or_headers():
    with given(
        agent_memory_api_setup(
            there_is_an_agent(status=AgentStatus.RUNNING), memory_is_enabled(), memory_gateway_is_ready()
        )
    ) as context:
        context.backend_status = 500
        context.backend_response = {"secret": "another agent's content"}
        with when("Hindsight fails with private diagnostic content"):
            response = _request(context)
        with then("the gateway returns a bounded error"):
            assert_that(response.status_code, equal_to(502))
            assert_that(response.json(), equal_to({"detail": "Agent Memory backend rejected the request."}))
            assert_that(response.headers.get("X-Backend-Secret"), none())


def test_each_start_rotates_memory_key_and_stop_revokes_access():
    with given(
        agent_memory_api_setup(
            there_is_an_agent(model="litellm/gpt-5-mini"), memory_is_enabled(), memory_gateway_is_ready()
        )
    ) as context:
        url = f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}"
        auth = {"Authorization": f"Bearer {context.access_token}"}
        k8s = context.injector.get(KubernetesClient)
        with when("the Agent starts, stops, and starts again"):
            first = context.client.post(url + "/start", headers=auth)
            assert_that(first.status_code, equal_to(200))
            key = k8s.create_secret.call_args.args[1].string_data["MEMORY_API_KEY"]
            context.memory_key = key
            assert_that(_request(context).status_code, equal_to(200))
            context.client.post(url + "/stop", headers=auth)
            assert_that(_request(context).status_code, equal_to(401))
            second = context.client.post(url + "/start", headers=auth)
            assert_that(second.status_code, equal_to(200))
        with then("the old key remains invalid and only the new key is stored as a hash"):
            assert_that(_request(context).status_code, equal_to(401))
            new_key = k8s.create_secret.call_args.args[1].string_data["MEMORY_API_KEY"]
            assert_that(new_key, is_not(equal_to(key)))
            agent = context.injector.get(PostgresRepositoryDelegate).find_by_id(Agent, context.agent.id)
            assert_that(agent.memory_key_hash, equal_to(hashlib.sha256(new_key.encode()).hexdigest()))
            context.memory_key = new_key
            assert_that(_request(context).status_code, equal_to(200))
            assert_that("memory_key_hash" in second.json(), equal_to(False))


def test_operation_and_document_ids_are_namespaced_per_agent():
    with given(agent_memory_api_setup(two_agents(), memory_is_enabled(), memory_gateway_is_ready())) as context:
        body = {
            "items": [{"content": "fact", "document_id": "same-session"}],
            "async": True,
            "operation_id": str(uuid7()),
        }
        with when("two Agents send identical client IDs"):
            _request(context, "memories", body)
            context.agent = context.billing
            context.memory_key = "second-agent-memory-key"
            context.agent.memory_enabled = True
            context.agent.memory_key_hash = hashlib.sha256(context.memory_key.encode()).hexdigest()
            context.injector.get(PostgresRepositoryDelegate).save(context.agent)
            _request(context, "memories", body)
        with then("neither Agent can address the other's document or operation"):
            first, second = [request["payload"] for request in context.backend_requests]
            assert_that(first["operation_id"], is_not(equal_to(second["operation_id"])))
            assert_that(first["items"][0]["document_id"], is_not(equal_to(second["items"][0]["document_id"])))


def test_deleted_sources_are_removed_from_recall_tags():
    with given(agent_memory_api_setup(two_agents(), memory_is_enabled(), memory_gateway_is_ready())) as context:
        _grant(context, context.billing.id)
        context.billing.deleted_at = context.billing.updated_at
        context.injector.get(PostgresRepositoryDelegate).save(context.billing)
        with when("the reader recalls after its source is deleted"):
            response = _request(context)
        with then("the source's tag is absent"):
            assert_that(response.status_code, equal_to(200))
            assert_that(
                _scope_tags(context.backend_requests[0]["payload"]), contains_exactly(f"agent:{context.triage.id}")
            )


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        ("memories/recall", {}),
        ("reflect", {"query": ""}),
        ("memories", {"items": []}),
        ("memories", {"items": [{"tags": ["scope:team"]}]}),
    ],
)
def test_invalid_gateway_requests_do_not_reach_hindsight(endpoint, payload):
    with given(
        agent_memory_api_setup(
            there_is_an_agent(status=AgentStatus.RUNNING), memory_is_enabled(), memory_gateway_is_ready()
        )
    ) as context:
        with when("a malformed request is sent"):
            response = context.memory_client.post(f"{_BASE}/{endpoint}", json=payload, headers=_headers(context))
        with then("validation rejects it before any backend work"):
            assert_that(response.status_code, equal_to(422))
            assert_that(context.backend_requests, empty())


def test_gateway_logs_do_not_contain_memory_or_keys(caplog):
    with given(
        agent_memory_api_setup(
            there_is_an_agent(status=AgentStatus.RUNNING), memory_is_enabled(), memory_gateway_is_ready()
        )
    ) as context:
        with when("the gateway handles private memory content"):
            with caplog.at_level("INFO", logger="api.domains.agent_memory.gateway_service"):
                _request(context, body={"query": "private-memory-marker", "tags": ["forged-tag-marker"]})
        with then("only request metadata is logged"):
            assert_that("private-memory-marker" in caplog.text, equal_to(False))
            assert_that("forged-tag-marker" in caplog.text, equal_to(False))
            assert_that(context.memory_key in caplog.text, equal_to(False))
            assert_that(f"agent={context.agent.id}" in caplog.text, equal_to(True))


def test_agents_without_memory_receive_no_memory_credentials():
    with given(agent_memory_api_setup(there_is_an_agent(model="litellm/gpt-5-mini"))) as context:
        url = f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/start"
        with when("an Agent starts with memory disabled"):
            response = context.client.post(url, headers={"Authorization": f"Bearer {context.access_token}"})
        with then("no memory key is persisted or injected"):
            assert_that(response.status_code, equal_to(200))
            agent = context.injector.get(PostgresRepositoryDelegate).find_by_id(Agent, context.agent.id)
            assert_that(agent.memory_key_hash, none())
            secret = context.injector.get(KubernetesClient).create_secret.call_args.args[1]
            assert_that("MEMORY_API_KEY" in secret.string_data, equal_to(False))
            deployment = context.injector.get(KubernetesClient).create_deployment.call_args.args[1]
            assert_that(deployment.spec.template.spec.automount_service_account_token, equal_to(False))


@pytest.mark.parametrize("read,write", [(False, False), (True, False), (False, True)])
def test_organization_write_includes_read_and_revocation_is_immediate(read, write):
    with given(
        agent_memory_api_setup(
            there_is_an_agent(status=AgentStatus.RUNNING), memory_is_enabled(), memory_gateway_is_ready()
        )
    ) as context:
        if read:
            _grant(context)
        writer = _grant(context, access="read_write") if write else None
        recall = _request(context)
        assert_that(recall.status_code, equal_to(200))
        assert_that("scope:team" in _scope_tags(context.backend_requests[-1]["payload"]), equal_to(read or write))
        response = context.memory_client.post(
            "/memory/v1/organization-memory", json={"content": "Shared convention"}, headers=_headers(context)
        )
        assert_that(response.status_code, equal_to(202 if write else 403))
        if write:
            payload = context.backend_requests[-1]["payload"]
            assert_that(payload["items"][0]["tags"], contains_exactly(f"author:{context.agent.id}", "scope:team"))
            assert_that(payload["async"], equal_to(True))
            context.injector.get(PostgresRepositoryDelegate).delete(writer)
            response = context.memory_client.post(
                "/memory/v1/organization-memory", json={"content": "Refused fact"}, headers=_headers(context)
            )
            assert_that(response.status_code, equal_to(403))
            recall = _request(context)
            assert_that(recall.status_code, equal_to(200))
            assert_that("scope:team" in _scope_tags(context.backend_requests[-1]["payload"]), equal_to(False))


def test_organization_write_tool_endpoint_rejects_identity_and_tag_overrides():
    with given(
        agent_memory_api_setup(
            there_is_an_agent(status=AgentStatus.RUNNING), memory_is_enabled(), memory_gateway_is_ready()
        )
    ) as context:
        _grant(context, access="read_write")
        response = context.memory_client.post(
            "/memory/v1/organization-memory",
            json={"content": "fact", "agent_id": "other", "tags": ["agent:other"]},
            headers=_headers(context),
        )
        assert_that(response.status_code, equal_to(422))
        assert_that(context.backend_requests, empty())


def test_recall_suppresses_bank_wide_entity_names_even_when_requested():
    with given(
        agent_memory_api_setup(
            there_is_an_agent(status=AgentStatus.RUNNING), memory_is_enabled(), memory_gateway_is_ready()
        )
    ) as context:
        response = _request(context, body={"query": "Who do we know?", "include": {"entities": {"max_tokens": 2000}}})
        assert_that(response.status_code, equal_to(200))
        assert_that(context.backend_requests[0]["payload"]["include"]["entities"], equal_to(None))
