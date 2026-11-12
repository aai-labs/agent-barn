"""The decision client against a loopback stand-in for the LiteLLM proxy."""

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from hamcrest import assert_that, empty, equal_to

from api.infrastructure.litellm.decisions import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionError,
    DecisionFailure,
    DecisionResult,
    LiteLLMDecisionClient,
    Question,
    ScoreAnswer,
    ScoreQuestion,
    YesNoAnswer,
    YesNoQuestion,
)
from api.tests.helpers.litellm_proxy import StubProxy, litellm_proxy

MODEL = "openrouter/typesafe/jev-1.14"
QUESTIONS: dict[str, Question] = {
    "unusual": YesNoQuestion("Is this spend pattern unusual?", yes_means="Far off baseline", no_means="Normal"),
    "cause": ChoiceQuestion("What drives it?", options={"volume": "More calls", "model": "Pricier model"}),
    "severity": ScoreQuestion("How severe is it?", levels=["low", "medium", "high"]),
}


def _client(base_url: str) -> LiteLLMDecisionClient:
    config = MagicMock()
    config.litellm_base_url = base_url
    return LiteLLMDecisionClient(config=config)


def _decide(stub: StubProxy, questions: dict[str, Question] | None = None) -> DecisionResult:
    with litellm_proxy(stub) as base_url:
        return _client(base_url).decide(
            "sk-agent-key", MODEL, {"spend_ratio": 3.2}, QUESTIONS if questions is None else questions
        )


def _answers(**overrides: Any) -> dict[str, Any]:
    answers: dict[str, Any] = {
        "unusual": {"type": "noul", "noul": 0.91},
        "cause": {
            "type": "choice",
            "choice": "volume",
            "confidence": 0.8,
            "probabilities": {"volume": 0.8, "model": 0.2},
        },
        "severity": {
            "type": "score",
            "score": 1.6,
            "confidence": 0.7,
            "legend": {"0": "low", "1": "medium", "2": "high"},
            "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7},
        },
    }
    answers.update(overrides)
    return {"model": "typesafe/jev-1.14", "answers": answers, "usage": {"input_tokens": 476, "output_tokens": 70}}


def _without(name: str) -> dict[str, Any]:
    body = _answers()
    del body["answers"][name]
    return body


def test_the_request_carries_the_agent_key_model_state_and_translated_questions():
    stub = StubProxy(body=_answers())

    _decide(stub)

    [request] = stub.requests
    assert_that(request["path"], equal_to("/v1/systemone"))
    assert_that(request["authorization"], equal_to("Bearer sk-agent-key"))
    assert_that(
        request["json"],
        equal_to(
            {
                "model": MODEL,
                "state": {"spend_ratio": 3.2},
                "questions": {
                    "unusual": {
                        "type": "noul",
                        "instructions": "Is this spend pattern unusual?",
                        "criteria": {"true": "Far off baseline", "false": "Normal"},
                    },
                    "cause": {
                        "type": "choice",
                        "instructions": "What drives it?",
                        "criteria": {"volume": "More calls", "model": "Pricier model"},
                    },
                    "severity": {
                        "type": "score",
                        "instructions": "How severe is it?",
                        "criteria": ["low", "medium", "high"],
                    },
                },
            }
        ),
    )


def test_a_yes_no_question_without_meanings_sends_only_its_instructions():
    stub = StubProxy(body={"answers": {"q": {"type": "noul", "noul": 0.5}}})

    _decide(stub, {"q": YesNoQuestion("Is it late?")})

    assert_that(stub.requests[0]["json"]["questions"], equal_to({"q": {"type": "noul", "instructions": "Is it late?"}}))


def test_answers_come_back_typed_with_usage_and_reported_cost():
    result = _decide(StubProxy(body=_answers(), headers={"x-litellm-response-cost": "0.00002"}))

    assert_that(
        result,
        equal_to(
            DecisionResult(
                answers={
                    "unusual": YesNoAnswer(probability=0.91),
                    "cause": ChoiceAnswer(choice="volume", confidence=0.8, probabilities={"volume": 0.8, "model": 0.2}),
                    "severity": ScoreAnswer(
                        score=1.6,
                        level="high",
                        confidence=0.7,
                        probabilities={"low": 0.1, "medium": 0.2, "high": 0.7},
                    ),
                },
                input_tokens=476,
                output_tokens=70,
                cost_usd=Decimal("0.00002"),
            )
        ),
    )


def test_a_missing_cost_is_unknown_rather_than_zero():
    assert_that(_decide(StubProxy(body=_answers())).cost_usd, equal_to(None))


def test_the_nearest_level_names_a_fractional_score():
    severity = {"type": "score", "score": 0.4, "confidence": 0.9, "probabilities": {"0": 0.6, "1": 0.4}}

    result = _decide(StubProxy(body=_answers(severity=severity)))

    severity_answer = result.answers["severity"]
    assert isinstance(severity_answer, ScoreAnswer)
    assert_that(severity_answer.level, equal_to("low"))


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(_without("cause"), id="a question left unanswered"),
        pytest.param(_answers(extra={"type": "noul", "noul": 0.5}), id="an answer to a question not asked"),
        pytest.param(_answers(unusual={"type": "choice", "choice": "volume"}), id="an answer of the wrong kind"),
        pytest.param(_answers(unusual={"type": "noul", "noul": 1.2}), id="a probability above one"),
        pytest.param(_answers(unusual={"type": "noul", "noul": -0.1}), id="a probability below zero"),
        pytest.param(_answers(unusual={"type": "noul", "noul": True}), id="a boolean probability"),
        pytest.param(_answers(unusual={"type": "noul", "noul": "0.9"}), id="a text probability"),
        pytest.param(_answers(unusual={"type": "noul", "noul": float("nan")}), id="a probability that is not a number"),
        pytest.param(
            _answers(cause={"type": "choice", "choice": "weather", "confidence": 0.8, "probabilities": {"volume": 1}}),
            id="a choice outside the offered set",
        ),
        pytest.param(
            _answers(cause={"type": "choice", "choice": "volume", "confidence": 0.8, "probabilities": {"rain": 0.1}}),
            id="a probability for an option not offered",
        ),
        pytest.param(
            _answers(cause={"type": "choice", "choice": "volume", "confidence": 1.5, "probabilities": {"volume": 1}}),
            id="a confidence above one",
        ),
        pytest.param(
            _answers(severity={"type": "score", "score": 2.5, "confidence": 0.7, "probabilities": {"2": 1}}),
            id="a score beyond the top level",
        ),
        pytest.param(
            _answers(severity={"type": "score", "score": 1, "confidence": 0.7, "probabilities": {"3": 1}}),
            id="a probability for a level not offered",
        ),
        pytest.param(_answers(unusual=0.91), id="an answer that is not an object"),
        pytest.param({"answers": ["not", "a", "map"]}, id="answers that are not a map"),
        pytest.param(["not", "an", "object"], id="a body that is not an object"),
    ],
)
def test_an_answer_that_does_not_fit_the_questions_is_a_bad_response(body):
    with pytest.raises(DecisionError) as raised:
        _decide(StubProxy(body=body))

    assert_that(raised.value.failure, equal_to(DecisionFailure.BAD_RESPONSE))


@pytest.mark.parametrize(
    "status,body,failure",
    [
        (422, {"error": {"type": "budget_exceeded", "message": "Budget has been exceeded"}}, "budget_exceeded"),
        (
            400,
            {"error": {"type": "invalid_request_error", "message": "Invalid Decisions request"}},
            "key_or_model_rejected",
        ),
        (401, {"error": {"type": "auth_error", "message": "Invalid key"}}, "key_or_model_rejected"),
        (502, {"error": "upstream"}, "unavailable"),
    ],
)
def test_proxy_errors_are_classified_without_their_text(status, body, failure):
    with pytest.raises(DecisionError) as raised:
        _decide(StubProxy(status=status, body=body))

    assert_that(raised.value.failure, equal_to(DecisionFailure(failure)))
    assert_that(str(raised.value), equal_to(failure))


def test_an_unreachable_proxy_is_unavailable():
    with litellm_proxy(StubProxy()) as base_url:
        pass

    with pytest.raises(DecisionError) as raised:
        _client(base_url).decide("sk-agent-key", MODEL, "state", QUESTIONS, timeout_seconds=2)

    assert_that(raised.value.failure, equal_to(DecisionFailure.UNAVAILABLE))


@pytest.mark.parametrize(
    "questions",
    [
        pytest.param({}, id="no questions"),
        pytest.param({f"q{i}": YesNoQuestion("?") for i in range(129)}, id="more questions than allowed"),
        pytest.param({"": YesNoQuestion("?")}, id="an unnamed question"),
        pytest.param({"q": YesNoQuestion("")}, id="a blank question"),
        pytest.param({"q": ChoiceQuestion("?", options={"only": None})}, id="a choice with one option"),
        pytest.param({"q": ScoreQuestion("?", levels=["one"])}, id="a scale with one level"),
        pytest.param({"q": ScoreQuestion("?", levels=[str(i) for i in range(11)])}, id="a scale with eleven levels"),
        pytest.param({"q": ScoreQuestion("?", levels=["low", "low"])}, id="a scale with repeated levels"),
    ],
)
def test_questions_the_models_cannot_answer_are_refused_before_any_call(questions):
    stub = StubProxy(body=_answers())

    with pytest.raises(ValueError):
        _decide(stub, questions)

    assert_that(stub.requests, empty())
