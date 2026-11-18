"""Before a Task is marked done at the end of a turn, a decision model can say the job is not finished."""

from unittest.mock import Mock
from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, contains_exactly, equal_to, has_entries
from starlette.testclient import TestClient

from api.domains.agents.repository import AgentRepository
from api.domains.decisions.service import DecisionService
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.litellm.decisions import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionError,
    DecisionFailure,
    DecisionResult,
)
from api.ingest_app import create_ingest_app
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization

_KEY = "test-ingest-key-abc"
_HEADERS = {"Authorization": f"Bearer {_KEY}"}
_REQUEST = "Ask the QA channel what the priority is, and attach the answer to the task when it comes."
_REPLY = "I posted the question and will attach the answer when it arrives."


def _an_agent_with_an_ingest_key():
    def step(context):
        there_is_an_agent(name="Test Agent")(context)
        repository: AgentRepository = context.injector.get(AgentRepository)
        agent = repository.get_by_id(context.agent.id)
        assert agent is not None
        agent.ingest_key_encrypted = encrypt_token(_KEY, TEST_ENCRYPTION_KEY)
        repository.save(agent)
        context.client = TestClient(create_ingest_app(injector=context.injector))
        context.tasks_url = f"/ingest/v1/agents/{context.agent.id}/tasks"

    return step


def _the_decision_model_says(choice: str = "finished", confidence: float = 0.9):
    """Every Task asked about gets `choice`."""

    def step(context):
        def decide(agent_id, state, questions):
            answer = ChoiceAnswer(choice=choice, confidence=confidence, probabilities={choice: confidence})
            return DecisionResult(answers=dict.fromkeys(questions, answer), input_tokens=10, output_tokens=1)

        context.decide = Mock(side_effect=decide)
        context.injector.get(DecisionService).decide = context.decide

    return step


def _the_decision_model_fails():
    def step(context):
        context.decide = Mock(side_effect=DecisionError(DecisionFailure.UNAVAILABLE))
        context.injector.get(DecisionService).decide = context.decide

    return step


def _given(model):
    return [
        set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization(),
        _an_agent_with_an_ingest_key(),
        model,
    ]


def _a_task(context, title: str = "Ask QA for the priority") -> str:
    created = context.client.post(context.tasks_url, json={"title": title, "status": "in_progress"}, headers=_HEADERS)
    assert created.status_code == status.HTTP_201_CREATED
    return created.json()["id"]


def _task(context, task_id: str) -> dict:
    return context.client.get(f"{context.tasks_url}/{task_id}", headers=_HEADERS).json()


def _end_turn(context, closing: list[str], key: str = _KEY, **fields):
    body = {"request": _REQUEST, "reply": _REPLY, "tools": [], "closing": closing, **fields}
    return context.client.post(f"{context.tasks_url}/turn-end", json=body, headers={"Authorization": f"Bearer {key}"})


def test_a_task_whose_job_is_still_going_is_held_in_progress():
    with given(_given(_the_decision_model_says("ongoing"))) as context:
        task_id = _a_task(context)

        response = _end_turn(context, [task_id])

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json(), equal_to({"holds": {task_id: "in_progress"}}))


def test_a_task_waiting_on_the_user_is_held_open():
    with given(_given(_the_decision_model_says("waiting"))) as context:
        task_id = _a_task(context)

        response = _end_turn(context, [task_id])

        assert_that(response.json(), equal_to({"holds": {task_id: "open"}}))


def test_a_finished_task_is_not_held():
    with given(_given(_the_decision_model_says("finished"))) as context:
        task_id = _a_task(context)

        response = _end_turn(context, [task_id])

        assert_that(response.json(), equal_to({"holds": {}}))


def test_an_unsure_answer_holds_nothing():
    with given(_given(_the_decision_model_says("ongoing", confidence=0.69))) as context:
        task_id = _a_task(context)

        response = _end_turn(context, [task_id])

        assert_that(response.json(), equal_to({"holds": {}}))


def test_nothing_is_held_when_the_decision_fails():
    with given(_given(_the_decision_model_fails())) as context:
        task_id = _a_task(context)

        response = _end_turn(context, [task_id])

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json(), equal_to({"holds": {}}))


def test_the_tasks_status_is_left_for_the_plugin_to_set():
    with given(_given(_the_decision_model_says("waiting"))) as context:
        task_id = _a_task(context)

        _end_turn(context, [task_id])

        assert_that(_task(context, task_id)["status"], equal_to("in_progress"))


def test_the_model_is_not_asked_when_no_task_is_closing():
    with given(_given(_the_decision_model_says("ongoing"))) as context:
        _a_task(context)

        response = _end_turn(context, [])

        assert_that(response.json(), equal_to({"holds": {}}))
        context.decide.assert_not_called()


def test_a_closing_task_that_no_longer_exists_is_skipped():
    with given(_given(_the_decision_model_says("ongoing"))) as context:
        response = _end_turn(context, [str(uuid7())])

        assert_that(response.json(), equal_to({"holds": {}}))
        context.decide.assert_not_called()


def test_only_the_closing_tasks_are_asked_about():
    with given(_given(_the_decision_model_says("ongoing"))) as context:
        _a_task(context, title="Write the Lisbon guide")
        script = _a_task(context, title="Prime number script")

        _end_turn(context, [script])

        assert_that(list(context.decide.call_args.args[2]), contains_exactly(script))


def test_the_model_sees_the_turn_and_the_task_and_is_billed_to_the_agent():
    with given(_given(_the_decision_model_says("ongoing"))) as context:
        task_id = _a_task(context)
        context.client.post(f"{context.tasks_url}/{task_id}/notes", json={"body": "Question posted."}, headers=_HEADERS)

        _end_turn(context, [task_id], tools=["message {}"], trigger="cron")

        agent_id, state, questions = context.decide.call_args.args
        assert_that(agent_id, equal_to(context.agent.id))
        assert_that(
            state["turn"],
            has_entries(trigger="cron", request=_REQUEST, agent_reply=_REPLY, tool_calls=["message {}"]),
        )
        assert_that(
            state["tasks"][task_id],
            has_entries(title="Ask QA for the priority", notes_oldest_first=["Question posted."], files_attached=[]),
        )
        assert_that(isinstance(questions[task_id], ChoiceQuestion), equal_to(True))
        assert_that(set(questions[task_id].options), equal_to({"finished", "ongoing", "waiting"}))


def test_another_agents_key_is_refused_and_nothing_is_asked():
    with given(_given(_the_decision_model_says("ongoing"))) as context:
        task_id = _a_task(context)

        response = _end_turn(context, [task_id], key="wrong-key")

        assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
        context.decide.assert_not_called()
