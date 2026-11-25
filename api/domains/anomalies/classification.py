"""What a decision model is asked about flagged activity, and how its answers are read.

Pure functions: the check service collects the Anomalies and asks the model; this module
only builds the request and reads the answers.

What goes to the model provider about the activity is derived: the signal, how far the
value went from the Agent's usual and its threshold, how long it has lasted, and what
else is flagged alongside it. Never identifiers, timestamps or tool arguments. A first
use names the tool or integration, which are the platform's own vocabulary, but never a
destination's host: a host can identify a customer.

What the Agent is for goes too, so the model can tell whether a change fits its job:
its role (the template's name and description) and the text of its latest inbound
messages. Both pass through `clean_text` first, which takes out links, hosts and IP
addresses, email addresses, phone and account numbers and anything shaped like a secret,
and a message goes without its sender, channel or thread. A destination held back from a
flagged item is also taken out of them wherever it appears, so it cannot come in through
a message instead.
"""

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from api.domains.anomalies.detection import Sensitivity
from api.domains.anomalies.models import AgentAnomaly, AnomalySignal
from api.infrastructure.litellm.decisions import (
    MAX_QUESTIONS,
    Answer,
    ChoiceAnswer,
    ChoiceQuestion,
    Question,
    ScoreAnswer,
    ScoreQuestion,
    YesNoAnswer,
    YesNoQuestion,
)

CATEGORIES: dict[str, str | None] = {
    "RUNAWAY_LOOP": "The Agent repeats the same work far beyond what the job needs, burning calls or tokens.",
    "FAILING_DEPENDENCY": "A tool, integration or model the Agent relies on keeps failing.",
    "MORE_WORK": (
        "The Agent is legitimately doing more of its usual work than usual, such as a bigger job it was asked to do."
    ),
    "NEW_CAPABILITY": "The Agent starts using something new in a way that fits ordinary work or was asked to use.",
    "RISKY_ACTION": "The activity could cause harm or expose data, such as unusual writes, deletes or new destinations.",
    "OTHER": "None of the above.",
}
SEVERITY_LEVELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
QUESTIONS_PER_ITEM = 3
MAX_ITEMS_PER_DECISION = MAX_QUESTIONS // QUESTIONS_PER_ITEM

RATE_SIGNALS = frozenset(
    {
        AnomalySignal.LLM_TOKENS_PER_HOUR,
        AnomalySignal.LLM_CALLS_PER_HOUR,
        AnomalySignal.LLM_ERROR_RATE,
        AnomalySignal.TOOL_CALLS_PER_HOUR,
        AnomalySignal.TOOL_ERROR_RATE,
        AnomalySignal.WRITES_PER_HOUR,
    }
)
CAP_SIGNALS = frozenset({AnomalySignal.LLM_TOKENS_CAP, AnomalySignal.LLM_CALLS_CAP})
# First uses whose subject may be named to the provider. NEW_DESTINATION is not one.
NAMED_FIRST_USES = frozenset(
    {AnomalySignal.NEW_TOOL, AnomalySignal.NEW_INTEGRATION, AnomalySignal.NEW_INTEGRATION_ACTION}
)


MAX_REQUEST_CHARACTERS = 300
# Only this much of a message is cleaned, so a long one costs no more than a short one.
MAX_CLEANED_CHARACTERS = 4 * MAX_REQUEST_CHARACTERS

# A host's last label that is really a file extension, as in "report.pdf". Extensions that
# are also widely used top-level domains, such as "zip", are left out: those are hosts.
_FILE_EXTENSIONS = frozenset(
    [
        "csv",
        "doc",
        "docx",
        "gif",
        "html",
        "jpeg",
        "jpg",
        "js",
        "json",
        "log",
        "md",
        "pdf",
        "png",
        "ppt",
        "pptx",
        "py",
        "sh",
        "sql",
        "svg",
        "ts",
        "tsx",
        "txt",
        "xls",
        "xlsx",
        "yaml",
        "yml",
    ]
)
_URL = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
# The lookbehinds start a match only at the start of a word, which keeps matching linear.
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_KNOWN_SECRET = re.compile(
    r"\b(?:sk|pk|rk)-[\w-]{8,}"
    r"|\bgh[pousr]_\w{20,}"
    r"|\bxox[abposr]-[\w-]{10,}"
    r"|\beyJ[\w-]+\.[\w-]+\.[\w-]+"
    r"|\bAKIA[0-9A-Z]{16}\b"
)
_BEARER = re.compile(r"\b(Bearer)\s+\S+", re.IGNORECASE)
_LONG_TOKEN = re.compile(r"(?<![A-Za-z0-9_+/=-])[A-Za-z0-9_+/=-]{24,}")
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?!\w)")
_IPV6 = re.compile(r"(?<![\w:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![\w:])", re.IGNORECASE)
_HOST = re.compile(r"(?<![\w.-])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+([a-z]{2,24})\b", re.IGNORECASE)
# The last whitespace and the partial word after it, where a message is cut short.
_PARTIAL_WORD = re.compile(r"\s\S*\Z")
_NUMBER = re.compile(r"\+?\(?\d[\d\s().-]{6,}\d")
# Fewer digits than this are a date, a time or an amount rather than a phone or account number.
_IDENTIFYING_DIGITS = 9


@dataclass(frozen=True)
class AgentRole:
    name: str
    description: str | None


@dataclass(frozen=True)
class RecentRequest:
    """The text of one message the Agent received, as written."""

    minutes_ago: int
    text: str


@dataclass(frozen=True)
class AgentContext:
    sensitivity: Sensitivity
    active_days: int
    # None for an Agent without a template.
    role: AgentRole | None = None
    # Oldest first.
    recent_requests: tuple[RecentRequest, ...] = ()


@dataclass(frozen=True)
class Classification:
    # Probability that the activity is really unusual for the Agent, not noise.
    unusual_probability: float
    category: str
    # Probability-weighted index into SEVERITY_LEVELS, 0 for LOW.
    severity: float
    # The model's full answer, kept with the Anomaly.
    details: dict[str, Any]


def classification_request(
    anomalies: Sequence[AgentAnomaly],
    context: AgentContext,
    *,
    other_ongoing: Iterable[AnomalySignal],
    withheld_hosts: Iterable[str] = (),
) -> tuple[dict[str, Any], dict[str, Question]]:
    """The state and questions for one decision about `anomalies`.

    `withheld_hosts` are destinations held back elsewhere, such as in another decision
    about the same check; they are kept out of the role and requests like the
    destinations among `anomalies`.

    Raises ValueError for more Anomalies than one decision can take.
    """
    if not 1 <= len(anomalies) <= MAX_ITEMS_PER_DECISION:
        raise ValueError(f"Classify between 1 and {MAX_ITEMS_PER_DECISION} Anomalies at a time")
    withheld = _withheld_pattern([*withheld_hosts, *withheld_destinations(anomalies)])
    state = {
        "agent": {
            "sensitivity": context.sensitivity.value,
            "active_days_in_last_14": context.active_days,
            "role": _role(context.role, withheld),
        },
        "recent_requests": [
            {"minutes_ago": request.minutes_ago, "text": _request_text(request.text, withheld)}
            for request in context.recent_requests
        ],
        "flagged": [_features(_ref(index), anomaly) for index, anomaly in enumerate(anomalies)],
        "also_ongoing": [signal.value for signal in other_ongoing],
    }
    questions: dict[str, Question] = {}
    for index in range(len(anomalies)):
        ref = _ref(index)
        questions[f"{ref}_unusual"] = YesNoQuestion(
            question=(
                f"Is flagged item {ref} really unusual for this Agent, rather than noise in its normal work? "
                "Its role and recent requests show what it is for and what it was asked, "
                "not that the activity was authorised."
            ),
            yes_means="Something has changed in what the Agent does that an Owner should look at.",
            no_means="Ordinary variation, or a change that explains itself.",
        )
        questions[f"{ref}_category"] = ChoiceQuestion(
            question=(
                f"What kind of activity is flagged item {ref}? Use the Agent's role and recent requests to judge "
                "whether the activity is work it was asked to do or that fits its job."
            ),
            options=CATEGORIES,
        )
        questions[f"{ref}_severity"] = ScoreQuestion(
            question=(
                f"How severe is flagged item {ref} for the Organization running the Agent? "
                "A risky action stays risky even when someone asked for it."
            ),
            levels=SEVERITY_LEVELS,
        )
    return state, questions


def read_classifications(
    anomalies: Sequence[AgentAnomaly], answers: Mapping[str, Answer]
) -> dict[UUID, Classification]:
    """Each Anomaly's classification from the answers to `classification_request`'s
    questions. Raises TypeError for answers of the wrong type."""
    return {anomaly.id: _classification(_ref(index), answers) for index, anomaly in enumerate(anomalies)}


def severity_level(score: float) -> str:
    """The severity level nearest a score, as the decision model reads it."""
    return SEVERITY_LEVELS[min(max(math.floor(score + 0.5), 0), len(SEVERITY_LEVELS) - 1)]


def clean_text(text: str) -> str:
    """`text` without what could identify a customer or unlock something: links, hosts
    and IP addresses, email addresses, phone and account numbers, and secrets.
    Whitespace is collapsed. Takes time linear in the length of `text`."""
    return _cleaned(text, None)


def _cleaned(text: str, withheld: re.Pattern[str] | None) -> str:
    if withheld is not None:
        text = withheld.sub("[link]", text)
    text = _URL.sub("[link]", text)
    text = _EMAIL.sub("[email]", text)
    text = _KNOWN_SECRET.sub("[secret]", text)
    text = _BEARER.sub(r"\1 [secret]", text)
    text = _LONG_TOKEN.sub(_secret_if_mixed, text)
    text = _IPV4.sub("[link]", text)
    text = _IPV6.sub(_link_if_address, text)
    text = _HOST.sub(_link_unless_file, text)
    text = _NUMBER.sub(_number_if_identifying, text)
    return " ".join(text.split())


def _secret_if_mixed(match: re.Match[str]) -> str:
    token = match.group(0)
    if any(char.isdigit() for char in token) and any(char.isalpha() for char in token):
        return "[secret]"
    return token


def _link_if_address(match: re.Match[str]) -> str:
    # A time such as 09:15:00 has two colons; an IPv6 address has more, or "::".
    address = match.group(0)
    return "[link]" if "::" in address or address.count(":") >= 3 else address


def _link_unless_file(match: re.Match[str]) -> str:
    return match.group(0) if match.group(1).lower() in _FILE_EXTENSIONS else "[link]"


def _number_if_identifying(match: re.Match[str]) -> str:
    number = match.group(0)
    return "[number]" if sum(char.isdigit() for char in number) >= _IDENTIFYING_DIGITS else number


def withheld_destinations(anomalies: Iterable[AgentAnomaly]) -> list[str]:
    """The destination hosts among `anomalies`, which never go to the provider."""
    return [
        anomaly.subject
        for anomaly in anomalies
        if anomaly.signal == AnomalySignal.NEW_DESTINATION.value and anomaly.subject
    ]


def _withheld_pattern(hosts: Iterable[str]) -> re.Pattern[str] | None:
    """Matches any of `hosts` anywhere, in any case; longest first, so a host is not
    taken out only in part."""
    unique = sorted({host for host in hosts if host}, key=len, reverse=True)
    if not unique:
        return None
    return re.compile("|".join(re.escape(host) for host in unique), re.IGNORECASE)


def _request_text(text: str, withheld: re.Pattern[str] | None) -> str:
    """A message as sent: cleaned, and cut to MAX_REQUEST_CHARACTERS.

    Only the first MAX_CLEANED_CHARACTERS are cleaned, cut back to the last whole word,
    so a secret or host split by the cut does not get through in part.
    """
    cut = len(text) > MAX_CLEANED_CHARACTERS
    if cut:
        head = text[:MAX_CLEANED_CHARACTERS]
        partial = _PARTIAL_WORD.search(head)
        # No whitespace at all: one word longer than the bound, so none of it goes.
        text = head[: partial.start()] if partial else ""
    return _shortened(_cleaned(text, withheld), cut=cut)


def _shortened(text: str, *, cut: bool) -> str:
    if not cut and len(text) <= MAX_REQUEST_CHARACTERS:
        return text
    return text[: MAX_REQUEST_CHARACTERS - 1] + "…"


def _role(role: AgentRole | None, withheld: re.Pattern[str] | None) -> dict[str, str | None] | None:
    if role is None:
        return None
    description = _cleaned(role.description, withheld) if role.description else None
    return {"name": _cleaned(role.name, withheld), "description": description}


def _ref(index: int) -> str:
    return f"a{index + 1}"


def _features(ref: str, anomaly: AgentAnomaly) -> dict[str, Any]:
    signal = AnomalySignal(anomaly.signal)
    if signal not in RATE_SIGNALS and signal not in CAP_SIGNALS:
        features: dict[str, Any] = {"ref": ref, "signal": signal.value, "kind": "first_use"}
        if signal in NAMED_FIRST_USES and anomaly.subject is not None:
            features["subject"] = anomaly.subject
        features["uses"] = int(anomaly.observed_value)
        return features
    return {
        "ref": ref,
        "signal": signal.value,
        "kind": "rate" if signal in RATE_SIGNALS else "cap",
        "observed": anomaly.observed_value,
        "usual": anomaly.usual_value,
        "threshold": anomaly.threshold,
        "times_usual": _ratio(anomaly.observed_value, anomaly.usual_value),
        "times_threshold": _ratio(anomaly.observed_value, anomaly.threshold),
        "ongoing": anomaly.ended_at is None,
        "minutes_flagged": int((anomaly.last_observed_at - anomaly.started_at).total_seconds() // 60),
    }


def _ratio(value: float, base: float | None) -> float | None:
    if base is None or base <= 0:
        return None
    return value / base


def _classification(ref: str, answers: Mapping[str, Answer]) -> Classification:
    unusual = answers[f"{ref}_unusual"]
    category = answers[f"{ref}_category"]
    severity = answers[f"{ref}_severity"]
    if (
        not isinstance(unusual, YesNoAnswer)
        or not isinstance(category, ChoiceAnswer)
        or not isinstance(severity, ScoreAnswer)
    ):
        raise TypeError(f"Unexpected answer types for {ref}")
    return Classification(
        unusual_probability=unusual.probability,
        category=category.choice,
        severity=severity.score,
        details={
            "unusual_probability": unusual.probability,
            "category": category.choice,
            "category_confidence": category.confidence,
            "category_probabilities": dict(category.probabilities),
            "severity_level": severity.level,
            "severity_score": severity.score,
            "severity_confidence": severity.confidence,
            "severity_probabilities": dict(severity.probabilities),
        },
    )
