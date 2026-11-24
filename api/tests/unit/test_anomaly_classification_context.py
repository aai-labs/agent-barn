"""What the decision model is told about the Agent's job (AF-459).

Alongside the derived features, the model gets the Agent's role (its template's name and
description) and what it was recently asked to do: the text of its latest inbound
messages, cleaned of links, hosts, email addresses, phone numbers and secrets, and
never with who sent them or where.
"""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from hamcrest import assert_that, contains_exactly, contains_string, equal_to, has_entries, has_length

from api.domains.anomalies.classification import (
    MAX_REQUEST_CHARACTERS,
    AgentContext,
    AgentRole,
    RecentRequest,
    classification_request,
    clean_text,
)
from api.domains.anomalies.detection import Sensitivity
from api.domains.anomalies.models import AgentAnomaly, AnomalySignal
from api.infrastructure.litellm.decisions import ChoiceQuestion

STARTED = datetime(2026, 11, 16, 11, 0, tzinfo=UTC)


def _rate():
    return AgentAnomaly(
        organization_id=uuid4(),
        agent_id=uuid4(),
        signal=AnomalySignal.WRITES_PER_HOUR.value,
        observed_value=40.0,
        usual_value=4.0,
        threshold=10.0,
        started_at=STARTED,
        last_observed_at=STARTED,
    )


def _context(*, role: AgentRole | None = None, requests: tuple[RecentRequest, ...] = ()) -> AgentContext:
    return AgentContext(sensitivity=Sensitivity.NORMAL, active_days=9, role=role, recent_requests=requests)


def _state(context: AgentContext) -> dict:
    state, _ = classification_request([_rate()], context, other_ongoing=[])
    return state


def test_the_agent_is_described_by_its_role():
    state = _state(_context(role=AgentRole(name="Sales assistant", description="Keeps the CRM tidy.")))

    assert_that(
        state["agent"],
        has_entries(role=equal_to({"name": "Sales assistant", "description": "Keeps the CRM tidy."})),
    )


def test_an_agent_without_a_template_has_no_role():
    assert_that(_state(_context())["agent"], has_entries(role=None))


def test_the_role_is_cleaned_like_a_request():
    role = AgentRole(name="Support", description="Answers mail sent to help@acme.example via https://acme.example/desk")

    sent = json.dumps(_state(_context(role=role)))

    assert "acme.example" not in sent
    assert "help@" not in sent


def test_recent_requests_say_what_the_agent_was_asked_and_how_long_ago():
    requests = (
        RecentRequest(minutes_ago=300, text="Archive last quarter's closed deals"),
        RecentRequest(minutes_ago=20, text="Now delete the archived ones"),
    )

    assert_that(
        _state(_context(requests=requests))["recent_requests"],
        contains_exactly(
            equal_to({"minutes_ago": 300, "text": "Archive last quarter's closed deals"}),
            equal_to({"minutes_ago": 20, "text": "Now delete the archived ones"}),
        ),
    )


def test_no_recent_requests_is_an_empty_list():
    assert_that(_state(_context())["recent_requests"], equal_to([]))


def test_a_long_request_is_cut_short():
    text = _state(_context(requests=(RecentRequest(minutes_ago=1, text="word " * 200),)))["recent_requests"][0]["text"]

    assert_that(text, has_length(MAX_REQUEST_CHARACTERS))
    assert text.endswith("…")


def test_the_questions_say_a_request_is_not_an_authorisation():
    _, questions = classification_request([_rate()], _context(), other_ongoing=[])

    assert_that(questions["a1_unusual"].question, contains_string("not that the activity was authorised"))
    assert_that(questions["a1_severity"].question, contains_string("stays risky even when someone asked for it"))


def test_the_category_is_judged_against_the_role_and_requests():
    _, questions = classification_request([_rate()], _context(), other_ongoing=[])

    category = questions["a1_category"]
    assert isinstance(category, ChoiceQuestion)
    assert_that(category.question, contains_string("role and recent requests"))
    assert "a bigger job it was asked to do" in (category.options["MORE_WORK"] or "")
    assert "or was asked to use" in (category.options["NEW_CAPABILITY"] or "")


@pytest.mark.parametrize(
    "raw, cleaned",
    [
        ("Pull the report from https://portal.acme.example/x?id=42 today", "Pull the report from [link] today"),
        ("check www.acme.example/pricing", "check [link]"),
        ("is reports.dept.example.org up?", "is [link] up?"),
        ("Email jane.doe+crm@acme.example the summary", "Email [email] the summary"),
        ("Call +1 (415) 555-0134 tomorrow", "Call [number] tomorrow"),
        ("account 004512339871", "account [number]"),
        ("use key sk-proj-AbCdEf1234567890xyz", "use key [secret]"),
        ("token ghp_abcdefghijklmnopqrstuvwxyz0123456789", "token [secret]"),
        ("slack xoxb-1234567890-abcdefghij", "slack [secret]"),
        ("Authorization: Bearer abc.def-123", "Authorization: Bearer [secret]"),
        ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl", "jwt [secret]"),
        ("aws AKIAIOSFODNN7EXAMPLE", "aws [secret]"),
        ("pass Zx81kQ0pLm4Rt7Yw2Vb9Nc3Hs6", "pass [secret]"),
        ("  lots \n\n of   space  ", "lots of space"),
    ],
)
def test_cleaning_removes_what_could_identify_or_unlock(raw, cleaned):
    assert_that(clean_text(raw), equal_to(cleaned))


@pytest.mark.parametrize(
    "kept",
    [
        "Send the Q3 report.pdf and notes.md to the team",
        "Meeting on 2026-11-24 at 14:30, budget 12,500",
        "Reply e.g. with a short thank-you",
        "Summarise the onboarding_checklist_for_new_hires",
    ],
)
def test_cleaning_keeps_ordinary_words_dates_and_file_names(kept):
    assert_that(clean_text(kept), equal_to(kept))
