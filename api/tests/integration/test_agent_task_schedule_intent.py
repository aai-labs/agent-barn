"""When an Agent creates a schedule, a decision model says whether the scheduled runs are part of its Task."""

from unittest.mock import Mock

import pytest
from fastapi import status
from hamcrest import assert_that, equal_to, has_entries, has_key
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
_BODY = {
    "request": "Post a greeting every day for a week. It is done after 7 greetings.",
    "schedule": {"recurrence": "every 1d", "run_limit": 7},
    "task": {"title": "Daily greeting for a week", "status": "done"},
}


def _an_agent_with_an_ingest_key():
    def step(context):
        there_is_an_agent(name="Test Agent")(context)
        repository: AgentRepository = context.injector.get(AgentRepository)
        agent = repository.get_by_id(context.agent.id)
        assert agent is not None
        agent.ingest_key_encrypted = encrypt_token(_KEY, TEST_ENCRYPTION_KEY)
        repository.save(agent)
        context.client = TestClient(create_ingest_app(injector=context.injector))

    return step


def _the_decision_model(answer: ChoiceAnswer | Exception):
    def step(context):
        result = DecisionResult(answers={"intent": answer}, input_tokens=10, output_tokens=1)
        context.decide = Mock(side_effect=answer if isinstance(answer, Exception) else None, return_value=result)
        context.injector.get(DecisionService).decide = context.decide

    return step


def _given(answer: ChoiceAnswer | Exception):
    return [
        set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization(),
        _an_agent_with_an_ingest_key(),
        _the_decision_model(answer),
    ]


def _ask(context, body=None, key: str = _KEY):
    return context.client.post(
        f"/ingest/v1/agents/{context.agent.id}/tasks/schedule-intent",
        json=_BODY if body is None else body,
        headers={"Authorization": f"Bearer {key}"},
    )


@pytest.mark.parametrize("intent", ["runs", "setup"])
def test_the_decision_models_answer_is_the_intent(intent):
    answer = ChoiceAnswer(choice=intent, confidence=0.5, probabilities={intent: 0.5})
    with given(_given(answer)) as context:
        response = _ask(context)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json(), equal_to({"intent": intent}))


def test_the_model_is_asked_about_the_request_the_schedule_and_the_task_and_billed_to_the_agent():
    with given(_given(ChoiceAnswer(choice="runs", confidence=0.9, probabilities={"runs": 0.9}))) as context:
        _ask(context)

        agent_id, state, questions = context.decide.call_args.args
        assert_that(agent_id, equal_to(context.agent.id))
        assert_that(
            state,
            has_entries(
                request=_BODY["request"],
                schedule=has_entries(recurrence="every 1d", run_limit=7),
                task=has_entries(title="Daily greeting for a week", status_the_agent_set="done"),
            ),
        )
        assert_that(questions, has_key("intent"))
        assert_that(isinstance(questions["intent"], ChoiceQuestion), equal_to(True))
        assert_that(set(questions["intent"].options), equal_to({"setup", "runs"}))


def test_no_intent_is_given_when_the_decision_fails():
    with given(_given(DecisionError(DecisionFailure.UNAVAILABLE))) as context:
        response = _ask(context)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json(), equal_to({"intent": None}))


def test_another_agents_key_is_refused_and_nothing_is_asked():
    with given(_given(ChoiceAnswer(choice="runs", confidence=0.9, probabilities={"runs": 0.9}))) as context:
        response = _ask(context, key="wrong-key")

        assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
        context.decide.assert_not_called()


def test_unknown_fields_are_refused():
    with given(_given(ChoiceAnswer(choice="runs", confidence=0.9, probabilities={"runs": 0.9}))) as context:
        response = _ask(context, body={**_BODY, "agent_id": "someone-else"})

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))
        context.decide.assert_not_called()
