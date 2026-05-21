import uuid

from fastapi import status
from hamcrest import assert_that, equal_to, has_length

from api.infrastructure.kubernetes.client import KubernetesClient
from api.tests.core.givenpy import given, then, when
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

_BASE = "/api/v1/agents"

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
]

_SIMPLE_JSONL = (
    '{"type":"message","id":"a1","message":{"role":"assistant","content":[{"type":"toolCall",'
    '"id":"call_abc123","name":"read","arguments":{"path":"/tmp/test.txt"}}],"timestamp":1748000000000}}\n'
    '{"type":"message","id":"r1","message":{"role":"toolResult","toolCallId":"call_abc123",'
    '"toolName":"read","content":[{"type":"text","text":"hello"}],"isError":false,"timestamp":1748000001000}}\n'
)

_SESSION_FILE = "/home/node/.openclaw/agents/main/sessions/session-abc.jsonl"


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def test_list_tool_calls_no_auth_returns_401():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        with when("I request tool calls without auth"):
            response = context.client.get(f"{_BASE}/{context.agent.id}/tool-calls")

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_list_tool_calls_unknown_agent_returns_404():
    with given(_GIVEN) as context:
        unknown_id = uuid.uuid4()

        with when("I request tool calls for an unknown agent"):
            response = context.client.get(
                f"{_BASE}/{unknown_id}/tool-calls", headers=_auth(context)
            )

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_list_tool_calls_pod_not_found_returns_200_empty():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        k8s: KubernetesClient = context.injector.get(KubernetesClient)
        k8s.get_pod_name_for_deployment.return_value = None

        with when("I request tool calls but no pod is running"):
            response = context.client.get(
                f"{_BASE}/{context.agent.id}/tool-calls", headers=_auth(context)
            )

        with then("it returns 200 with empty results"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["total"], equal_to(0))
            assert_that(body["items"], has_length(0))


def test_list_tool_calls_exec_failure_returns_200_empty():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        k8s: KubernetesClient = context.injector.get(KubernetesClient)
        k8s.get_pod_name_for_deployment.return_value = "agent-pod"
        k8s.exec_command.side_effect = RuntimeError("exec failed")

        with when("I request tool calls but exec fails"):
            response = context.client.get(
                f"{_BASE}/{context.agent.id}/tool-calls", headers=_auth(context)
            )

        with then("it still returns 200 with empty results"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["total"], equal_to(0))


def test_list_tool_calls_syncs_from_pod_and_returns_results():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        k8s: KubernetesClient = context.injector.get(KubernetesClient)
        k8s.get_pod_name_for_deployment.return_value = "agent-pod"
        k8s.exec_command.side_effect = [_SESSION_FILE + "\n", _SIMPLE_JSONL]

        with when("I request tool calls and pod has JSONL data"):
            response = context.client.get(
                f"{_BASE}/{context.agent.id}/tool-calls", headers=_auth(context)
            )

        with then("it returns 200 with the synced tool call"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["total"], equal_to(1))
            item = body["items"][0]
            assert_that(item["tool_name"], equal_to("read"))
            assert_that(item["status"], equal_to("SUCCESS"))
            assert_that(item["arguments"], equal_to({"path": "/tmp/test.txt"}))


def test_list_tool_calls_pending_when_no_result():
    # JSONL with a tool call but no matching toolResult
    jsonl_no_result = (
        '{"type":"message","id":"a1","message":{"role":"assistant","content":[{"type":"toolCall",'
        '"id":"call_pending1","name":"bash","arguments":{"command":"sleep 10"}}],"timestamp":1748000000000}}\n'
    )

    with given([*_GIVEN, there_is_an_agent()]) as context:
        k8s: KubernetesClient = context.injector.get(KubernetesClient)
        k8s.get_pod_name_for_deployment.return_value = "agent-pod"
        k8s.exec_command.side_effect = [_SESSION_FILE + "\n", jsonl_no_result]

        with when("I request tool calls and the result hasn't arrived yet"):
            response = context.client.get(
                f"{_BASE}/{context.agent.id}/tool-calls", headers=_auth(context)
            )

        with then("the tool call appears with status PENDING"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["total"], equal_to(1))
            assert_that(body["items"][0]["status"], equal_to("PENDING"))


def test_list_tool_calls_filter_by_tool_name():
    read_jsonl = (
        '{"type":"message","id":"a1","message":{"role":"assistant","content":[{"type":"toolCall",'
        '"id":"call_r1","name":"read","arguments":{}}],"timestamp":1748000000000}}\n'
        '{"type":"message","id":"a2","message":{"role":"assistant","content":[{"type":"toolCall",'
        '"id":"call_b1","name":"bash","arguments":{}}],"timestamp":1748000001000}}\n'
    )

    with given([*_GIVEN, there_is_an_agent()]) as context:
        k8s: KubernetesClient = context.injector.get(KubernetesClient)
        k8s.get_pod_name_for_deployment.return_value = "agent-pod"
        k8s.exec_command.side_effect = [_SESSION_FILE + "\n", read_jsonl]

        with when("I filter tool calls by tool_name=read"):
            response = context.client.get(
                f"{_BASE}/{context.agent.id}/tool-calls?tool_name=read",
                headers=_auth(context),
            )

        with then("only the read tool call is returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["total"], equal_to(1))
            assert_that(body["items"][0]["tool_name"], equal_to("read"))


def test_list_tool_calls_filter_by_status():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        k8s: KubernetesClient = context.injector.get(KubernetesClient)
        k8s.get_pod_name_for_deployment.return_value = "agent-pod"
        k8s.exec_command.side_effect = [_SESSION_FILE + "\n", _SIMPLE_JSONL]

        with when("I filter by status=PENDING"):
            response = context.client.get(
                f"{_BASE}/{context.agent.id}/tool-calls?status=PENDING",
                headers=_auth(context),
            )

        with then("no results because the one call is SUCCESS"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["total"], equal_to(0))


def test_list_tool_calls_pagination():
    # Two tool calls in one JSONL, request page 1 with size 1
    two_calls_jsonl = (
        '{"type":"message","id":"a1","message":{"role":"assistant","content":[{"type":"toolCall",'
        '"id":"call_1","name":"read","arguments":{}}],"timestamp":1748000000000}}\n'
        '{"type":"message","id":"a2","message":{"role":"assistant","content":[{"type":"toolCall",'
        '"id":"call_2","name":"write","arguments":{}}],"timestamp":1748000001000}}\n'
    )

    with given([*_GIVEN, there_is_an_agent()]) as context:
        k8s: KubernetesClient = context.injector.get(KubernetesClient)
        k8s.get_pod_name_for_deployment.return_value = "agent-pod"
        k8s.exec_command.side_effect = [_SESSION_FILE + "\n", two_calls_jsonl]

        with when("I request page 1 with size 1"):
            response = context.client.get(
                f"{_BASE}/{context.agent.id}/tool-calls?page=1&page_size=1",
                headers=_auth(context),
            )

        with then("total is 2 but only 1 item returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["total"], equal_to(2))
            assert_that(body["items"], has_length(1))


def test_list_tool_calls_second_sync_reads_only_new_bytes():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        k8s: KubernetesClient = context.injector.get(KubernetesClient)
        k8s.get_pod_name_for_deployment.return_value = "agent-pod"

        first_call_jsonl = (
            '{"type":"message","id":"a1","message":{"role":"assistant","content":[{"type":"toolCall",'
            '"id":"call_first","name":"read","arguments":{}}],"timestamp":1748000000000}}\n'
        )
        second_call_jsonl = (
            '{"type":"message","id":"a2","message":{"role":"assistant","content":[{"type":"toolCall",'
            '"id":"call_second","name":"write","arguments":{}}],"timestamp":1748000001000}}\n'
        )

        k8s.exec_command.side_effect = [_SESSION_FILE + "\n", first_call_jsonl]

        with when("I make an initial request to seed the database"):
            seed_response = context.client.get(
                f"{_BASE}/{context.agent.id}/tool-calls", headers=_auth(context)
            )

        with then("the first call is stored"):
            assert_that(seed_response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(seed_response.json()["total"], equal_to(1))

        # Second request: same session file, tail returns only the new bytes
        k8s.exec_command.side_effect = [_SESSION_FILE + "\n", second_call_jsonl]

        with when("I request tool calls a second time with new data"):
            response = context.client.get(
                f"{_BASE}/{context.agent.id}/tool-calls", headers=_auth(context)
            )

        with then("both calls are returned (old + new)"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["total"], equal_to(2))


def test_list_tool_calls_agent_from_other_org_returns_404():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
        ]
    ) as context:
        other_org_agent_id = uuid.uuid4()

        with when("I request tool calls for an agent in another org"):
            response = context.client.get(
                f"{_BASE}/{other_org_agent_id}/tool-calls", headers=_auth(context)
            )

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
