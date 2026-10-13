"""What a Playbook Extraction would read, shown before anything is billed.

Conversation Messages and Tool Calls carry different session identifiers, so Tool
Calls are paired to the conversation whose time span contains their runtime session.
"""

from datetime import UTC, datetime, timedelta

from fastapi import status
from hamcrest import assert_that, equal_to, greater_than, has_entries

from api.domains.conversations.models import MessageDirection
from api.domains.rbac.catalog import AGENT_OWNER_ROLE_ID
from api.domains.users.organization_users.models import OrganizationRole
from api.tests.core.givenpy import given, then, when
from api.tests.steps.agent import there_is_agent_access, there_is_an_agent
from api.tests.steps.agent_memory import signed_in_as
from api.tests.steps.playbooks import playbooks_api_setup, there_is_a_conversation

_PREVIEW = "/api/v1/organizations/{organization_id}/agents/{agent_id}/playbook-extractions/preview"
IN = MessageDirection.INBOUND
OUT = MessageDirection.OUTBOUND


def _preview(context, **params):
    return context.client.get(
        _PREVIEW.replace("{agent_id}", str(context.agent.id)),
        params=params,
        headers={"Authorization": f"Bearer {context.access_token}"},
    )


def _days_ago(days: float) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def test_the_preview_counts_conversations_with_their_paired_tool_calls():
    with given(
        playbooks_api_setup(
            there_is_an_agent(),
            there_is_a_conversation(
                "thread-invoices",
                _days_ago(2),
                [(0, IN, "Which invoices are open?"), (60, OUT, "Three are open.")],
                tool_session_id="run-a",
                tool_calls=((10, "exec", {"command": "aai-cli invoices list"}, "3 rows"),),
            ),
            there_is_a_conversation(
                "thread-refund",
                _days_ago(1),
                [(0, IN, "Refund order 42"), (20, IN, "No, only half of it"), (90, OUT, "Refunded half.")],
                tool_session_id="run-b",
                tool_calls=(
                    (30, "exec", {"command": "aai-cli refunds create"}, "ok"),
                    (40, "exec", {"command": "aai-cli refunds show"}, "ok"),
                ),
            ),
        )
    ) as context:
        with when("the Owner previews a 30-day run"):
            response = _preview(context, window_days=30, max_sessions=20)

        with then("both conversations, their messages, and their paired Tool Calls are counted"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body, has_entries(session_count=2, message_count=5, tool_call_count=3))
            assert_that(body["estimated_input_tokens"], greater_than(body["input_chars"] // 4))
            assert_that(body["estimated_output_tokens"], greater_than(0))
            assert_that(body["model"], equal_to("openrouter/openai/gpt-4.1-mini"))


def test_the_preview_reads_only_the_most_recent_conversations_inside_the_window():
    with given(
        playbooks_api_setup(
            there_is_an_agent(),
            there_is_a_conversation("too-old", _days_ago(40), [(0, IN, "Old request")]),
            there_is_a_conversation("older", _days_ago(3), [(0, IN, "Older request")]),
            there_is_a_conversation("newest", _days_ago(1), [(0, IN, "Newest request"), (5, OUT, "Done")]),
        )
    ) as context:
        with when("the Owner previews one session from the last 30 days"):
            response = _preview(context, window_days=30, max_sessions=1)

        with then("only the newest conversation in the window is read"):
            assert_that(response.json(), has_entries(session_count=1, message_count=2))


def test_runtime_sessions_outside_every_conversation_are_not_read():
    with given(
        playbooks_api_setup(
            there_is_an_agent(),
            there_is_a_conversation("thread-a", _days_ago(1), [(0, IN, "Hello"), (30, OUT, "Hi")]),
            there_is_a_conversation(
                "unrelated",
                _days_ago(5),
                [],
                tool_session_id="startup",
                tool_calls=((0, "read", {"path": "BOOT.md"}, "ok"),),
            ),
        )
    ) as context:
        with when("the Owner previews a run"):
            response = _preview(context)

        with then("the startup Tool Call is not paired with the conversation"):
            assert_that(response.json(), has_entries(session_count=1, tool_call_count=0))


def test_another_agents_activity_is_never_read():
    with given(
        playbooks_api_setup(
            there_is_an_agent(name="Triage"),
            there_is_a_conversation(
                "shared-key",
                _days_ago(1),
                [(0, IN, "Triage request")],
                tool_session_id="run-triage",
                tool_calls=((1, "exec", {"command": "ls"}, "ok"),),
            ),
            there_is_an_agent(name="Billing"),
            there_is_a_conversation("shared-key", _days_ago(1), [(0, IN, "Billing request"), (10, OUT, "Done")]),
        )
    ) as context:
        with when("the Owner previews the Billing Agent"):
            response = _preview(context)

        with then("only Billing's own messages count, even under the same session key and time"):
            assert_that(response.json(), has_entries(session_count=1, message_count=2, tool_call_count=0))


def test_previewing_needs_skill_management_too():
    with given(
        playbooks_api_setup(
            there_is_an_agent(),
            signed_in_as(OrganizationRole.MEMBER),
            there_is_agent_access(access_role_id=AGENT_OWNER_ROLE_ID),
        )
    ) as context:
        with when("a Member who owns the Agent previews a run"):
            response = _preview(context)

        with then("it is forbidden"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_the_preview_bounds_its_settings():
    with given(playbooks_api_setup(there_is_an_agent())) as context:
        with when("the Owner previews with settings beyond the limits"):
            too_many = _preview(context, max_sessions=51)
            too_long = _preview(context, window_days=366)

        with then("both are rejected"):
            assert_that(too_many.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))
            assert_that(too_long.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))
