"""Send approval requests: a Slack direct message telling one chosen person that a step's command
waits for a decision. Slack only notifies; the decision is made on the web page it links to.

Per docs/features/agent-workflows.md, the recipient is checked through an Agent the author can
update (`agent.update`, docs/features/rbac/IMPLEMENTATION-BRIEF.md), the message never carries
the command, and Slack's failures never touch the step or a decision.
"""

import json
import time
from uuid import UUID

import pytest
from hamcrest import (
    assert_that,
    contains_string,
    empty,
    equal_to,
    has_entries,
    has_length,
    is_,
    is_not,
    none,
)
from injector import Module, provider, singleton
from sqlmodel import Session, col, select

from api.domains.agents.models import AgentStatus
from api.domains.communications.models import CommunicationConnection
from api.domains.communications.slack_messaging import SlackClients
from api.domains.events.handlers import RetryableEventHandlerError
from api.domains.events.models import EventDelivery, OutboxMessage
from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID
from api.domains.workflows.approval_notices import ApprovalNoticeSender
from api.domains.workflows.run_models import WorkflowApprovalNotice, WorkflowApprovalRequest
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.slack.client import SlackApiError
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.integration.test_workflow_runs import attempt, start
from api.tests.integration.test_workflows import auth, base, create, member_headers
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_agent_access,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

COMMAND = "rm -rf ./out && ./deploy.sh --token=s3cr3t"
TEAM, OTHER_TEAM = "T0APPROVE", "T0ELSEWHERE"
USER = "U0DECIDER"


class FakeSlack:
    """One Slack server for every workspace in a test; each bot token belongs to one workspace."""

    def __init__(self) -> None:
        self.teams: dict[str, str] = {}
        self.users = {USER: {"id": USER, "name": "dana", "real_name": "Dana Decider", "display_name": "Dana"}}
        self.posts: list[dict] = []
        self.updates: list[dict] = []
        self.failure: Exception | None = None
        self.delay = 0.0

    def client(self, bot_token: str) -> FakeSlackClient:
        return FakeSlackClient(self, bot_token)


class FakeSlackClient:
    def __init__(self, slack: FakeSlack, bot_token: str) -> None:
        self.slack, self.bot_token = slack, bot_token

    def _maybe_fail(self) -> None:
        time.sleep(self.slack.delay)
        if self.slack.failure is not None:
            raise self.slack.failure

    def get_workspace(self) -> dict:
        team = self.slack.teams[self.bot_token]
        return {"team_id": team, "team": f"Workspace {team}", "enterprise_id": None}

    def list_users(self, search: str | None = None) -> list[dict]:
        return [user for user in self.slack.users.values() if not search or search.lower() in user["id"].lower()]

    def open_dm(self, user_id: str) -> str:
        self._maybe_fail()
        return f"D-{user_id}"

    def post_message(self, channel_id: str, text: str, thread_ts=None, blocks=None) -> str:
        self._maybe_fail()
        ts = f"1780000000.{len(self.slack.posts):06d}"
        self.slack.posts.append({"channel": channel_id, "ts": ts, "text": text, "blocks": blocks or []})
        return ts

    def update_message(self, channel_id: str, ts: str, text: str, blocks=None) -> None:
        self._maybe_fail()
        self.slack.updates.append({"channel": channel_id, "ts": ts, "text": text, "blocks": blocks or []})


class _FakeClients(SlackClients):
    def __init__(self, slack: FakeSlack) -> None:
        self.slack = slack

    def for_connection(self, bot_token: str, api_url: str | None):  # type: ignore[override]
        return self.slack.client(bot_token)


def fake_slack(context) -> None:
    context.slack = FakeSlack()
    slack = context.slack

    class SlackModule(Module):
        @provider
        @singleton
        def provide(self) -> SlackClients:
            return _FakeClients(slack)

    context.slack_module = SlackModule()


def injector_with_fake_slack(context) -> None:
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), context.slack_module])(context)


_GIVEN = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY, "WEB_APP_URL": "https://barn.example"}),
    fake_slack,
    injector_with_fake_slack,
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_an_agent(status=AgentStatus.STOPPED),
]


# --- Setup -------------------------------------------------------------------------------------------------


def slack_connection(context, agent=None, team=TEAM, enabled=True) -> CommunicationConnection:
    agent = agent or context.agent
    token = f"xoxb-{agent.id}"
    context.slack.teams[token] = team
    connection = CommunicationConnection(
        organization_id=agent.organization_id,
        agent_id=agent.id,
        platform_key="slack",
        display_name="Slack",
        enabled=enabled,
        settings={},
        credentials_encrypted=encrypt_token(
            json.dumps({"bot_token": token, "app_token": "xapp-test"}), TEST_ENCRYPTION_KEY
        ),
    )
    context.injector.get(PostgresRepositoryDelegate).save(connection)
    return connection


def notice_setting(enabled=True, user=USER, team=TEAM) -> dict:
    return {
        "enabled": enabled,
        "platform": "slack",
        "slack_user_id": user,
        "slack_user_name": "x",
        "slack_team_id": team,
    }


def set_notice(context, saved, setting, headers=None):
    return context.client.patch(
        base(context) + f"/workflows/{saved['id']}",
        headers=headers or auth(context),
        json={"expected_revision": saved["revision"], "approval_notice": setting},
    )


def workflow_sending_to_dana(context) -> dict:
    saved = create(context)
    response = set_notice(context, saved, notice_setting())
    assert_that(response.status_code, equal_to(200), response.text)
    return response.json()


def raise_request(context, saved, command=COMMAND):
    response, _, _ = start(context, saved)
    _repository, row, token = attempt(context, response.json()["id"])
    raised = context.client.post(
        f"/workflow-runtime/v1/attempts/{row.id}/approvals",
        headers={"Authorization": f"Bearer {token}"},
        json={"command": command, "runtime_run_id": "hermes-run-1"},
    )
    assert_that(raised.status_code, equal_to(200), raised.text)
    return row, token, raised.json()["id"]


def send(context, run_id) -> None:
    context.injector.get(ApprovalNoticeSender).send(UUID(str(run_id)))


def decide(context, run_id, request_id, decision):
    response = context.client.post(
        base(context) + f"/workflow-runs/{run_id}/approvals/{request_id}/decision",
        headers=auth(context),
        json={"decision": decision},
    )
    assert_that(response.status_code, equal_to(200), response.text)


def notices(context) -> list[WorkflowApprovalNotice]:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return list(session.exec(select(WorkflowApprovalNotice).order_by(col(WorkflowApprovalNotice.created_at))))


def request_state(context, request_id) -> str:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return session.get_one(WorkflowApprovalRequest, UUID(request_id)).state


def run_read(context, run_id) -> dict:
    return context.client.get(base(context) + f"/workflow-runs/{run_id}", headers=auth(context)).json()


def card_text(message: dict) -> str:
    return json.dumps(message)


def has_button(message: dict) -> bool:
    return any(block["type"] == "actions" for block in message["blocks"])


# --- The workflow setting ------------------------------------------------------------------------------------


def test_sending_approval_requests_is_off_by_default_and_sends_nothing() -> None:
    with given(_GIVEN) as context:
        slack_connection(context)
        saved = create(context)
        assert_that(saved["approval_notice"], has_entries(enabled=False, slack_user_id=None))
        row, _, _ = raise_request(context, saved)
        send(context, row.run_id)
        assert_that((notices(context), context.slack.posts), equal_to(([], [])))


def test_turning_it_on_without_a_slack_user_is_refused() -> None:
    with given(_GIVEN) as context:
        saved = create(context)
        response = set_notice(context, saved, {"enabled": True, "platform": "slack"})
        assert_that(response.status_code, equal_to(422))
        stored = context.client.get(base(context) + f"/workflows/{saved['id']}", headers=auth(context)).json()
        assert_that(stored["approval_notice"]["enabled"], is_(False))


def test_turning_it_on_stores_the_user_with_the_name_slack_gives() -> None:
    with given(_GIVEN) as context:
        slack_connection(context)
        saved = workflow_sending_to_dana(context)
        assert_that(
            saved["approval_notice"],
            equal_to(
                {
                    "enabled": True,
                    "platform": "slack",
                    "slack_user_id": USER,
                    "slack_user_name": "Dana",
                    "slack_team_id": TEAM,
                }
            ),
        )


def test_a_user_outside_every_workspace_the_author_reaches_is_refused() -> None:
    with given(_GIVEN) as context:
        slack_connection(context)
        saved = create(context)
        unknown_team = set_notice(context, saved, notice_setting(team=OTHER_TEAM))
        unknown_user = set_notice(context, saved, notice_setting(user="U0NOBODY"))
        assert_that((unknown_team.status_code, unknown_user.status_code), equal_to((400, 400)))


def test_an_author_who_cannot_update_the_slack_agent_cannot_choose_from_its_workspace() -> None:
    with given(_GIVEN) as context:
        slack_connection(context)
        member = member_headers(context)
        saved = create_as(context, member)
        there_is_agent_access(membership_id=context.member_membership.id, access_role_id=AGENT_VIEWER_ROLE_ID)(context)
        response = set_notice(context, saved, notice_setting(), headers=member)
        assert_that(response.status_code, equal_to(400))
        workspaces = context.client.get(base(context) + "/slack-workspaces", headers=member).json()
        assert_that(workspaces, empty())


def test_an_author_who_can_update_the_slack_agent_chooses_from_its_workspace() -> None:
    with given(_GIVEN) as context:
        connection = slack_connection(context)
        member = member_headers(context)
        saved = create_as(context, member)
        there_is_agent_access(membership_id=context.member_membership.id)(context)
        workspaces = context.client.get(base(context) + "/slack-workspaces", headers=member).json()
        assert_that(
            workspaces,
            equal_to(
                [
                    {
                        "team_id": TEAM,
                        "name": f"Workspace {TEAM}",
                        "connections": [
                            {
                                "agent_id": str(context.agent.id),
                                "agent_name": context.agent.name,
                                "connection_id": str(connection.id),
                            }
                        ],
                    }
                ]
            ),
        )
        assert_that(set_notice(context, saved, notice_setting(), headers=member).status_code, equal_to(200))


def test_only_those_who_may_change_the_workflow_see_its_recipient() -> None:
    with given(_GIVEN) as context:
        slack_connection(context)
        saved = workflow_sending_to_dana(context)
        member = member_headers(context)
        read = context.client.get(base(context) + f"/workflows/{saved['id']}", headers=member).json()
        assert_that(
            read["approval_notice"],
            equal_to(
                {
                    "enabled": True,
                    "platform": "slack",
                    "slack_user_id": None,
                    "slack_user_name": None,
                    "slack_team_id": None,
                }
            ),
        )


def test_a_member_who_may_not_change_the_workflow_cannot_turn_it_on() -> None:
    with given(_GIVEN) as context:
        slack_connection(context)
        saved = create(context)
        member = member_headers(context)
        assert_that(set_notice(context, saved, notice_setting(), headers=member).status_code, equal_to(403))


def create_as(context, headers) -> dict:
    from api.tests.helpers.workflows import draft

    response = context.client.post(base(context) + "/workflows", headers=headers, json={"draft": draft()})
    assert_that(response.status_code, equal_to(201), response.text)
    return response.json()


# --- Sending -------------------------------------------------------------------------------------------------


def test_a_raised_request_sends_the_chosen_user_a_link_without_the_command() -> None:
    with given(_GIVEN) as context:
        slack_connection(context)
        row, _, _ = raise_request(context, workflow_sending_to_dana(context))
        send(context, row.run_id)
        [message] = context.slack.posts
        link = f"https://barn.example/dashboard/{context.organization.id}/workflows?workflowRun={row.run_id}"
        assert_that(
            (message["channel"], has_button(message), card_text(message)),
            equal_to((f"D-{USER}", True, card_text(message))),
        )
        assert_that(card_text(message), contains_string(link))
        assert_that(card_text(message), contains_string("Review and approve"))
        for part in (COMMAND, "deploy.sh", "s3cr3t"):
            assert_that(card_text(message), is_not(contains_string(part)))


def test_the_link_carries_no_token() -> None:
    with given(_GIVEN) as context:
        slack_connection(context)
        row, token, _ = raise_request(context, workflow_sending_to_dana(context))
        send(context, row.run_id)
        [message] = context.slack.posts
        [button] = next(block for block in message["blocks"] if block["type"] == "actions")["elements"]
        assert_that(button["url"].split("?")[1], equal_to(f"workflowRun={row.run_id}"))
        assert_that(card_text(message), is_not(contains_string(token)))


def test_the_runtime_is_told_nothing_about_the_recipient() -> None:
    with given(_GIVEN) as context:
        slack_connection(context)
        saved = workflow_sending_to_dana(context)
        response, _, _ = start(context, saved)
        _repository, row, token = attempt(context, response.json()["id"])
        raised = context.client.post(
            f"/workflow-runtime/v1/attempts/{row.id}/approvals",
            headers={"Authorization": f"Bearer {token}"},
            json={"command": COMMAND, "runtime_run_id": "hermes-run-1"},
        )
        assert_that(set(raised.json()), equal_to({"id", "live_seconds"}))


@pytest.mark.parametrize("setup", ["no_connection", "disabled_connection", "other_workspace"])
def test_no_message_goes_out_without_the_agents_own_slack_in_that_workspace(setup) -> None:
    with given(_GIVEN) as context:
        slack_connection(context)
        saved = workflow_sending_to_dana(context)
        # The workflow's recipient was found through the first Agent; the run uses another one.
        there_is_an_agent(name="Runner", status=AgentStatus.STOPPED)(context)
        if setup == "disabled_connection":
            slack_connection(context, enabled=False)
        elif setup == "other_workspace":
            slack_connection(context, team=OTHER_TEAM)
        row, _, request_id = raise_request(context, saved)
        send(context, row.run_id)
        run = run_read(context, row.run_id)
        assert_that(context.slack.posts, empty())
        assert_that([notice.state for notice in notices(context)], equal_to(["SKIPPED"]))
        assert_that((run["state"], run["approval"]["state"]), equal_to(("RUNNING", "LIVE")))
        assert_that(request_state(context, request_id), equal_to("LIVE"))


def test_another_agent_in_the_workspace_does_not_send_for_the_runs_agent() -> None:
    with given(_GIVEN) as context:
        slack_connection(context)
        saved = workflow_sending_to_dana(context)
        there_is_an_agent(name="Runner without Slack", status=AgentStatus.STOPPED)(context)
        row, _, _ = raise_request(context, saved)
        send(context, row.run_id)
        assert_that((context.slack.posts, notices(context)[0].outcome), equal_to(([], "no_slack_connection")))


# --- Slack failures ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("failure", [TimeoutError("Slack timed out"), SlackApiError("chat.postMessage", "ratelimited")])
def test_a_slack_outage_is_retried_without_touching_the_step(failure) -> None:
    with given(_GIVEN) as context:
        slack_connection(context)
        context.slack.failure = failure
        row, _, request_id = raise_request(context, workflow_sending_to_dana(context))
        with pytest.raises(RetryableEventHandlerError):
            send(context, row.run_id)
        assert_that([notice.state for notice in notices(context)], equal_to(["PENDING"]))
        assert_that(request_state(context, request_id), equal_to("LIVE"))
        context.slack.failure = None
        send(context, row.run_id)
        assert_that(context.slack.posts, has_length(1))


def test_a_slow_slack_never_delays_raising_or_deciding() -> None:
    with given(_GIVEN) as context:
        slack_connection(context)
        context.slack.delay = 5
        started = time.monotonic()
        row, _, request_id = raise_request(context, workflow_sending_to_dana(context))
        decide(context, row.run_id, request_id, "approve")
        assert_that(time.monotonic() - started < 4, is_(True))
        assert_that(request_state(context, request_id), equal_to("APPROVED"))


def test_a_decision_is_not_held_up_by_a_message_being_posted() -> None:
    from concurrent.futures import ThreadPoolExecutor

    with given(_GIVEN) as context:
        slack_connection(context)
        context.slack.delay = 3
        row, _, request_id = raise_request(context, workflow_sending_to_dana(context))
        with ThreadPoolExecutor(max_workers=1) as pool:
            posting = pool.submit(send, context, row.run_id)
            time.sleep(0.5)
            started = time.monotonic()
            decide(context, row.run_id, request_id, "approve")
            assert_that(time.monotonic() - started < 2, is_(True))
            posting.result()
        # The message posted as live is brought up to date once the post lands.
        assert_that(has_button(context.slack.updates[-1]), is_(False))
        assert_that(notices(context)[0].shown_state, equal_to("APPROVED"))


def test_a_slack_refusal_is_recorded_and_not_retried() -> None:
    with given(_GIVEN) as context:
        slack_connection(context)
        context.slack.failure = SlackApiError("conversations.open", "user_not_found")
        row, _, request_id = raise_request(context, workflow_sending_to_dana(context))
        send(context, row.run_id)
        [notice] = notices(context)
        assert_that((notice.state, notice.outcome), equal_to(("FAILED", "user_not_found")))
        assert_that(request_state(context, request_id), equal_to("LIVE"))


# --- Keeping the message current -----------------------------------------------------------------------------


def _sent(context):
    slack_connection(context)
    row, token, request_id = raise_request(context, workflow_sending_to_dana(context))
    send(context, row.run_id)
    return row, token, request_id


def _runtime(row, token, request_id, path):
    return {
        "url": f"/workflow-runtime/v1/attempts/{row.id}/approvals/{request_id}{path}",
        "headers": {"Authorization": f"Bearer {token}"},
    }


def test_a_live_approval_settles_the_message_and_release_changes_nothing_more() -> None:
    with given(_GIVEN) as context:
        row, token, request_id = _sent(context)
        decide(context, row.run_id, request_id, "approve")
        send(context, row.run_id)
        assert_that(context.client.post(**_runtime(row, token, request_id, "/released")).status_code, equal_to(204))
        send(context, row.run_id)
        [update] = context.slack.updates
        assert_that((has_button(update), update["blocks"][0]["text"]["text"]), equal_to((False, "Approved")))


def test_a_decline_settles_the_message() -> None:
    with given(_GIVEN) as context:
        row, _, request_id = _sent(context)
        decide(context, row.run_id, request_id, "decline")
        send(context, row.run_id)
        [update] = context.slack.updates
        assert_that((has_button(update), update["blocks"][0]["text"]["text"]), equal_to((False, "Declined")))


def test_a_parked_request_keeps_the_link_and_says_the_step_is_paused() -> None:
    with given(_GIVEN) as context:
        row, token, request_id = _sent(context)
        assert_that(context.client.post(**_runtime(row, token, request_id, "/park")).status_code, equal_to(200))
        send(context, row.run_id)
        [update] = context.slack.updates
        assert_that(has_button(update), is_(True))
        assert_that(card_text(update), contains_string("paused, waiting for your decision"))
        decide(context, row.run_id, request_id, "approve")
        send(context, row.run_id)
        assert_that(has_button(context.slack.updates[-1]), is_(False))


def test_cancelling_the_run_closes_the_message_without_a_decision() -> None:
    with given(_GIVEN) as context:
        row, token, request_id = _sent(context)
        context.client.post(**_runtime(row, token, request_id, "/park"))
        run = run_read(context, row.run_id)
        cancelled = context.client.post(
            base(context) + f"/workflow-runs/{row.run_id}/cancel",
            headers=auth(context),
            json={"expected_revision": run["revision"]},
        )
        assert_that(cancelled.status_code, equal_to(200), cancelled.text)
        send(context, row.run_id)
        update = context.slack.updates[-1]
        assert_that(
            (has_button(update), update["blocks"][0]["text"]["text"]), equal_to((False, "Closed without a decision"))
        )


def test_a_request_decided_before_the_message_went_out_is_not_posted() -> None:
    with given(_GIVEN) as context:
        slack_connection(context)
        row, _, request_id = raise_request(context, workflow_sending_to_dana(context))
        decide(context, row.run_id, request_id, "decline")
        send(context, row.run_id)
        [notice] = notices(context)
        assert_that(
            (context.slack.posts, notice.state, notice.outcome), equal_to(([], "SKIPPED", "settled_before_sent"))
        )


def test_a_recipient_changed_after_the_request_was_raised_does_not_redirect_it() -> None:
    with given(_GIVEN) as context:
        slack_connection(context)
        saved = workflow_sending_to_dana(context)
        row, _, _ = raise_request(context, saved)
        off = set_notice(context, saved, notice_setting(enabled=False))
        assert_that(off.status_code, equal_to(200))
        send(context, row.run_id)
        assert_that(context.slack.posts, has_length(1))


# --- Wiring and the runtime boundary -------------------------------------------------------------------------


def test_every_run_change_is_also_delivered_to_the_approval_notice_handler() -> None:
    with given(_GIVEN) as context:
        start(context)
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            event = session.exec(select(OutboxMessage).where(OutboxMessage.event_name == "workflow.run.changed")).one()
            handlers = session.exec(
                select(EventDelivery.handler_name).where(EventDelivery.event_id == event.event_id)
            ).all()
        assert_that(sorted(handlers), equal_to(["workflow.approval_notice", "workflow.controller"]))


def test_no_runtime_callback_route_records_a_decision() -> None:
    with given(_GIVEN) as context:
        runtime_routes = sorted(
            f"{sorted(route.methods)} {route.path}"
            for route in context.app.routes
            if getattr(route, "path", "").startswith("/workflow-runtime")
        )
        assert_that([path for path in runtime_routes if "decision" in path or "decide" in path], empty())
        row, token, request_id = raise_request(context, create(context))
        attempts = [
            context.client.post(**_runtime(row, token, request_id, "/decision"), json={"decision": "approve"}),
            context.client.post(**_runtime(row, token, request_id, "/released")),
            context.client.put(**_runtime(row, token, request_id, ""), json={"state": "APPROVED"}),
        ]
        assert_that([response.status_code for response in attempts], equal_to([404, 409, 405]))
        assert_that(request_state(context, request_id), equal_to("LIVE"))
        assert_that(run_read(context, row.run_id)["approval"]["decided_by_user_id"], none())
