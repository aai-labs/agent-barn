"""Typed questions to a decision model through the LiteLLM proxy, billed to the caller's virtual key.

Decision models (jev, OpenAI's decision models) answer a fixed set of questions about a
piece of state with calibrated probabilities instead of free text. Callers ask with the
question types here and get the answer types here back; the provider's wire vocabulary
stays inside this module, because OpenRouter's decisions route is still alpha.

Pass derived features, not raw records. The state is sent to the model as given, so a
caller that wants to keep row-level data, names or free text out of the provider must
reduce it first, e.g. to ratios, counts and z-scores.

Answers are untrusted: every question must come back answered, from the offered set and
with probabilities in range, or the whole call fails with `BAD_RESPONSE`.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import cast

import httpx
from injector import inject, singleton

from api.core.config import Config
from api.infrastructure.litellm.completions import CompletionFailure, failure_for, response_cost

# The same failure categories as chat completions; callers handle both alike.
DecisionFailure = CompletionFailure

# LiteLLM refuses more questions than this in one request.
MAX_QUESTIONS = 128
MAX_CHOICE_OPTIONS = 255
MIN_SCORE_LEVELS = 2
MAX_SCORE_LEVELS = 10


class DecisionError(Exception):
    """A decision that did not produce valid answers. Never carries request or response content."""

    def __init__(self, failure: DecisionFailure) -> None:
        super().__init__(failure.value)
        self.failure = failure


@dataclass(frozen=True)
class YesNoQuestion:
    question: str
    # What makes the answer yes, and what makes it no. Optional, but sharpen the answer.
    yes_means: str | None = None
    no_means: str | None = None


@dataclass(frozen=True)
class ChoiceQuestion:
    question: str
    # Option label to an optional description. The answer is one of the labels.
    options: Mapping[str, str | None]


@dataclass(frozen=True)
class ScoreQuestion:
    question: str
    # Ordered lowest to highest.
    levels: Sequence[str]


Question = YesNoQuestion | ChoiceQuestion | ScoreQuestion


@dataclass(frozen=True)
class YesNoAnswer:
    # Probability that the answer is yes.
    probability: float


@dataclass(frozen=True)
class ChoiceAnswer:
    choice: str
    confidence: float
    probabilities: Mapping[str, float]


@dataclass(frozen=True)
class ScoreAnswer:
    # Probability-weighted level index, 0 for the lowest level.
    score: float
    # The level nearest the score.
    level: str
    confidence: float
    # Level to probability.
    probabilities: Mapping[str, float]


Answer = YesNoAnswer | ChoiceAnswer | ScoreAnswer


@dataclass(frozen=True)
class DecisionResult:
    answers: Mapping[str, Answer]
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal | None = field(default=None)


@inject
@singleton
@dataclass
class LiteLLMDecisionClient:
    config: Config

    def decide(
        self,
        api_key: str,
        model: str,
        state: str | Mapping[str, object] | Sequence[object],
        questions: Mapping[str, Question],
        *,
        timeout_seconds: float = 60,
    ) -> DecisionResult:
        """Ask every question about `state` in one call; answers are keyed like `questions`.

        Raises ValueError for questions the models cannot answer, before any call is made.
        """
        body = {"model": model, "state": state, "questions": _wire_questions(questions)}
        try:
            # No environment proxy or redirect: the key goes only to the configured proxy.
            with httpx.Client(timeout=timeout_seconds, trust_env=False, follow_redirects=False) as client:
                response = client.post(
                    f"{self.config.litellm_base_url.rstrip('/')}/v1/systemone",
                    json=body,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
        except httpx.HTTPError:
            raise DecisionError(DecisionFailure.UNAVAILABLE) from None
        if response.status_code != 200:
            raise DecisionError(failure_for(response))
        try:
            payload = response.json()
            answers = payload["answers"]
            if not isinstance(answers, dict) or answers.keys() != questions.keys():
                raise ValueError()
            usage = payload.get("usage") or {}
            return DecisionResult(
                answers={name: _answer(question, answers[name]) for name, question in questions.items()},
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                cost_usd=response_cost(response.headers.get("x-litellm-response-cost")),
            )
        except ValueError, KeyError, TypeError, AttributeError:
            raise DecisionError(DecisionFailure.BAD_RESPONSE) from None


def _wire_questions(questions: Mapping[str, Question]) -> dict[str, dict[str, object]]:
    if not 1 <= len(questions) <= MAX_QUESTIONS:
        raise ValueError(f"Ask between 1 and {MAX_QUESTIONS} questions")
    return {_name(name): _wire_question(question) for name, question in questions.items()}


def _name(name: str) -> str:
    if not name.strip():
        raise ValueError("Every question needs a name")
    return name


def _wire_question(question: Question) -> dict[str, object]:
    if not question.question.strip():
        raise ValueError("Every question needs text")
    match question:
        case YesNoQuestion():
            wire: dict[str, object] = {"type": "noul", "instructions": question.question}
            if question.yes_means is not None or question.no_means is not None:
                wire["criteria"] = {"true": question.yes_means, "false": question.no_means}
            return wire
        case ChoiceQuestion():
            if not 2 <= len(question.options) <= MAX_CHOICE_OPTIONS:
                raise ValueError(f"A choice needs between 2 and {MAX_CHOICE_OPTIONS} options")
            return {"type": "choice", "instructions": question.question, "criteria": dict(question.options)}
        case ScoreQuestion():
            levels = list(question.levels)
            if not MIN_SCORE_LEVELS <= len(levels) <= MAX_SCORE_LEVELS or len(set(levels)) != len(levels):
                raise ValueError(f"A scale needs between {MIN_SCORE_LEVELS} and {MAX_SCORE_LEVELS} distinct levels")
            return {"type": "score", "instructions": question.question, "criteria": levels}


def _answer(question: Question, answer: object) -> Answer:
    wire = _object(answer)
    match question:
        case YesNoQuestion():
            _expect(wire, "noul")
            return YesNoAnswer(probability=_probability(wire["noul"]))
        case ChoiceQuestion():
            _expect(wire, "choice")
            choice = wire["choice"]
            if not isinstance(choice, str) or choice not in question.options:
                raise ValueError()
            return ChoiceAnswer(
                choice=choice,
                confidence=_probability(wire["confidence"]),
                probabilities=_probabilities(wire["probabilities"], {option: option for option in question.options}),
            )
        case ScoreQuestion():
            _expect(wire, "score")
            levels = list(question.levels)
            score = _number(wire["score"])
            if not 0 <= score <= len(levels) - 1:
                raise ValueError()
            return ScoreAnswer(
                score=score,
                level=levels[math.floor(score + 0.5)],
                confidence=_probability(wire["confidence"]),
                # The wire keys levels by index; callers read them by name.
                probabilities=_probabilities(wire["probabilities"], {str(i): level for i, level in enumerate(levels)}),
            )


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError()
    return cast(dict[str, object], value)


def _expect(wire: dict[str, object], kind: str) -> None:
    if wire.get("type") != kind:
        raise ValueError()


def _probabilities(wire: object, names: Mapping[str, str]) -> dict[str, float]:
    probabilities = _object(wire)
    if not probabilities.keys() <= names.keys():
        raise ValueError()
    return {names[key]: _probability(value) for key, value in probabilities.items()}


def _probability(value: object) -> float:
    number = _number(value)
    if not 0 <= number <= 1:
        raise ValueError()
    return number


def _number(value: object) -> float:
    # bool is an int in Python; a true/false here is a malformed answer, not 1 or 0.
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError()
    return float(value)
