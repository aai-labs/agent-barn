import uuid
from datetime import datetime, timezone

from fastapi import status
from hamcrest import assert_that, equal_to, has_length

from api.domains.tool_calls.models import ToolCallStatus
from api.domains.tool_calls.repository import ToolCallRepository
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


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _seed_tool_call(context, external_id, tool_name, arguments, status_val, result=None):
    repo: ToolCallRepository = context.injector.get(ToolCallRepository)
    now = datetime.now(timezone.utc)
    with repo.get_session() as session:
        repo.upsert_pending(
            session=session,
            organization_id=context.organization.id,
            agent_id=context.agent.id,
            session_id="session-abc",
            external_id=external_id,
            tool_name=tool_name,
            arguments=arguments,
            occurred_at=now,
        )
        if status_val != ToolCallStatus.PENDING:
            repo.complete(
                session=session,
                agent_id=context.agent.id,
                external_id=external_id,
                result=result,
                is_error=(status_val == ToolCallStatus.ERROR),
                completed_at=now,
            )
        session.commit()


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


def test_list_tool_calls_empty_returns_200():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        with when("I request tool calls with no data seeded"):
            response = context.client.get(
                f"{_BASE}/{context.agent.id}/tool-calls", headers=_auth(context)
            )

        with then("it returns 200 with empty results"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["total"], equal_to(0))
            assert_that(body["items"], has_length(0))


def test_list_tool_calls_returns_seeded_results():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        _seed_tool_call(
            context, "call_abc123", "read", {"path": "/tmp/test.txt"},
            ToolCallStatus.SUCCESS, result="hello",
        )

        with when("I request tool calls"):
            response = context.client.get(
                f"{_BASE}/{context.agent.id}/tool-calls", headers=_auth(context)
            )

        with then("it returns 200 with the seeded tool call"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["total"], equal_to(1))
            item = body["items"][0]
            assert_that(item["tool_name"], equal_to("read"))
            assert_that(item["status"], equal_to("SUCCESS"))
            assert_that(item["arguments"], equal_to({"path": "/tmp/test.txt"}))


def test_list_tool_calls_pending_status():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        _seed_tool_call(
            context, "call_pending1", "bash", {"command": "sleep 10"},
            ToolCallStatus.PENDING,
        )

        with when("I request tool calls"):
            response = context.client.get(
                f"{_BASE}/{context.agent.id}/tool-calls", headers=_auth(context)
            )

        with then("the tool call appears with status PENDING"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["total"], equal_to(1))
            assert_that(body["items"][0]["status"], equal_to("PENDING"))


def test_list_tool_calls_filter_by_tool_name():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        _seed_tool_call(context, "call_r1", "read", {}, ToolCallStatus.PENDING)
        _seed_tool_call(context, "call_b1", "bash", {}, ToolCallStatus.PENDING)

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
        _seed_tool_call(
            context, "call_abc123", "read", {"path": "/tmp/test.txt"},
            ToolCallStatus.SUCCESS, result="hello",
        )

        with when("I filter by status=PENDING"):
            response = context.client.get(
                f"{_BASE}/{context.agent.id}/tool-calls?status=PENDING",
                headers=_auth(context),
            )

        with then("no results because the one call is SUCCESS"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["total"], equal_to(0))


def test_list_tool_calls_pagination():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        _seed_tool_call(context, "call_1", "read", {}, ToolCallStatus.PENDING)
        _seed_tool_call(context, "call_2", "write", {}, ToolCallStatus.PENDING)

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
